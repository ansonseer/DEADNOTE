"""离线演示：虚构公司 + 虚构人物 + mock 模型，把整条管道跑一遍，生成作战卡和日报。

所有示例数据都带『（示例）』和 example.com，和任何真实公司/人物无关。
"""
from __future__ import annotations

import json

from .config import ROOT
from .db import insert, j, one, upsert_company, upsert_team
from .stages import brief, cards, discover, outreach, people, rank, research

FIXTURES = ROOT / "examples" / "demo"


def load_fixtures(conn) -> dict:
    companies = json.loads((FIXTURES / "companies.json").read_text(encoding="utf-8"))
    jobs = json.loads((FIXTURES / "jobs.json").read_text(encoding="utf-8"))
    persons = json.loads((FIXTURES / "people.json").read_text(encoding="utf-8"))
    ids: dict[str, int] = {}
    team_ids: dict[tuple[str, str], int] = {}
    for c in companies:
        cid = upsert_company(conn, c["name"], aliases=j(c.get("aliases", [])), tier=c["tier"], hq=c["hq"],
                             au_footprint=1 if c.get("au_footprint") else 0, why=c.get("why"), careers_url=c.get("careers_url"),
                             status="pilot", screen_score=3.0)
        ids[c["name"]] = cid
        for t in c.get("teams", []):
            team_ids[(c["name"], t["name"])] = upsert_team(conn, cid, t["name"], bu=t.get("bu"), direction=t.get("direction", "unknown"),
                                                            description=t.get("description"), confidence=float(t.get("confidence", 0.3)))
    n_jobs = 0
    for jb in jobs:
        discover.add_job(conn, ids[jb["company"]], jb["title"], url=jb.get("url"), city=jb.get("city"), jd_text=jb.get("jd_text"),
                         source="demo", team_id=team_ids.get((jb["company"], jb.get("team"))), verified=int(jb.get("verified", 0)))
        n_jobs += 1
    n_people = 0
    for p in persons:
        people.add_person(conn, ids[p["company"]], p["name"], title=p.get("title"), team_id=team_ids.get((p["company"], p.get("team"))),
                          channels=p.get("channels"), evidence=p.get("evidence"), tags=p.get("tags"))
        n_people += 1
    return {"companies": len(companies), "jobs": n_jobs, "people": n_people}


def run_demo(conn, router, searcher, settings) -> list[str]:
    out = []
    counts = load_fixtures(conn)
    out.append(f"[demo] 载入示例数据：{counts}")
    out += discover.classify(conn, router, settings)
    out += research.run(conn, router, searcher, settings)
    out += people.assess(conn, router, settings)
    ranked = rank.rank(conn, router, settings)
    out.append(f"[demo] 评分完成：{len(ranked)} 个机会，最高 {ranked[0]['score'] if ranked else '-'}")
    if ranked:
        r = outreach.draft(conn, router, settings, ranked[0]["id"])
        out.append(f"[demo] 已为机会 #{ranked[0]['id']} 生成触达文案（渠道 {r.get('channel')}）")
    paths = cards.render_all(conn, router, settings, top_n=10)
    out.append(f"[demo] 作战卡 {len(paths)} 张：" + "、".join(p.name for p in paths))
    text = brief.build(conn, settings, router)
    out.append("[demo] 日报已生成。\n\n" + text)
    if paths:
        out.append("\n---- 第一张作战卡 ----\n" + paths[0].read_text(encoding="utf-8"))
    return out
