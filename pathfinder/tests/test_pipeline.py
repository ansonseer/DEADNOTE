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
