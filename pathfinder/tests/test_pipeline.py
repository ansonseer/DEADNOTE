"""端到端测试：mock 模型 + 虚构示例数据，验证整条管道、评分边界、CRM 状态机、packet 往返。"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))


@pytest.fixture()
def env(tmp_path, monkeypatch):
    monkeypatch.setenv("PF_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("PF_MOCK", "1")
    from pathfinder.config import settings
    from pathfinder.db import connect
    from pathfinder.llm import Router
    from pathfinder.search import get_searcher
    conn = connect(tmp_path / "pathfinder.db")
    router = Router(settings, conn=conn, force_mock=True)
    return conn, router, get_searcher(), settings, tmp_path


def test_mock_outputs_match_schemas():
    from pathfinder.llm.mock import mock_result
    from pathfinder.schemas import BY_TASK, coerce, validate
    ctx = {"company_name": "X", "team_name": "T", "people": [{"name": "A", "title": "负责人"}], "category_id": 2, "title": "AI 应用工程师"}
    for task, schema in BY_TASK.items():
        validate(coerce(mock_result(task, ctx), schema), schema)


def test_score_bounds():
    from pathfinder.config import settings
    from pathfinder.stages.rank import compute_score, tier_for
    hi, _ = compute_score(settings, {"category_id": 1, "role_match": 10, "seniority_fit": 10, "direction": "agent", "team_verified": True,
                                     "experience_overlap": 10, "city_factor": 1.0, "path_level": 5, "path_potential": 5,
                                     "au_bridge": True, "fresh_signal_days": 3, "has_asset": True})
    lo, bd = compute_score(settings, {"category_id": 0, "role_match": 0, "seniority_fit": 0, "direction": "model_research",
                                      "team_verified": False, "experience_overlap": 0, "city_factor": 0.3, "path_level": 0, "path_potential": 0})
    assert 95 <= hi <= 100 and tier_for(settings, hi) == "A1"
    assert 0 <= lo < 20 and tier_for(settings, lo) == "C"
    assert set(bd) >= {"role_match", "team_direction", "experience_overlap", "feasibility", "path", "bonuses", "total"}


def test_full_pipeline_and_crm(env):
    conn, router, searcher, settings, tmp = env
    from pathfinder import crm
    from pathfinder.db import get, rows
    from pathfinder.demo import run_demo
    from pathfinder.stages.rank import top

    out = run_demo(conn, router, searcher, settings)
    assert any("作战卡" in line for line in out)
    opps = top(conn, 10)
    assert len(opps) >= 4, "四条岗位 + 一个纯团队机会"
    assert all(o["tier"] in {"A1", "A2", "B", "C"} for o in opps)
    assert (tmp / "cards" / "index.md").exists() and (tmp / "briefs").exists()
    card = (tmp / "cards").glob("01_*.md").__next__().read_text(encoding="utf-8")
    for section in ("公司是什么", "哪个 BU / Team", "什么岗位", "为什么适合你", "这个团队最近在做什么", "谁最值得联系",
                    "为什么联系这个人", "第一条私信怎么发", "能不能走内推", "下一步行动", "评分拆解", "证据"):
        assert section in card
    # 中澳双足迹的公司拿到 au_bridge 加分
    south = [o for o in opps if o["company"].startswith("南岸云")]
    assert south and "au_bridge" in json.loads(south[0]["breakdown"])["bonuses"]["note"]
    # 纯团队机会（海岭）存在且没有岗位
    assert any(o["company"].startswith("海岭") and o["job_title"] is None for o in opps)

    # ---- CRM：私信 → 回复 → 会议 → 内推 ----
    first = opps[0]
    pid = first["person_id"]
    assert pid, "Top1 机会应关联联系人"
    p = crm.log_touch(conn, settings, pid, "first_msg", channel="maimai")
    assert p["relationship"] == "contacted" and p["path_level"] >= 1
    assert get(conn, "opportunities", first["id"])["stage"] == "contacted"
    assert any("follow-up 1" in t["action"] for t in crm.due_tasks(conn, within_hours=24 * 30))
    p = crm.log_touch(conn, settings, pid, "reply", channel="maimai", content="可以聊")
    assert p["relationship"] == "replied" and p["path_level"] >= 2
    assert get(conn, "opportunities", first["id"])["stage"] == "replied"
    assert not any("follow-up" in t["action"] for t in crm.due_tasks(conn, within_hours=24 * 30)), "回复后 follow-up 任务应取消"
    p = crm.log_touch(conn, settings, pid, "meeting", channel="wechat")
    assert p["relationship"] == "warm"
    assert p["path_level"] == (4 if p["role_type"] in {"hiring_manager", "team_lead", "exec"} else 3)
    crm.log_touch(conn, settings, pid, "ask", content="问 headcount")
    assert get(conn, "opportunities", first["id"])["stage"] == "referral_requested"
    assert crm.account_warnings(conn, settings), "只索取未给予 → 提醒"
    crm.log_touch(conn, settings, pid, "value_given", content="发了评测对比")
    assert not crm.account_warnings(conn, settings)
    m = crm.metrics(conn)
    assert m["contacted"] == 1 and m["replied"] == 1 and m["reply_rate"] == 1.0
    # 重新评分后路径分数提升，Top1 不降级
    from pathfinder.stages.rank import rank
    ranked = rank(conn, router, settings)
    assert ranked[0]["id"] == first["id"]
    assert ranked[0]["score"] >= first["fit_score"]


def test_packet_roundtrip(env):
    conn, router, searcher, settings, tmp = env
    from pathfinder.db import insert, rows
    from pathfinder.llm.mock import mock_result
    from pathfinder.packets import ingest
    from pathfinder.stages import scan
    cid = insert(conn, "companies", {"name": "测试公司", "tier": 3, "status": "pilot"})
    msgs = scan.enrich(conn, router, settings, "测试公司", packet=True)
    assert msgs and "packet" in msgs[0]
    result_file = next((tmp / "packets").glob("company_enrich__*.result.json"))
    payload = json.loads(result_file.read_text(encoding="utf-8"))
    payload["result"] = mock_result("company_enrich", payload["context"])
    result_file.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    msg = ingest(conn, settings, result_file)
    assert "团队假设" in msg
    assert rows(conn, "SELECT id FROM teams WHERE company_id = ?", (cid,))


def test_research_without_evidence_exports_packet_when_not_mock(env, monkeypatch):
    """没有搜索、又不是 mock 时，研究阶段必须导出 packet 而不是让模型编造。"""
    conn, router, searcher, settings, tmp = env
    from pathfinder.db import insert
    from pathfinder.stages import research
    cid = insert(conn, "companies", {"name": "无证据公司", "tier": 3, "status": "pilot"})
    insert(conn, "teams", {"company_id": cid, "name": "某团队", "confidence": 0.3})
    monkeypatch.setattr(router, "is_mock", lambda task: False)
    msg = research.research_company(conn, router, searcher, settings, {"id": cid, "name": "无证据公司", "au_footprint": 0})
    assert "packet" in msg and "编造" in msg
    assert list((tmp / "packets").glob("team_research__*.md"))


# ---------------------------------------------------------------------------
# 国内模型的联网接口：用假客户端验证循环与解析逻辑（不需要真实 key）
# ---------------------------------------------------------------------------

class _Obj:
    def __init__(self, **kw):
        self.__dict__.update(kw)


def _resp(content, finish_reason="stop", tool_calls=None, web_search=None):
    msg = _Obj(content=content, tool_calls=tool_calls)
    r = _Obj(choices=[_Obj(message=msg, finish_reason=finish_reason)], usage=_Obj(prompt_tokens=10, completion_tokens=5))
    if web_search is not None:
        r.web_search = web_search
    return r


class _FakeChat:
    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = []

    def create(self, **kwargs):
        self.calls.append(kwargs)
        return self.responses.pop(0)


def _provider(monkeypatch, name, cfg):
    monkeypatch.setenv(cfg["api_key_env"], "test-key")
    from pathfinder.llm.providers import OpenAICompatProvider
    return OpenAICompatProvider(name, cfg)


def test_kimi_builtin_web_search_loop(monkeypatch):
    prov = _provider(monkeypatch, "kimi", {"base_url": "https://api.moonshot.cn/v1", "model": "kimi-k3",
                                           "api_key_env": "MOONSHOT_API_KEY", "web_search": "moonshot_builtin", "max_search_uses": 3})
    assert prov.supports_search
    tc = _Obj(id="call_1", function=_Obj(name="$web_search", arguments='{"search_query": "阿里云 百炼 解决方案"}'))
    final = '```json\n{"team_name": "T", "url": "https://example.com/a"}\n```'
    chat = _FakeChat([_resp(None, finish_reason="tool_calls", tool_calls=[tc]), _resp(final)])
    prov.client = _Obj(chat=_Obj(completions=chat))
    res = prov.complete_json("team_research", "sys", "user", {}, web_search=True)
    assert res.data["team_name"] == "T"
    assert res.citations == ["https://example.com/a"]
    # 第一次带工具声明；第二次把 arguments 原样作为 tool 结果回传
    assert chat.calls[0]["tools"] == [{"type": "builtin_function", "function": {"name": "$web_search"}}]
    tool_msg = [m for m in chat.calls[1]["messages"] if m.get("role") == "tool"][0]
    assert tool_msg["tool_call_id"] == "call_1" and tool_msg["content"] == '{"search_query": "阿里云 百炼 解决方案"}'
    assert "response_format" not in chat.calls[0]


def test_zhipu_web_search_tool(monkeypatch):
    prov = _provider(monkeypatch, "zhipu", {"base_url": "https://open.bigmodel.cn/api/paas/v4", "model": "glm-5.3",
                                            "api_key_env": "ZHIPU_API_KEY", "web_search": "zhipu_tool", "search_engine": "search_pro"})
    chat = _FakeChat([_resp('{"ok": true}', web_search=[{"title": "x", "link": "https://example.com/z", "content": "..."}])])
    prov.client = _Obj(chat=_Obj(completions=chat))
    res = prov.complete_json("team_research", "sys", "user", {}, web_search=True)
    assert res.data == {"ok": True} and res.citations == ["https://example.com/z"]
    tool = chat.calls[0]["tools"][0]
    assert tool["type"] == "web_search" and tool["web_search"]["enable"] is True and tool["web_search"]["search_engine"] == "search_pro"


def test_plain_provider_json_mode_and_fallback(monkeypatch):
    prov = _provider(monkeypatch, "deepseek", {"base_url": "https://api.deepseek.com", "model": "deepseek-chat",
                                               "api_key_env": "DEEPSEEK_API_KEY"})
    assert not prov.supports_search
    chat = _FakeChat([_resp('{"category_id": 1}')])
    prov.client = _Obj(chat=_Obj(completions=chat))
    res = prov.complete_json("jd_classify", "sys", "user", {})
    assert res.data["category_id"] == 1 and chat.calls[0]["response_format"] == {"type": "json_object"}
    assert "json" in chat.calls[0]["messages"][0]["content"].lower()


def test_zhipu_searcher_parses_results(monkeypatch):
    from pathfinder import search
    monkeypatch.setattr(search, "_post_json", lambda url, payload, headers, timeout=30: {
        "search_result": [{"title": "t", "link": "https://example.com/r", "content": "c", "publish_date": "2026-08-01"}]})
    s = search.ZhipuSearcher("k", "search_std")
    out = s.search("测试", n=5)
    assert out[0].url == "https://example.com/r" and out[0].date == "2026-08-01"
    monkeypatch.setenv("PF_SEARCH_PROVIDER", "zhipu"); monkeypatch.setenv("ZHIPU_API_KEY", "k")
    assert search.get_searcher().name == "zhipu"
    monkeypatch.setenv("PF_SEARCH_PROVIDER", "native")
    assert search.use_native_search()


def test_research_uses_native_search_when_provider_supports_it(env, monkeypatch):
    conn, router, searcher, settings, tmp = env
    from pathfinder.db import insert
    from pathfinder.stages import research
    cid = insert(conn, "companies", {"name": "联网公司", "tier": 3, "status": "pilot"})
    insert(conn, "teams", {"company_id": cid, "name": "某团队", "confidence": 0.3})
    monkeypatch.setenv("PF_SEARCH_PROVIDER", "native")
    seen = {}

    def fake_call(task, system, user, *, context=None, web_search=False, retries=1):
        seen["web_search"] = web_search
        from pathfinder.llm.mock import mock_result
        router.last_citations = ["https://example.com/src"]
        return mock_result(task, context or {})

    monkeypatch.setattr(router, "supports_search", lambda task: True)
    monkeypatch.setattr(router, "is_mock", lambda task: False)
    monkeypatch.setattr(router, "call", fake_call)
    msg = research.research_company(conn, router, searcher, settings, {"id": cid, "name": "联网公司", "au_footprint": 0})
    assert seen["web_search"] is True and "信号" in msg
    from pathfinder.db import one, unj
    team = one(conn, "SELECT research FROM teams WHERE company_id = ? AND research IS NOT NULL", (cid,))
    assert unj(team["research"])["sources"] == ["https://example.com/src"]


def test_doctor_reports_without_network(env, monkeypatch):
    """没有 key 时 doctor 只报告缺 key；有 key 但网络不通时报告失败而不是崩溃。"""
    conn, router, searcher, settings, tmp = env
    from pathfinder import doctor
    for k in ("MOONSHOT_API_KEY", "ZHIPU_API_KEY", "DEEPSEEK_API_KEY", "DASHSCOPE_API_KEY", "ANTHROPIC_API_KEY"):
        monkeypatch.delenv(k, raising=False)
    rows_, routing = doctor.run(settings, router)
    assert rows_ and all(r["key"].startswith("✗") for r in rows_)
    assert len(routing) == 8
    monkeypatch.setenv("DEEPSEEK_API_KEY", "bad")
    monkeypatch.setattr(doctor, "list_models", lambda cfg: "无法列出（测试）")
    from pathfinder.llm import providers as prov

    class _Boom:
        supports_search = False
        def complete_json(self, *a, **k):
            raise prov.ProviderError("network down")

    monkeypatch.setattr(doctor, "build_provider", lambda name, cfg: _Boom())
    rows_, _ = doctor.run(settings, router, only="deepseek")
    assert rows_[0]["key"] == "✓" and rows_[0]["json"].startswith("✗")
