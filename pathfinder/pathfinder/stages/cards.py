"""阶段 10：作战卡。把一个机会的所有研究压成一页能直接行动的卡片。"""
from __future__ import annotations

from datetime import datetime, timedelta
from pathlib import Path

from ..config import data_dir
from ..crm import PATH_LADDER
from ..db import get, j, now, rows, unj, update
from ..llm import prompts
from ..render import bullets, fill, load_template, table, write
from .rank import top


def narrative_for(conn, router, settings, o: dict, force: bool = False) -> dict:
    cached = unj(o.get("narrative"))
    if cached and not force:
        return cached
    company = get(conn, "companies", o["company_id"])
    team = get(conn, "teams", o["team_id"]) if o.get("team_id") else {}
    team_ctx = {**(team or {}), **(unj((team or {}).get("research"), {}) or {})}
    job = get(conn, "jobs", o["job_id"]) if o.get("job_id") else None
    job_ctx = {**job, "features": unj(job.get("features"), {})} if job else None
    person = get(conn, "people", o["person_id"]) if o.get("person_id") else None
    breakdown = unj(o.get("breakdown"), {}) or {}
    fit = breakdown.get("fit")
    slim = {k: v for k, v in breakdown.items() if k not in ("fit", "features")}
    system, user = prompts.card_write(settings.profile, company, team_ctx, job_ctx, person, fit, slim)
    result = router.call("card_write", system, user, context={"company_name": company["name"], "team_name": team_ctx.get("name")})
    update(conn, "opportunities", o["id"], {"narrative": j(result)})
    return result


def _fmt_date(dt: datetime) -> str:
    return dt.strftime("%m-%d")


