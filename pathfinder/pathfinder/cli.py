"""pf 命令行：整条流水线 + CRM 的入口。

典型一天：
  pf brief                 看今天做什么
  pf crm touch 3 --kind first_msg --channel maimai    发了私信就记一笔
  pf outreach 7            给某个机会生成文案
  pf cards                 重新生成 Top 10 作战卡
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

from . import crm
from .config import data_dir, load_env, settings
from .db import STAGES, connect, find_company, get, rows, unj
from .llm import Router
from .render import table
from .search import get_searcher


def _ctx(args):
    load_env()
    if getattr(args, "data_dir", None):
        os.environ["PF_DATA_DIR"] = args.data_dir
    conn = connect()
    router = Router(settings, conn=conn, force_mock=True if getattr(args, "mock", False) else None, verbose=getattr(args, "verbose", False))
    return conn, router, get_searcher(), settings


def _print(lines):
    for line in (lines if isinstance(lines, list) else [lines]):
        print(line)


# ---- 命令 ----

def cmd_init(args):
    from .stages import scan
    conn, router, searcher, st = _ctx(args)
    n = scan.load_seeds(conn, st)
    pilot = scan.screen(conn, st)
    print(f"数据库：{data_dir() / 'pathfinder.db'}")
    print(f"载入种子公司（新增 {n}），pilot {len(pilot)} 家：" + "、".join(c["name"] for c in pilot))
    cmd_status(args, conn=conn, router=router, searcher=searcher)


def cmd_status(args, conn=None, router=None, searcher=None):
    if conn is None:
        conn, router, searcher, _ = _ctx(args)
    m = crm.metrics(conn)
    c = m["counts"]
    print(f"公司 {c['companies']}（pilot {c['pilot_companies']}）｜团队 {c['teams']}（已验证 {c['verified_teams']}）｜岗位 {c['jobs']}（相关 {c['relevant_jobs']}）"
          f"｜人物 {c['people']}｜机会 {c['opportunities']}｜触点 {c['touchpoints']}｜作品 {c['assets']}")
    from .search import use_native_search
    native = use_native_search() and router.supports_search("team_research")
    mode = "native（研究模型自己联网）" if native else (searcher.name if searcher.enabled else "none（未配置 → 研究阶段会导出 packet）")
    print(f"研究证据来源：{mode}")
    print("模型分工（实际生效）：")
    print(table(["任务", "provider", "model"], [list(r) for r in router.describe()]))
    print(f"模型调用 {m['llm_calls']} 次，tokens {m['tokens_in']} 入 / {m['tokens_out']} 出")


def cmd_doctor(args):
    from . import doctor
    from .search import use_native_search
    conn, router, searcher, st = _ctx(args)
    rows_, routing = doctor.run(st, router, only=args.provider, do_search=args.search)
    print("Provider 体检" + ("（含联网测试）" if args.search else "（加 --search 测联网）"))
    print(table(["provider", "配置的模型", "key", "模型是否存在", "JSON 调用", "联网搜索"],
                [[r["provider"], r["model"], r["key"], r["models"], r["json"], r["search"]] for r in rows_]))
    print("\n任务 → 实际生效的模型")
    print(table(["任务", "provider", "model"], [list(r) for r in routing]))
    native = use_native_search() and router.supports_search("team_research")
    print(f"\n研究证据来源：{'native（研究模型自己联网）' if native else (searcher.name if searcher.enabled else 'none → 研究阶段会导出 packet')}")
    if any(r["key"] == "✓" for r in rows_) and not any("✓" in r["json"] for r in rows_):
        print("\n提示：有 key 但没有一个 JSON 调用成功，多半是网络（代理 / 防火墙）或 key 无效。")


def cmd_demo(args):
    """demo 永远写到 <data_dir>/demo/，不会碰你的真实数据。"""
    from .demo import run_demo
    base = Path(args.data_dir) if args.data_dir else data_dir()
    args.data_dir = str(base / "demo")
    db = Path(args.data_dir) / "pathfinder.db"
    if args.reset and db.exists():
        db.unlink()
    args.mock = True
    conn, router, searcher, st = _ctx(args)
    _print(run_demo(conn, router, searcher, st))
    print(f"\n（demo 数据在 {args.data_dir}，与真实数据隔离）")


def cmd_scan(args):
    from .stages import scan
    conn, router, _, st = _ctx(args)
    _print(scan.run(conn, router, st, company=args.company, packet=args.packet))


def cmd_discover(args):
    from .stages import discover
    conn, router, searcher, st = _ctx(args)
    _print(discover.run(conn, router, searcher, st, company=args.company, packet=args.packet))


def cmd_jobs(args):
    from .stages import discover
    conn, router, _, st = _ctx(args)
    if args.jobs_cmd == "add":
        c = find_company(conn, args.company)
        if not c:
            sys.exit(f"找不到公司：{args.company}（先 pf init，或检查名字）")
        jd = Path(args.jd_file).read_text(encoding="utf-8") if args.jd_file else None
        team_id = None
        if args.team:
            t = rows(conn, "SELECT id FROM teams WHERE company_id = ? AND name LIKE ?", (c["id"], f"%{args.team}%"))
            team_id = t[0]["id"] if t else None
        jid = discover.add_job(conn, c["id"], args.title, url=args.url, city=args.city, jd_text=jd, source="manual", team_id=team_id, verified=1 if args.url else 0)
        print(f"岗位 #{jid} 已录入；运行 pf discover --company \"{c['name']}\" 进行分类，或 pf rank")
    else:
        sql = "SELECT j.id, c.name, j.title, j.category_id, j.city, j.status, j.verified FROM jobs j JOIN companies c ON c.id=j.company_id"
        params = ()
        if args.company:
            c = find_company(conn, args.company)
            sql += " WHERE j.company_id = ?"
            params = (c["id"],) if c else (-1,)
        print(table(["ID", "公司", "岗位", "类别", "城市", "状态", "已验证"], [list(r.values()) for r in rows(conn, sql + " ORDER BY j.id", params)]))


def cmd_research(args):
    from .stages import research
    conn, router, searcher, st = _ctx(args)
    _print(research.run(conn, router, searcher, st, company=args.company, packet=args.packet, force=args.force))


def cmd_people(args):
    from .stages import people
    conn, router, _, st = _ctx(args)
    if args.people_cmd == "add":
        c = find_company(conn, args.company)
        if not c:
            sys.exit(f"找不到公司：{args.company}")
        team_id = None
        if args.team:
            t = rows(conn, "SELECT id FROM teams WHERE company_id = ? AND name LIKE ?", (c["id"], f"%{args.team}%"))
            team_id = t[0]["id"] if t else None
        channels = {k: getattr(args, k) for k in ("linkedin", "maimai", "wechat", "email", "zhihu", "jike", "github") if getattr(args, k)}
        evidence = []
        for e in args.evidence or []:
            parts = [p.strip() for p in e.split("|")]
            evidence.append({"title": parts[0], "url": parts[1] if len(parts) > 1 else "", "summary": parts[2] if len(parts) > 2 else ""})
        pid = people.add_person(conn, c["id"], args.name, title=args.title, team_id=team_id, channels=channels, evidence=evidence,
                                role_type=args.role, notes=args.notes, tags=args.tags)
        print(f"人物 #{pid} 已录入；运行 pf people assess --company \"{c['name']}\" 评估，然后 pf rank")
    elif args.people_cmd == "assess":
        _print(people.assess(conn, router, st, args.company, packet=args.packet, force=args.force))
    elif args.people_cmd == "packet":
        c = find_company(conn, args.company)
        if not c:
            sys.exit(f"找不到公司：{args.company}")
        print(people.export_people_packet(conn, st, c, people.best_team(conn, c["id"])))
    else:
        sql = "SELECT p.id, c.name, p.name, p.title, p.role_type, p.path_level, p.relationship, p.tags FROM people p JOIN companies c ON c.id=p.company_id"
        params = ()
        if args.company:
            c = find_company(conn, args.company)
            sql += " WHERE p.company_id = ?"
            params = (c["id"],) if c else (-1,)
        print(table(["ID", "公司", "姓名", "职位", "角色", "路径", "关系", "标签"], [list(r.values()) for r in rows(conn, sql + " ORDER BY p.id", params)]))


def cmd_rank(args):
    from .stages import rank
    conn, router, _, st = _ctx(args)
    res = rank.rank(conn, router, st, args.company, packet=args.packet)
    print(table(["ID", "优先级", "公司", "团队", "岗位", "Fit", "阶段"], [[r["id"], r["tier"], r["company"], r["team"], r["job"] or "（团队）", r["score"], r["stage"]] for r in res]))


def cmd_top(args):
    from .stages.rank import top
    conn, _, _, _ = _ctx(args)
    print(table(["#", "ID", "优先级", "公司 / 团队", "岗位", "Fit", "阶段", "联系人", "下一步"],
                [[i, o["id"], o["tier"], f"{o['company']} / {o.get('team') or ''}", o.get("job_title") or "（团队）", o["fit_score"], o["stage"],
                  o.get("person_name") or "—", o.get("next_action")] for i, o in enumerate(top(conn, args.n), 1)]))


def cmd_show(args):
    conn, _, _, _ = _ctx(args)
    o = get(conn, "opportunities", args.opp_id)
    if not o:
        sys.exit("没有这个机会")
    o = {k: (unj(v) if k in ("breakdown", "narrative", "outreach") else v) for k, v in o.items()}
    print(json.dumps(o, ensure_ascii=False, indent=1))


def cmd_outreach(args):
    from .stages import outreach
    conn, router, _, st = _ctx(args)
    r = outreach.draft(conn, router, st, args.opp_id, channel=args.channel, pattern=args.pattern, person_id=args.person, force=args.force)
    print(f"渠道：{r.get('channel')}｜模式：{r.get('pattern')}\n\n第一条私信：\n{r.get('first_message')}\n\nFollow-up 1：\n{r.get('followup_1')}\n\n"
          f"Follow-up 2：\n{r.get('followup_2')}\n\n转岗位：\n{r.get('referral_transition')}\n\n提醒：{r.get('notes')}\n\n（已写入 {data_dir() / 'outreach'}）")


def cmd_cards(args):
    from .stages import cards
    conn, router, _, st = _ctx(args)
    paths = cards.render_all(conn, router, st, top_n=args.n, force=args.force)
    _print([str(p) for p in paths] or ["没有机会可渲染：先 pf rank"])


def cmd_brief(args):
    from .stages import brief
    conn, router, _, st = _ctx(args)
    print(brief.build(conn, st, router))


def cmd_crm(args):
    conn, _, _, st = _ctx(args)
    if args.crm_cmd == "stage":
        o = crm.set_stage(conn, st, args.opp_id, args.stage, note=args.note)
        print(f"机会 #{o['id']} → {o['stage']}；下一步：{o.get('next_action')}（{o.get('next_action_at') or '无到期'}）")
    elif args.crm_cmd == "touch":
        p = crm.log_touch(conn, st, args.person_id, args.kind, channel=args.channel or "", direction=args.direction,
                          content=args.content or "", outcome=args.outcome or "", opp_id=args.opp)
        print(f"{p['name']}：关系 {p['relationship']}，路径 L{p['path_level']}（{crm.PATH_LADDER[p['path_level']]}）；待办：")
        _print([f"  - {t['action']}（{t.get('due_at')}）" for t in crm.due_tasks(conn, within_hours=24 * 30) if t.get("person_id") == args.person_id])
    elif args.crm_cmd == "due":
        print(table(["任务ID", "优先级", "公司", "人", "动作", "到期"], [[t["id"], t.get("tier"), t.get("company"), t.get("person_name"), t["action"], t.get("due_at")] for t in crm.due_tasks(conn, args.hours)]))
    elif args.crm_cmd == "done":
        crm.complete_task(conn, args.task_id)
        print(f"任务 #{args.task_id} 完成")
    elif args.crm_cmd == "asset":
        aid = crm.add_asset(conn, args.kind, args.title, url=args.url or "", status=args.status, company_ref=args.company, notes=args.notes or "")
        print(f"作品 #{aid} 已记录（{args.status}）")
    elif args.crm_cmd == "stages":
        print(" → ".join(STAGES))


def cmd_packet(args):
    from .packets import ingest
    conn, _, _, st = _ctx(args)
    if args.packet_cmd == "ingest":
        for f in args.files:
            print(ingest(conn, st, Path(f)))
    else:
        d = data_dir() / "packets"
        _print(sorted(str(p) for p in d.glob("*")) if d.exists() else ["（没有 packet）"])


def cmd_run_all(args):
    from .stages import scan, discover, research, people, rank, cards, brief
    conn, router, searcher, st = _ctx(args)
    _print(scan.run(conn, router, st, company=args.company))
    _print(discover.run(conn, router, searcher, st, company=args.company))
    _print(research.run(conn, router, searcher, st, company=args.company))
    _print(people.run(conn, router, st, company=args.company))
    res = rank.rank(conn, router, st, args.company)
    print(f"评分完成：{len(res)} 个机会")
    _print([str(p) for p in cards.render_all(conn, router, st, top_n=10)])
    print(brief.build(conn, st, router))


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="pf", description="中国 AI 求职情报 + 人脉路径 + 内推 + CRM")
    p.add_argument("--data-dir", help="运行时数据目录（默认 ./data）")
    p.add_argument("--mock", action="store_true", help="强制所有模型调用走 mock")
    p.add_argument("--verbose", "-v", action="store_true")
    sub = p.add_subparsers(dest="cmd", required=True)

    sub.add_parser("init", help="建库 + 载入种子公司 + 筛选 pilot").set_defaults(fn=cmd_init)
    sub.add_parser("status", help="系统状态与模型分工").set_defaults(fn=cmd_status)
    dr = sub.add_parser("doctor", help="体检：key / 模型名 / JSON 调用 / 联网搜索"); dr.add_argument("--search", action="store_true", help="同时测试联网搜索"); dr.add_argument("--provider", help="只测某一个 provider"); dr.set_defaults(fn=cmd_doctor)
    d = sub.add_parser("demo", help="用虚构示例数据 + mock 模型跑通整条管道"); d.add_argument("--reset", action="store_true"); d.set_defaults(fn=cmd_demo)

    for name, fn, helptext in (("scan", cmd_scan, "市场扫描：种子 → 筛选 → 团队假设"), ("discover", cmd_discover, "岗位发现：叫法扩展 → 搜索 → 分类"),
                               ("research", cmd_research, "团队研究：证据 → 团队画像 + 信号")):
        s = sub.add_parser(name, help=helptext); s.add_argument("--company"); s.add_argument("--packet", action="store_true", help="不调模型，导出 packet")
        if name == "research":
            s.add_argument("--force", action="store_true")
        s.set_defaults(fn=fn)

    jb = sub.add_parser("jobs", help="岗位录入 / 列表"); jsub = jb.add_subparsers(dest="jobs_cmd", required=True)
    ja = jsub.add_parser("add"); ja.add_argument("--company", required=True); ja.add_argument("--title", required=True); ja.add_argument("--url"); ja.add_argument("--city"); ja.add_argument("--jd-file"); ja.add_argument("--team")
    jl = jsub.add_parser("list"); jl.add_argument("--company"); jb.set_defaults(fn=cmd_jobs)

    pp = sub.add_parser("people", help="人物录入 / 评估 / 找人清单"); psub = pp.add_subparsers(dest="people_cmd", required=True)
    pa = psub.add_parser("add"); pa.add_argument("--company", required=True); pa.add_argument("--name", required=True); pa.add_argument("--title"); pa.add_argument("--team")
    for ch in ("linkedin", "maimai", "wechat", "email", "zhihu", "jike", "github"):
        pa.add_argument(f"--{ch}")
    pa.add_argument("--evidence", action="append", help="'标题|URL|摘要'，可多次"); pa.add_argument("--role", choices=["hiring_manager", "team_lead", "senior_ic", "exec", "employee", "recruiter"]); pa.add_argument("--notes"); pa.add_argument("--tags", nargs="*")
    ps = psub.add_parser("assess"); ps.add_argument("--company"); ps.add_argument("--packet", action="store_true"); ps.add_argument("--force", action="store_true")
    pk = psub.add_parser("packet"); pk.add_argument("--company", required=True)
    pl = psub.add_parser("list"); pl.add_argument("--company"); pp.set_defaults(fn=cmd_people)

    r = sub.add_parser("rank", help="评分 → 机会 → 优先级"); r.add_argument("--company"); r.add_argument("--packet", action="store_true"); r.set_defaults(fn=cmd_rank)
    t = sub.add_parser("top", help="Top 机会"); t.add_argument("-n", type=int, default=10); t.set_defaults(fn=cmd_top)
    sh = sub.add_parser("show", help="查看一个机会的全部 JSON"); sh.add_argument("opp_id", type=int); sh.set_defaults(fn=cmd_show)
    o = sub.add_parser("outreach", help="生成触达文案"); o.add_argument("opp_id", type=int); o.add_argument("--channel"); o.add_argument("--pattern", default="peer_exchange"); o.add_argument("--person", type=int); o.add_argument("--force", action="store_true"); o.set_defaults(fn=cmd_outreach)
    c = sub.add_parser("cards", help="生成 Top N 作战卡"); c.add_argument("-n", type=int, default=10); c.add_argument("--force", action="store_true"); c.set_defaults(fn=cmd_cards)
    sub.add_parser("brief", help="作战日报").set_defaults(fn=cmd_brief)

    cr = sub.add_parser("crm", help="状态 / 触点 / 待办 / 作品"); csub = cr.add_subparsers(dest="crm_cmd", required=True)
    cs = csub.add_parser("stage"); cs.add_argument("opp_id", type=int); cs.add_argument("stage", choices=STAGES); cs.add_argument("--note")
    ct = csub.add_parser("touch"); ct.add_argument("person_id", type=int); ct.add_argument("--kind", required=True, choices=sorted(crm.OUT_KINDS | crm.IN_KINDS)); ct.add_argument("--channel"); ct.add_argument("--direction", choices=["out", "in"]); ct.add_argument("--content"); ct.add_argument("--outcome"); ct.add_argument("--opp", type=int)
    cd = csub.add_parser("due"); cd.add_argument("--hours", type=float, default=24)
    cdn = csub.add_parser("done"); cdn.add_argument("task_id", type=int)
    ca = csub.add_parser("asset"); ca.add_argument("--kind", required=True, choices=["poc", "post", "teardown", "talk", "repo", "case_study"]); ca.add_argument("--title", required=True); ca.add_argument("--url"); ca.add_argument("--status", default="idea", choices=["idea", "draft", "published"]); ca.add_argument("--company"); ca.add_argument("--notes")
    csub.add_parser("stages"); cr.set_defaults(fn=cmd_crm)

    pk = sub.add_parser("packet", help="导入 / 列出 packet"); pksub = pk.add_subparsers(dest="packet_cmd", required=True)
    pi = pksub.add_parser("ingest"); pi.add_argument("files", nargs="+"); pksub.add_parser("list"); pk.set_defaults(fn=cmd_packet)

    ra = sub.add_parser("run-all", help="一键跑完整条管道（Pilot 循环）"); ra.add_argument("--company"); ra.set_defaults(fn=cmd_run_all)
    return p


def main(argv=None):
    args = build_parser().parse_args(argv)
    args.fn(args)


if __name__ == "__main__":
    main()
