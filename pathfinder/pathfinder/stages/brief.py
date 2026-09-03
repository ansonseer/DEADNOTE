"""阶段 11：作战日报。你每天真正要看的东西：今天做什么、为什么、给谁。"""
from __future__ import annotations

from datetime import date

from ..config import data_dir
from ..crm import PATH_LADDER, account_warnings, due_tasks, metrics, stale_contacts, upcoming_tasks
from ..db import rows
from ..render import bullets, fill, load_template, table, write
from .rank import top


def build(conn, settings, router=None) -> str:
    today = date.today().isoformat()
    tops = top(conn, 10)
    due = due_tasks(conn)
    m = metrics(conn)

    actions = [f"[{t.get('tier') or '-'}] {t.get('company') or ''} · {t.get('person_name') or ''}：{t['action']}（到期 {t.get('due_at') or '无'}）  `pf crm done {t['id']}`" for t in due]
    if not actions:
        actions = [f"[{o.get('tier')}] {o['company']} / {o.get('team') or ''}：{o.get('next_action')}  （机会 #{o['id']}）" for o in tops[:5]]
    up = upcoming_tasks(conn)
    if up:
        actions.append("之后：" + "；".join(f"{t.get('due_at', '')[:10]} {t.get('company') or ''} {t['action']}" for t in up[:5]))

    top_rows = [[i, o.get("tier"), f"{o['company']} / {o.get('team') or ''}", o.get("job_title") or "（团队）", o.get("fit_score"),
                 o.get("stage"), (o.get("person_name") or "未找到人") + (f" L{o.get('path_level')}" if o.get("person_name") else ""), f"#{o['id']}"]
                for i, o in enumerate(tops, 1)]

    stale = stale_contacts(conn, settings)
    account = account_warnings(conn, settings)
    assets = rows(conn, "SELECT * FROM assets ORDER BY id DESC LIMIT 5")
    content = [f"[{a['status']}] {a['kind']}：{a['title']} {a.get('url') or ''}" for a in assets]
    if not any(a["status"] != "idea" for a in assets):
        target = tops[0] if tops else None
        content.append("本周还没有新的公开作品。建议：" + (f"针对 {target['company']} / {target.get('team') or ''} 做一个小 PoC 或拆解，先发一篇，再拿它去敲门。"
                                             if target else "从 Top 机会里挑一个团队做小 PoC。"))
    funnel = [f"机会阶段分布：{m['by_stage']}", f"人物关系分布：{m['people']}",
              f"已联系 {m['contacted']} 人，回复 {m['replied']} 人，回复率 {m['reply_rate'] if m['reply_rate'] is not None else '—'}"]
    c = m["counts"]
    system = [f"公司 {c['companies']}（pilot {c['pilot_companies']}）｜团队 {c['teams']}（已验证 {c['verified_teams']}）｜岗位 {c['jobs']}（相关 {c['relevant_jobs']}）"
              f"｜人物 {c['people']}｜机会 {c['opportunities']}｜触点 {c['touchpoints']}",
              f"模型调用 {m['llm_calls']} 次，tokens {m['tokens_in']} 入 / {m['tokens_out']} 出"]
    if router is not None:
        system.append("模型分工：" + "；".join(f"{t}→{p}({mdl})" for t, p, mdl in router.describe()))
    a_count = sum(1 for o in tops if (o.get("tier") or "").startswith("A"))
    first = due[0] if due else None
    headline = (f"A 类机会 {a_count} 个；待办 {len(due)} 项。今天最重要的一件事：" +
                (f"{first.get('company') or ''} · {first['action']}" if first else (f"推进 #{tops[0]['id']} {tops[0]['company']}：{tops[0].get('next_action')}" if tops else "先跑 pf scan / pf demo")))
    text = fill(load_template("daily_brief.md"), {
        "date": today, "headline": headline, "actions": bullets(actions),
        "top_table": table(["#", "优先级", "公司 / 团队", "岗位", "Fit", "阶段", "联系人", "ID"], top_rows),
        "stale": bullets([f"{p['name']}（{p.get('title') or ''}）已 {p['hours_since']} 小时无回复且无排期 → `pf crm touch {p['id']} --kind followup`" for p in stale]),
        "account": bullets([f"{p['name']}：索取 {p['asks']} 次 / 给予 {p.get('value_given') or 0} 次 → 先给一次价值再开口" for p in account]),
        "content": bullets(content), "funnel": bullets(funnel), "system": bullets(system),
    })
    write(data_dir() / "briefs" / f"{today}.md", text)
    return text
