"""B 线验收测试（先于实现编写，交接简报 §5 B线）。

验收标准：
1. 同一条消息模拟重试 3 次，只主动推送 1 次（MsgId 幂等）
2. 处理耗时 >5 秒的消息：回调仍 <1 秒返回空串确认，消息最终正常送达
3. messages 表落全量日志（含 C/D 线预留字段，可回放）
4. access_token：内存缓存、过期前刷新、42001/40014 强刷重试
5. A 线行为回归：GET URL 验证裸文本、坏签名 403、/health

第 3 条验收里的「企业微信后台配置可信IP」是管理后台人工操作，见 README。
"""

import asyncio
import time

import httpx
from starlette.testclient import TestClient

from conftest import wait_until, query_messages


def make_app(settings, fake_wecom, handler=None):
    from app.server import create_app

    return create_app(settings, wecom_client=fake_wecom, handler=handler)


# ---------------------------------------------------------------- 验收 1：幂等


def test_same_message_retried_3_times_pushes_once(settings, fake_wecom, make_inbound):
    params, body = make_inbound("你好，营业时间是？", msg_id="7000000000000001")
    with TestClient(make_app(settings, fake_wecom)) as client:
        for _ in range(3):
            resp = client.post("/wecom/callback", params=params, content=body)
            assert resp.status_code == 200
            assert resp.text == ""

        assert wait_until(lambda: len(fake_wecom.sent) >= 1), "worker 未在时限内推送"
        time.sleep(0.5)  # 留出窗口，确认没有第 2 次推送
        assert fake_wecom.sent == [("TestUser", "收到：你好，营业时间是？")]

    rows = query_messages(settings.db_path)
    assert len(rows) == 1, "重试 3 次应只落 1 行（msg_id UNIQUE）"
    assert rows[0]["status"] == "done"


def test_two_distinct_messages_both_delivered(settings, fake_wecom, make_inbound):
    p1, b1 = make_inbound("第一条", msg_id="7000000000000011")
    p2, b2 = make_inbound("第二条", msg_id="7000000000000012")
    with TestClient(make_app(settings, fake_wecom)) as client:
        client.post("/wecom/callback", params=p1, content=b1)
        client.post("/wecom/callback", params=p2, content=b2)
        assert wait_until(lambda: len(fake_wecom.sent) == 2)
    assert fake_wecom.sent == [
        ("TestUser", "收到：第一条"),
        ("TestUser", "收到：第二条"),
    ]


# ------------------------------------------- 验收 2：>5 秒处理仍送达，确认不超时


def test_slow_processing_acks_immediately_and_still_delivers(
    settings, fake_wecom, make_inbound
):
    async def slow_echo(msg):
        await asyncio.sleep(5.5)  # 超过企业微信 5 秒被动回复窗口
        return f"收到：{msg['content']}"

    params, body = make_inbound("这条要处理很久", msg_id="7000000000000002")
    with TestClient(make_app(settings, fake_wecom, handler=slow_echo)) as client:
        t0 = time.monotonic()
        resp = client.post("/wecom/callback", params=params, content=body)
        ack_seconds = time.monotonic() - t0

        assert resp.status_code == 200
        assert resp.text == ""
        assert ack_seconds < 1.0, f"确认耗时 {ack_seconds:.2f}s，必须与处理解耦"

        assert wait_until(lambda: len(fake_wecom.sent) == 1, timeout=10)
        assert fake_wecom.sent[0] == ("TestUser", "收到：这条要处理很久")

    rows = query_messages(settings.db_path)
    assert rows[0]["status"] == "done"
    assert rows[0]["latency_ms"] >= 5000


# ---------------------------------------------------------- 验收 3：全量日志


def test_messages_table_logs_full_pipeline(settings, fake_wecom, make_inbound):
    params, body = make_inbound("挂号多少钱", msg_id="7000000000000003", from_user="Anson")
    with TestClient(make_app(settings, fake_wecom)) as client:
        client.post("/wecom/callback", params=params, content=body)
        assert wait_until(lambda: len(fake_wecom.sent) == 1)

    row = query_messages(settings.db_path)[0]
    # B 线已落的字段
    assert row["msg_id"] == "7000000000000003"
    assert row["from_user"] == "Anson"
    assert row["msg_type"] == "text"
    assert row["content"] == "挂号多少钱"
    assert row["reply"] == "收到：挂号多少钱"
    assert row["status"] == "done"
    assert row["latency_ms"] is not None and row["latency_ms"] >= 0
    assert row["received_at"] is not None
    assert row["done_at"] is not None
    assert row["error"] is None
    # C/D 线预留字段必须已在 schema 中（全链路可回放的结构就位）
    for reserved in ("retrieval_json", "prompt", "guardrail_json", "token_usage_json"):
        assert reserved in row, f"messages 表缺少预留字段 {reserved}"


def test_restart_replays_unfinished_messages(settings, fake_wecom):
    """已确认（status=received）但进程挂掉没处理完的消息，重启后要重新入队送达。"""
    from app import db as appdb

    appdb.init_db(settings.db_path)
    appdb.insert_message_if_new(
        settings.db_path, "7000000000000009", "TestUser", "text", "重启前没处理完", 0
    )
    with TestClient(make_app(settings, fake_wecom)):
        assert wait_until(lambda: len(fake_wecom.sent) == 1)
    assert fake_wecom.sent[0] == ("TestUser", "收到：重启前没处理完")
    assert query_messages(settings.db_path)[0]["status"] == "done"


