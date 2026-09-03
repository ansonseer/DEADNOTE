"""阶段 8：评分与优先级。

Fit Score 由代码按 config/scoring.yaml 计算，每一分都能追溯到证据；模型只负责 fit_assess（经历重叠度）。
一个"机会" = 公司 × 团队 × 岗位（岗位可以为空：先找对团队，headcount 往往不公开）。
"""
from __future__ import annotations

from datetime import date, datetime

from ..db import find_company, insert, j, one, pilot_companies, rows, unj, update
from ..llm import prompts
from ..packets import export_packet

ROLE_PRIORITY = ["hiring_manager", "team_lead", "senior_ic", "exec", "employee", "recruiter"]
STRONG_DIRECTIONS = {"agent", "enterprise_ai", "industry_delivery"}

NEXT_ACTION = {
    "identified": "跑 pf research 验证团队方向与信号",
    "researched": "找人：pf people assess 会导出找人清单；录入 2-3 位团队成员",
    "people_found": "生成触达文案：pf outreach <机会ID>",
    "outreach_drafted": "亲手发送第一条私信，并记录：pf crm touch <人物ID> --kind first_msg --channel ...",
    "contacted": "等待回复；到期自动生成 follow-up 任务",
    "replied": "24 小时内回复，把对话引向团队正在解决的问题",
    "in_conversation": "先给价值（小实验 / 资源），再自然问 headcount 与内推",
    "referral_requested": "5 天后确认内推进度；准备简历与作品链接",
    "referred": "准备面试材料；复盘团队近况",
    "applied": "跟进流程；准备面试材料",
    "interviewing": "每轮面试后复盘并更新作战卡",
    "offer": "评估 offer 与长期路径",
}


def best_team_for(conn, company_id: int, job: dict | None) -> dict | None:
    if job and job.get("team_id"):
        t = one(conn, "SELECT * FROM teams WHERE id = ?", (job["team_id"],))
        if t:
            return t
    return one(conn, "SELECT * FROM teams WHERE company_id = ? ORDER BY verified DESC, confidence DESC, id ASC LIMIT 1", (company_id,))


def best_person(conn, company_id: int, team_id: int | None) -> dict | None:
    people = rows(conn, "SELECT * FROM people WHERE company_id = ? AND relationship != 'parked'", (company_id,))
    if not people:
        return None

    def key(p):
        same_team = 0 if (team_id and p.get("team_id") == team_id) else 1
        role = ROLE_PRIORITY.index(p.get("role_type")) if p.get("role_type") in ROLE_PRIORITY else 9
        potential = (unj(p.get("assess"), {}) or {}).get("path_level_potential", 1)
        return (same_team, -(p.get("path_level") or 0), role, -potential)

    return sorted(people, key=key)[0]


def fresh_signal_days(conn, team_id: int | None) -> int | None:
    if not team_id:
        return None
    days = []
    for s in rows(conn, "SELECT date FROM signals WHERE team_id = ? AND date IS NOT NULL", (team_id,)):
        try:
            days.append((date.today() - datetime.strptime(s["date"], "%Y-%m-%d").date()).days)
        except ValueError:
            continue
    return min(days) if days else None


def city_factor(city: str | None, profile: dict) -> float:
    c = profile.get("constraints", {})
    if not city:
        return 0.6
    if any(p in city or city in p for p in c.get("preferred_cities", [])):
        return 1.0
    if any(p in city or city in p for p in c.get("acceptable_cities", [])):
        return 0.7
    return 0.3


