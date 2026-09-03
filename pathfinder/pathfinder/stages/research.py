"""阶段 4-5：团队研究 + 业务背景研究。

原则：没有证据来源的研究不做。
- 有搜索 API：先搜证据，再让 Claude 综合；
- PF_SEARCH_PROVIDER=claude_web：让 Claude 自己边搜边写（服务端 web_search 工具）；
- 都没有且不是 mock：导出 packet，交给带搜索的人/Agent；
每条 signal 必须带 URL，团队 verified 只在证据充分时置 1。
"""
from __future__ import annotations

from ..db import find_company, insert, j, one, pilot_companies, rows, unj, update, upsert_team
from ..llm import prompts
from ..packets import export_packet
from ..search import use_claude_web

RESEARCH_QUERIES = [
    "{company} 大模型 解决方案 客户 案例",
    "{company} Agent 企业 落地 2026",
    "{company} 解决方案 团队 分享 大会 演讲",
    "{company} 招聘 解决方案 工程师 AI",
]


def gather_evidence(conn, searcher, company: dict, teams: list[dict], max_queries: int = 5) -> list[dict]:
    if not searcher.enabled:
        return []
    name = company["name"].split(" / ")[0]
    queries = [q.format(company=name) for q in RESEARCH_QUERIES] + [f"{name} {t['name']}" for t in teams[:2]]
    evidence = []
    for q in queries[:max_queries]:
        results = searcher.search(q, n=6)
        insert(conn, "queries", {"stage": "research", "company_id": company["id"], "query": q, "provider": searcher.name, "n_results": len(results)})
        evidence += [r.to_dict() for r in results]
    seen, dedup = set(), []
    for e in evidence:
        if e["url"] not in seen:
            seen.add(e["url"])
            dedup.append(e)
    return dedup[:25]


def research_company(conn, router, searcher, settings, company: dict, packet: bool = False, force: bool = False) -> str:
    teams = rows(conn, "SELECT * FROM teams WHERE company_id = ? ORDER BY verified DESC, confidence DESC LIMIT 4", (company["id"],))
    if not teams:
        return f"{company['name']}：还没有团队假设，先跑 pf scan"
    if any(t.get("research") for t in teams) and not force:
        return f"{company['name']}：已有研究结果（--force 可重做）"
    web = use_claude_web() and router.provider_name_for("team_research") == "anthropic"
    evidence = [] if web else gather_evidence(conn, searcher, company, teams)
    system, user = prompts.team_research(company, teams, evidence, settings.taxonomy, web_search=web)
    context = {"company_id": company["id"], "company_name": company["name"],
               "team_name": teams[0]["name"], "direction": teams[0].get("direction") or "unknown",
               "au_footprint": bool(company.get("au_footprint"))}
    no_evidence = not evidence and not web and not router.is_mock("team_research")
    if packet or no_evidence:
        p = export_packet("team_research", context, system, user, company["name"])
        reason = "（未配置搜索，为避免模型凭空编造，改为导出 packet）" if no_evidence and not packet else ""
        return f"{company['name']}：已导出 packet {p} {reason}"
    result = router.call("team_research", system, user, context=context, web_search=web)
    return ingest_research(conn, settings, context, result)


def ingest_research(conn, settings, context: dict, result: dict) -> str:
    cid = int(context["company_id"])
    signals = [s for s in result.get("signals", []) if s.get("url")]
    real_urls = [s for s in signals if "example.com" not in s["url"]]
    verified = 1 if (real_urls and float(result.get("confidence", 0)) >= 0.6) else 0
    team_id = upsert_team(conn, cid, result["team_name"], direction=result.get("direction", "unknown"),
                          description=result.get("what_they_do_now"), confidence=float(result.get("confidence", 0.3)),
                          verified=verified, research=j(result))
    conn.execute("DELETE FROM signals WHERE team_id = ?", (team_id,))
    for s in signals:
        insert(conn, "signals", {"company_id": cid, "team_id": team_id, "kind": s.get("kind"), "title": s.get("title"),
                                 "url": s.get("url"), "date": s.get("date") or None, "summary": s.get("summary"),
                                 "strength": int(s.get("strength", 1))})
    conn.commit()
    for opp in rows(conn, "SELECT id, stage FROM opportunities WHERE team_id = ? AND stage = 'identified'", (team_id,)):
        update(conn, "opportunities", opp["id"], {"stage": "researched"})
    return f"{context.get('company_name')} / {result['team_name']}：{len(signals)} 条信号，置信度 {result.get('confidence')}，{'已验证' if verified else '未验证'}"


def run(conn, router, searcher, settings, company: str | None = None, packet: bool = False, force: bool = False) -> list[str]:
    targets = [find_company(conn, company)] if company else pilot_companies(conn)
    return [research_company(conn, router, searcher, settings, c, packet=packet, force=force) for c in targets if c]
