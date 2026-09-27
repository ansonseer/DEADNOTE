"""阶段 6-7：找人 + 判断人脉价值。

找人这一步刻意留给人（或你亲手驱动的 Agent）：脉脉 / LinkedIn / 会议议程 / 公众号署名 / GitHub。
系统做三件事：1) 告诉你该找什么角色、去哪找（packet 清单）；2) 录入后用模型判断谁最值得联系、为什么、怎么开口；
3) 给每个人打长期标签（不只是 hiring_now）。
"""
from __future__ import annotations

from ..config import data_dir
from ..db import find_company, insert, j, one, pilot_companies, rows, unj, update
from ..llm import prompts
from ..packets import export_packet
from ..render import bullets, write

ROLE_PRIORITY = ["hiring_manager", "team_lead", "senior_ic", "exec", "employee", "recruiter"]


def add_person(conn, company_id: int, name: str, title: str | None = None, team_id: int | None = None,
               channels: dict | None = None, evidence: list | None = None, role_type: str | None = None,
               notes: str | None = None, tags: list | None = None) -> int:
    existing = one(conn, "SELECT * FROM people WHERE company_id = ? AND name = ?", (company_id, name))
    channels = {k: v for k, v in (channels or {}).items() if v}
    if existing:
        merged_channels = {**(unj(existing.get("channels"), {}) or {}), **channels}
        merged_evidence = (unj(existing.get("evidence"), []) or []) + (evidence or [])
        fields = {"channels": j(merged_channels), "evidence": j(merged_evidence)}
        for k, v in dict(title=title, team_id=team_id, role_type=role_type, notes=notes).items():
            if v:
                fields[k] = v
        if tags:
            fields["tags"] = j(sorted(set((unj(existing.get("tags"), []) or []) + tags)))
        if merged_channels and (existing.get("path_level") or 0) < 1:
            fields["path_level"] = 1
        update(conn, "people", existing["id"], fields)
        return existing["id"]
    return insert(conn, "people", {"company_id": company_id, "name": name, "title": title, "team_id": team_id,
                                   "channels": j(channels), "evidence": j(evidence or []), "role_type": role_type or "employee",
                                   "notes": notes, "tags": j(tags or []), "path_level": 1 if channels else 0,
                                   "relationship": "cold"})


def export_people_packet(conn, settings, company: dict, team: dict | None) -> str:
    research = unj((team or {}).get("research"), {}) or {}
    where = settings.sources.get("people", {}).get("where", [])
    lines = [f"# 找人清单：{company['name']} / {(team or {}).get('name') or '（团队待定）'}", "",
             "## 要找的角色（按优先级）",
             bullets(["Hiring Manager / 团队负责人（拥有 headcount）", "Team Lead / 解决方案负责人", "Senior Solution Engineer / 高级解决方案架构师",
                      "行业解决方案负责人", "团队里最近公开分享过的人（回复率最高）", "最后才是 HR / 招聘者"]),
             "", "## 去哪找", bullets([f"{w['channel']}：{w['how']}" for w in where]),
             "", "## 这个团队最近在做什么（用来判断谁是对的人）", (research.get("what_they_do_now") or "（先跑 pf research）"),
             "", "## 可聊的话题", bullets(research.get("conversation_hooks", [])),
             "", "## 录入命令",
             "```", f"pf people add --company \"{company['name']}\" --name 姓名 --title 职位 --team \"{(team or {}).get('name') or ''}\" \\",
             "  --linkedin URL --maimai URL --evidence \"分享标题|URL|一句话摘要\"", "```",
             "", "> 只记录公开的职业信息；不要抓取、不要存手机号等敏感信息；所有消息由你本人发送。"]
    p = write(data_dir() / "packets" / f"people_checklist__{company['name']}.md", "\n".join(lines))
    return str(p)


def best_team(conn, company_id: int) -> dict | None:
    return one(conn, "SELECT * FROM teams WHERE company_id = ? ORDER BY verified DESC, confidence DESC LIMIT 1", (company_id,))


def assess(conn, router, settings, company_ref: str | None = None, packet: bool = False, force: bool = False) -> list[str]:
    targets = [find_company(conn, company_ref)] if company_ref else pilot_companies(conn)
    out = []
    for c in targets:
        if not c:
            continue
        people = rows(conn, "SELECT * FROM people WHERE company_id = ?" + ("" if force else " AND assess IS NULL"), (c["id"],))
        team = best_team(conn, c["id"])
        if not people:
            if not rows(conn, "SELECT id FROM people WHERE company_id = ?", (c["id"],)):
                out.append(f"{c['name']}：还没有录入人物 → 找人清单 {export_people_packet(conn, settings, c, team)}")
            continue
        team_ctx = {**(team or {}), **(unj((team or {}).get("research"), {}) or {})}
        public = [{"name": p["name"], "title": p.get("title"), "channels": list((unj(p.get("channels"), {}) or {}).keys()),
                   "evidence": unj(p.get("evidence"), []), "notes": p.get("notes")} for p in people]
        system, user = prompts.people_assess(c, team_ctx, public, settings.profile)
        context = {"company_id": c["id"], "company_name": c["name"], "team_id": (team or {}).get("id"),
                   "team_name": (team or {}).get("name"), "people": [{"name": p["name"], "title": p.get("title")} for p in people],
                   "au_footprint": bool(c.get("au_footprint"))}
        if packet:
            out.append(f"已导出 packet：{export_packet('people_assess', context, system, user, c['name'])}")
            continue
        result = router.call("people_assess", system, user, context=context)
        out.append(ingest_assess(conn, settings, context, result))
    return out


def ingest_assess(conn, settings, context: dict, result: dict) -> str:
    cid = int(context["company_id"])
    n = 0
    for p in result.get("people", []):
        row = one(conn, "SELECT * FROM people WHERE company_id = ? AND name = ?", (cid, p["name"]))
        if not row:
            continue
        tags = sorted(set((unj(row.get("tags"), []) or []) + p.get("long_term_tags", [])))
        fields = {"role_type": p.get("role_type") or row.get("role_type"), "why_contact": p.get("why_contact"),
                  "hook": p.get("hook"), "tags": j(tags), "assess": j(p)}
        if not row.get("team_id") and context.get("team_id"):
            fields["team_id"] = context["team_id"]
        update(conn, "people", row["id"], fields)
        n += 1
    for opp in rows(conn, "SELECT id, stage FROM opportunities WHERE company_id = ? AND stage IN ('identified','researched')", (cid,)):
        update(conn, "opportunities", opp["id"], {"stage": "people_found"})
    return f"{context.get('company_name')}：评估了 {n} 人，建议先联系 {result.get('recommended_first')}（{result.get('rationale')}）"


def run(conn, router, settings, company: str | None = None, packet: bool = False) -> list[str]:
    return assess(conn, router, settings, company, packet=packet)