def test_push_failure_marks_row_failed(settings, make_inbound):
    class BrokenClient:
        async def send_text(self, touser, content):
            raise RuntimeError("simulated 60011 no privilege")

    params, body = make_inbound("推送会失败", msg_id="7000000000000004")
    with TestClient(make_app(settings, BrokenClient())) as client:
        client.post("/wecom/callback", params=params, content=body)
        assert wait_until(
            lambda: query_messages(settings.db_path)[0]["status"] == "failed"
        )
    row = query_messages(settings.db_path)[0]
    assert "60011" in row["error"]


# ------------------------------------------------- 验收 4：access_token 生命周期


def _token_transport(state, expires_in=7200, send_errcodes=None):
    """gettoken 每次发新 token（tok1, tok2…）；send 按 send_errcodes 依次返回。"""
    send_errcodes = list(send_errcodes or [])

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/cgi-bin/gettoken":
            state["gettoken_calls"] += 1
            return httpx.Response(
                200,
                json={
                    "errcode": 0,
                    "access_token": f"tok{state['gettoken_calls']}",
                    "expires_in": expires_in,
                },
            )
        if request.url.path == "/cgi-bin/message/send":
            state["send_calls"] += 1
            state["send_tokens"].append(request.url.params["access_token"])
            code = send_errcodes.pop(0) if send_errcodes else 0
            return httpx.Response(200, json={"errcode": code, "errmsg": "mock"})
        raise AssertionError(f"unexpected url {request.url}")

    return httpx.MockTransport(handler)


def _new_state():
    return {"gettoken_calls": 0, "send_calls": 0, "send_tokens": []}


def test_access_token_cached_across_sends(settings):
    from app.wecom import WeComClient

    state = _new_state()

    async def scenario():
        http = httpx.AsyncClient(transport=_token_transport(state))
        client = WeComClient(
            settings.corp_id, settings.corp_secret, settings.agent_id, http=http
        )
        await client.send_text("u1", "第一条")
        await client.send_text("u1", "第二条")
        await http.aclose()

    asyncio.run(scenario())
    assert state["send_calls"] == 2
    assert state["gettoken_calls"] == 1, "7200s 内应复用缓存的 access_token"


def test_access_token_refreshed_before_expiry(settings):
    from app.wecom import WeComClient

    state = _new_state()

    async def scenario():
        # expires_in=1 落在刷新余量之内 → 每次发送都应换新 token
        http = httpx.AsyncClient(transport=_token_transport(state, expires_in=1))
        client = WeComClient(
            settings.corp_id, settings.corp_secret, settings.agent_id, http=http
        )
        await client.send_text("u1", "第一条")
        await client.send_text("u1", "第二条")
        await http.aclose()

    asyncio.run(scenario())
    assert state["gettoken_calls"] == 2, "临近过期必须提前刷新，不能拿旧 token 去撞 42001"


def test_access_token_force_refresh_on_42001(settings):
    from app.wecom import WeComClient

    state = _new_state()

    async def scenario():
        # 第一次 send 返回 42001（token 过期），应强刷 token 后重试一次
        http = httpx.AsyncClient(transport=_token_transport(state, send_errcodes=[42001]))
        client = WeComClient(
            settings.corp_id, settings.corp_secret, settings.agent_id, http=http
        )
        await client.send_text("u1", "只发一条")
        await http.aclose()

    asyncio.run(scenario())
    assert state["send_calls"] == 2
    assert state["gettoken_calls"] == 2
    assert state["send_tokens"] == ["tok1", "tok2"], "重试必须带新 token"


# ------------------------------------------------------------- A 线行为回归


def test_url_verification_returns_bare_plaintext(settings, fake_wecom, crypto):
    import xmltodict

    plain = "8768593966987651354"  # 企业微信 GET 验证里 echostr 解出来是随机串
    envelope = xmltodict.parse(crypto.encrypt_message(plain, "vnonce", "1234567890"))["xml"]
    with TestClient(make_app(settings, fake_wecom)) as client:
        resp = client.get(
            "/wecom/callback",
            params={
                "msg_signature": envelope["MsgSignature"],
                "timestamp": "1234567890",
                "nonce": "vnonce",
                "echostr": envelope["Encrypt"],
            },
        )
    assert resp.status_code == 200
    assert resp.text == plain, "echostr 必须裸文本原样返回"


def test_invalid_signature_rejected_with_403(settings, fake_wecom, make_inbound):
    params, body = make_inbound("bad", msg_id="7000000000000005")
    params["msg_signature"] = "0" * 40
    with TestClient(make_app(settings, fake_wecom)) as client:
        resp = client.post("/wecom/callback", params=params, content=body)
    assert resp.status_code == 403
    assert fake_wecom.sent == []
    assert query_messages(settings.db_path) == []


def test_health(settings, fake_wecom):
    with TestClient(make_app(settings, fake_wecom)) as client:
        resp = client.get("/health")
    assert resp.status_code == 200
    assert resp.json() == {"status": "ok"}