def compute_score(settings, f: dict) -> tuple[float, dict]:
    """f 里是特征；返回 (总分, 拆解)。拆解会原样进作战卡，所以每项都带说明。"""
    sc = settings.scoring
    w, bonus = sc["weights"], sc.get("bonuses", {})
    path_scores = sc.get("path_scores", [0, 0.3, 0.5, 0.7, 0.85, 1.0])
    priority = settings.category_priority(f.get("category_id", 0)) or 0.6
    direction_coef = sc["direction_scores"].get(f.get("direction", "unknown"), 0.5)
    verified_coef = 1.0 if f.get("team_verified") else 0.7

    role = w["role_match"] * (f.get("role_match", 0) / 10) * priority
    direction = w["team_direction"] * direction_coef * verified_coef
    exp = w["experience_overlap"] * (f.get("experience_overlap", 0) / 10)
    feas = w["feasibility"] * (0.7 * f.get("seniority_fit", 0) / 10 + 0.3 * f.get("city_factor", 0.6))
    cur, pot = int(f.get("path_level", 0)), int(f.get("path_potential", 0))
    cur, pot = min(cur, 5), min(max(pot, cur), 5)
    path = w["path"] * (0.6 * path_scores[cur] + 0.4 * path_scores[pot])

    extras = {}
    if f.get("au_bridge"):
        extras["au_bridge"] = bonus.get("au_bridge", 0)
    if f.get("fresh_signal_days") is not None and f["fresh_signal_days"] <= 30:
        extras["fresh_signal"] = bonus.get("fresh_signal", 0)
    if f.get("has_asset"):
        extras["proof_asset"] = bonus.get("proof_asset", 0)

    total = min(100.0, round(role + direction + exp + feas + path + sum(extras.values()), 1))
    breakdown = {
        "role_match": {"points": round(role, 1), "max": w["role_match"],
                       "note": f"岗位贴合 {f.get('role_match', 0)}/10 × 类别优先级 {priority}（{f.get('role_note', '')}）"},
        "team_direction": {"points": round(direction, 1), "max": w["team_direction"],
                           "note": f"方向 {f.get('direction')}（系数 {direction_coef}）{'，已验证' if f.get('team_verified') else '，未验证 ×0.7'}"},
        "experience_overlap": {"points": round(exp, 1), "max": w["experience_overlap"],
                               "note": f"经历重叠 {f.get('experience_overlap', 0)}/10"},
        "feasibility": {"points": round(feas, 1), "max": w["feasibility"],
                        "note": f"资历可行 {f.get('seniority_fit', 0)}/10；城市系数 {f.get('city_factor', 0.6)}（{f.get('city') or '城市未知'}）"},
        "path": {"points": round(path, 1), "max": w["path"],
                 "note": f"当前 L{cur} → 可达 L{pot}（{f.get('person_name') or '尚未找到人'}）"},
        "bonuses": {"points": sum(extras.values()), "max": sum(bonus.values()), "note": "、".join(extras) or "无"},
        "total": total,
    }
    return total, breakdown


def tier_for(settings, score: float) -> str:
    tiers = settings.scoring.get("tiers", {"A1": 85, "A2": 75, "B": 60})
    for name in ("A1", "A2", "B"):
        if score >= tiers.get(name, 999):
            return name
    return "C"


def ensure_fit(conn, router, settings, company: dict, team: dict | None, job: dict | None,
               existing: dict | None, packet: bool) -> dict | None:
    cached = unj((job or {}).get("fit")) if job else (unj((existing or {}).get("breakdown"), {}) or {}).get("fit")
    if cached:
        return cached
    team_ctx = {**(team or {}), **(unj((team or {}).get("research"), {}) or {})} if team else None
    job_ctx = {**job, "features": unj(job.get("features"), {})} if job else None
    system, user = prompts.fit_assess(settings.profile, company, team_ctx, job_ctx)
    context = {"company_id": company["id"], "company_name": company["name"], "team_name": (team or {}).get("name"),
               "job_id": (job or {}).get("id"), "opportunity_id": (existing or {}).get("id")}
    if packet:
        export_packet("fit_assess", context, system, user, f"{company['name']}_{(job or {}).get('title') or (team or {}).get('name')}")
        return None
    result = router.call("fit_assess", system, user, context=context)
    ingest_fit(conn, settings, context, result)
    return result


def ingest_fit(conn, settings, context: dict, result: dict) -> str:
    if context.get("job_id"):
        update(conn, "jobs", int(context["job_id"]), {"fit": j(result)})
    elif context.get("opportunity_id"):
        opp = one(conn, "SELECT breakdown FROM opportunities WHERE id = ?", (int(context["opportunity_id"]),))
        bd = unj((opp or {}).get("breakdown"), {}) or {}
        bd["fit"] = result
        update(conn, "opportunities", int(context["opportunity_id"]), {"breakdown": j(bd)})
    return f"{context.get('company_name')}：经历重叠 {result.get('experience_overlap')}/10"


def _find_opp(conn, company_id: int, team_id: int | None, job_id: int | None) -> dict | None:
    if job_id:
        return one(conn, "SELECT * FROM opportunities WHERE company_id = ? AND job_id = ?", (company_id, job_id))
    return one(conn, "SELECT * FROM opportunities WHERE company_id = ? AND team_id IS ? AND job_id IS NULL", (company_id, team_id))


