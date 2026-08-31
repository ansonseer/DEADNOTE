"""B 线验收测试的公共底座。

思路：用 wechatpy 自己的 encrypt_message 构造出「企业微信发来的加密 POST」——
它输出的 <Encrypt> 密文与 <MsgSignature> 签名，正是 decrypt_message 校验的那套格式，
所以不需要真实企业微信环境就能整段回放渠道层。
"""

import os
import sqlite3
import sys
import time

import pytest
import xmltodict
from wechatpy.enterprise.crypto import WeChatCrypto

# 让 tests 能 import 同目录层级的 app 包
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# 测试用固定凭据（EncodingAESKey 必须是 43 位 base64 字符）
TEST_TOKEN = "test-token"
TEST_AES_KEY = "abcdefghijklmnopqrstuvwxyz0123456789ABCDEFG"
TEST_CORP_ID = "wwtestcorpid12345"


@pytest.fixture
def crypto():
    return WeChatCrypto(TEST_TOKEN, TEST_AES_KEY, TEST_CORP_ID)


@pytest.fixture
def settings(tmp_path):
    from app.config import Settings

    return Settings(
        corp_id=TEST_CORP_ID,
        token=TEST_TOKEN,
        aes_key=TEST_AES_KEY,
        corp_secret="dummy-secret",
        agent_id="1000002",
        db_path=str(tmp_path / "bot.db"),
    )


@pytest.fixture
def make_inbound(crypto):
    """构造一条加密的 inbound 消息，返回 (query_params, post_body_bytes)。

    重发同一个返回值 == 模拟企业微信 5 秒超时后的原包重试。
    """

    def _make(content, msg_id, from_user="TestUser", msg_type="text"):
        create_time = int(time.time())
        if msg_type == "text":
            inner = (
                "<MsgType><![CDATA[text]]></MsgType>"
                f"<Content><![CDATA[{content}]]></Content>"
                f"<MsgId>{msg_id}</MsgId>"
            )
        else:
            inner = f"<MsgType><![CDATA[{msg_type}]]></MsgType><MsgId>{msg_id}</MsgId>"
        plain = (
            "<xml>"
            f"<ToUserName><![CDATA[{TEST_CORP_ID}]]></ToUserName>"
            f"<FromUserName><![CDATA[{from_user}]]></FromUserName>"
            f"<CreateTime>{create_time}</CreateTime>"
            f"{inner}"
            "<AgentID>1000002</AgentID>"
            "</xml>"
        )
        nonce = f"nonce{msg_id}"
        timestamp = str(create_time)
        envelope = xmltodict.parse(crypto.encrypt_message(plain, nonce, timestamp))["xml"]
        params = {
            "msg_signature": envelope["MsgSignature"],
            "timestamp": timestamp,
            "nonce": nonce,
        }
        body = (
            "<xml>"
            f"<ToUserName><![CDATA[{TEST_CORP_ID}]]></ToUserName>"
            f"<Encrypt><![CDATA[{envelope['Encrypt']}]]></Encrypt>"
            "<AgentID><![CDATA[1000002]]></AgentID>"
            "</xml>"
        ).encode()
        return params, body

    return _make


class FakeWeComClient:
    """替身推送客户端：记录 send_text 调用，不出网。"""

    def __init__(self):
        self.sent = []

    async def send_text(self, touser, content):
        self.sent.append((touser, content))
        return {"errcode": 0, "errmsg": "ok"}


@pytest.fixture
def fake_wecom():
    return FakeWeComClient()


def wait_until(cond, timeout=10.0, interval=0.05):
    """轮询等待异步 worker 的结果。返回 cond 最终是否为真。"""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if cond():
            return True
        time.sleep(interval)
    return cond()


def query_messages(db_path):
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    try:
        return [dict(r) for r in conn.execute("SELECT * FROM messages ORDER BY id")]
    finally:
        conn.close()