def render_card(conn, settings, o: dict, n: dict, rank_no: int) -> str:
    company = get(conn, "companies", o["company_id"])
    research = unj(o.get("research"), {}) or {}
    features = unj(o.get("job_features"), {}) or {}
    breakdown = unj(o.get("breakdown"), {}) or {}
    fit = breakdown.get("fit") or unj(o.get("job_fit"), {}) or {}
    outreach = unj(o.get("outreach"), {}) or {}
    assess = unj(o.get("person_assess"), {}) or {}
    channels = unj(o.get("person_channels"), {}) or {}
    tags = unj(o.get("person_tags"), []) or []
    cad = settings.scoring.get("cadence", {})
    t0 = datetime.now()
    signals = rows(conn, "SELECT * FROM signals WHERE team_id = ? ORDER BY strength DESC, date DESC", (o.get("team_id") or -1,))
    people = rows(conn, "SELECT * FROM people WHERE company_id = ? ORDER BY path_level DESC, id", (o["company_id"],))
    path_level = int(o.get("path_level") or 0)
    path_potential = int(assess.get("path_level_potential") or path_level)
    long_term = []
    if company.get("au_footprint"):
        long_term.append("中澳双足迹：这家公司的中国经历可以在 2027 年转化为澳洲团队 / 澳洲客户的敲门砖。")
    if tags:
        long_term.append(f"联系人长期标签：{'、'.join(tags)}")
    long_term.append("作品敲门：为这个团队做一个小 PoC / 拆解，同一件作品同时是私信素材、公众号内容和作品集。")
    bd_rows = [[k, f"{v['points']}/{v['max']}", v["note"]] for k, v in breakdown.items() if isinstance(v, dict) and "points" in v]
    evidence = [f"{s['title']} — {s['url']}" for s in signals if s.get("url")]
    if o.get("job_url"):
        evidence.append(f"岗位链接 — {o['job_url']}")
    for u in research.get("sources", []) or []:
        evidence.append(f"研究来源 — {u}")
    for p in people:
        for e in unj(p.get("evidence"), []) or []:
            if e.get("url"):
                evidence.append(f"{p['name']}：{e.get('title')} — {e['url']}")
    mapping = {
        "priority": f"Priority {o.get('tier')} · #{rank_no}",
        "company": company["name"], "team": o.get("team") or "（团队待定）",
        "fit_score": o.get("fit_score"), "stage": o.get("stage"), "generated_at": now(),
        "company_line": f"{company['name']}（Tier {company.get('tier')}，{company.get('hq') or ''}）"
                        f"{'｜中澳双足迹' if company.get('au_footprint') else ''}\n{company.get('why') or ''}",
        "team_line": f"{o.get('team') or '未知'}（{o.get('bu') or 'BU 未知'}）｜方向：{o.get('direction') or 'unknown'}｜"
                     f"{'已验证' if o.get('team_verified') else '假设，待验证'}\n{research.get('what_they_do_now') or ''}",
        "job_line": (f"{o['job_title']}（{o.get('job_city') or '城市未知'}，{features.get('years_required') or '年限未知'}）"
                     f"\n{features.get('summary') or ''}\n{o.get('job_url') or ''}"
                     if o.get("job_title") else "暂无公开岗位：先通过对话确认 headcount（很多解决方案岗不公开挂出）"),
        "why_fit": n.get("why_fit") or fit.get("why_fit_summary") or "",
        "matched_points": bullets([f"{m.get('jd_need')} ← {m.get('your_evidence')}" for m in fit.get("matched_points", [])])
                          + ("\n\n差距：" + "；".join(fit.get("gaps", [])) if fit.get("gaps") else ""),
        "team_now": n.get("team_now") or research.get("what_they_do_now") or "",
        "signals": bullets([f"[{s.get('kind')}] {s.get('title')}（{s.get('date') or '日期未知'}）{s.get('url') or ''}" for s in signals]),
        "person_line": (f"**{o['person_name']}**（{o.get('person_title') or ''}）｜角色 {o.get('role_type')}｜渠道 {', '.join(channels) or '未知'}"
                        if o.get("person_name") else "尚未找到人：见 data/packets/people_checklist__*.md"),
        "people_table": table(["姓名", "职位", "角色", "路径", "关系"],
                              [[p["name"], p.get("title") or "", p.get("role_type"), f"L{p.get('path_level')}", p.get("relationship")] for p in people]),
        "why_this_person": (n.get("why_this_person") or o.get("why_contact") or "") + (f"\n\nHook：{o['person_hook']}" if o.get("person_hook") else ""),
        "channel": outreach.get("channel") or assess.get("suggested_channel") or "待定",
        "first_message": outreach.get("first_message") or f"（尚未生成：pf outreach {o['id']}）",
        "outreach_notes": outreach.get("notes") or "先在对方最近一篇内容下留一条有内容的评论，再私信。",
        "referral_assessment": n.get("referral_assessment") or "",
        "path_level": path_level, "path_level_name": PATH_LADDER.get(path_level, ""),
        "path_potential": path_potential, "path_potential_name": PATH_LADDER.get(path_potential, ""),
        "next_action": n.get("next_action") or "", "today_action": o.get("next_action") or "",
        "followup_1_date": _fmt_date(t0 + timedelta(hours=cad.get("followup_1_hours", 60))),
        "followup_2_date": _fmt_date(t0 + timedelta(hours=cad.get("followup_1_hours", 60) + cad.get("followup_2_hours", 168))),
        "risks": n.get("risks") or "",
        "long_term_note": bullets(long_term),
        "breakdown_table": table(["维度", "得分", "说明"], bd_rows) + f"\n\n总分：{breakdown.get('total', o.get('fit_score'))}",
        "evidence_links": bullets(evidence, empty="暂无带 URL 的证据 —— 这本身就是一个风险"),
    }
    return fill(load_template("battle_card.md"), mapping)


def render_all(conn, router, settings, top_n: int = 10, force: bool = False) -> list[Path]:
    out_dir = data_dir() / "cards"
    paths, index_rows = [], []
    for i, o in enumerate(top(conn, top_n), 1):
        n = narrative_for(conn, router, settings, o, force=force)
        md = render_card(conn, settings, o, n, i)
        safe = "".join(ch for ch in o["company"] if ch.isalnum() or "一" <= ch <= "鿿")[:20]
        p = write(out_dir / f"{i:02d}_{safe}.md", md)
        update(conn, "opportunities", o["id"], {"card_path": str(p)})
        paths.append(p)
        index_rows.append([i, o.get("tier"), o["company"], o.get("team") or "", o.get("job_title") or "（团队）", o.get("fit_score"), o.get("stage"), p.name])
    write(out_dir / "index.md", "# Top 机会索引\n\n" + table(["#", "优先级", "公司", "团队", "岗位", "Fit", "阶段", "文件"], index_rows))
    return paths