def rank_company(conn, router, settings, company: dict, packet: bool = False) -> list[dict]:
    jobs = rows(conn, "SELECT * FROM jobs WHERE company_id = ? AND status = 'classified' AND category_id BETWEEN 1 AND 3", (company["id"],))
    candidates: list[tuple[dict | None, dict | None]] = [(job, best_team_for(conn, company["id"], job)) for job in jobs]
    if not candidates:
        team = best_team_for(conn, company["id"], None)
        if team:
            candidates = [(None, team)]
    results = []
    has_asset = bool(one(conn, "SELECT id FROM assets WHERE company_id = ? AND status != 'idea'", (company["id"],)))
    au_bridge = bool(company.get("au_footprint")) and bool(settings.profile.get("long_term", {}).get("au_bridge_bonus"))
    for job, team in candidates:
        existing = _find_opp(conn, company["id"], (team or {}).get("id"), (job or {}).get("id"))
        fit = ensure_fit(conn, router, settings, company, team, job, existing, packet) or {}
        feats = unj((job or {}).get("features"), {}) or {}
        person = best_person(conn, company["id"], (team or {}).get("id"))
        # 方向以"研究过的团队"为准；没研究过时才用 JD 推断的方向
        if team and team.get("research"):
            direction = team.get("direction") or feats.get("direction") or "unknown"
        else:
            direction = feats.get("direction") or (team or {}).get("direction") or "unknown"
        if job:
            role_match, seniority, role_note = feats.get("role_match", 4), feats.get("seniority_fit", 5), feats.get("summary", "")
        else:
            role_match = 5 if direction in STRONG_DIRECTIONS else 3
            seniority, role_note = 5, "暂无公开岗位，按团队方向估计"
        f = {
            "category_id": (job or {}).get("category_id") or (feats.get("category_id") if job else 1) or 1,
            "role_match": role_match, "role_note": role_note, "seniority_fit": seniority,
            "direction": direction, "team_verified": bool((team or {}).get("verified")),
            "experience_overlap": fit.get("experience_overlap", 0),
            "city": (job or {}).get("city") or company.get("hq"),
            "city_factor": city_factor((job or {}).get("city") or company.get("hq"), settings.profile),
            "path_level": (person or {}).get("path_level", 0) if person else 0,
            "path_potential": ((unj((person or {}).get("assess"), {}) or {}).get("path_level_potential", (person or {}).get("path_level", 0))) if person else 0,
            "person_name": (person or {}).get("name"),
            "au_bridge": au_bridge, "fresh_signal_days": fresh_signal_days(conn, (team or {}).get("id")), "has_asset": has_asset,
        }
        score, breakdown = compute_score(settings, f)
        breakdown["fit"] = fit
        breakdown["features"] = f
        tier = tier_for(settings, score)
        stage = (existing or {}).get("stage") or "identified"
        if stage == "identified" and (team or {}).get("verified"):
            stage = "researched"
        if stage in ("identified", "researched") and person and person.get("assess"):
            stage = "people_found"
        fields = {"company_id": company["id"], "team_id": (team or {}).get("id"), "job_id": (job or {}).get("id"),
                  "person_id": (person or {}).get("id"), "fit_score": score, "tier": tier, "breakdown": j(breakdown),
                  "stage": stage, "next_action": (existing or {}).get("next_action") or NEXT_ACTION.get(stage, "")}
        if existing:
            update(conn, "opportunities", existing["id"], fields)
            opp_id = existing["id"]
        else:
            opp_id = insert(conn, "opportunities", fields)
        results.append({"id": opp_id, "company": company["name"], "team": (team or {}).get("name"),
                        "job": (job or {}).get("title"), "score": score, "tier": tier, "stage": stage})
    return results


def rank(conn, router, settings, company_ref: str | None = None, packet: bool = False) -> list[dict]:
    targets = [find_company(conn, company_ref)] if company_ref else pilot_companies(conn)
    out = []
    for c in targets:
        if c:
            out += rank_company(conn, router, settings, c, packet=packet)
    return sorted(out, key=lambda r: -r["score"])


def top(conn, n: int = 10, include_terminal: bool = False) -> list[dict]:
    sql = """SELECT o.*, c.name AS company, c.au_footprint, c.hq, c.tier AS company_tier,
                    t.name AS team, t.bu, t.direction, t.verified AS team_verified, t.research,
                    jb.title AS job_title, jb.url AS job_url, jb.city AS job_city, jb.features AS job_features, jb.fit AS job_fit,
                    p.name AS person_name, p.title AS person_title, p.role_type, p.path_level, p.assess AS person_assess,
                    p.hook AS person_hook, p.why_contact, p.channels AS person_channels, p.tags AS person_tags
             FROM opportunities o
             JOIN companies c ON c.id = o.company_id
             LEFT JOIN teams t ON t.id = o.team_id
             LEFT JOIN jobs jb ON jb.id = o.job_id
             LEFT JOIN people p ON p.id = o.person_id"""
    if not include_terminal:
        sql += " WHERE o.stage NOT IN ('closed_won','closed_lost','parked')"
    sql += " ORDER BY o.fit_score DESC, o.id ASC LIMIT ?"
    return rows(conn, sql, (n,))
