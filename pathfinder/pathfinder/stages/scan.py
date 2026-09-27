"""阶段 1-2：市场扫描 + 公司筛选。

seeds.yaml → companies 表 → 按 tier / 中澳足迹 / 团队假设数量打 screen_score → 前 pilot_size 家进入 pilot
→ 对 pilot 公司做 company_enrich（BU / 团队假设、招聘风格、注意点）。
"""
from __future__ import annotations

from ..db import insert, j, one, rows, unj, update, upsert_company, upsert_team, pilot_companies, find_company
from ..llm import prompts
from ..packets import export_packet


def load_seeds(conn, settings) -> int:
    seeds = settings.seeds
    n = 0
    for c in seeds.get("companies", []):
        existing = one(conn, "SELECT id, status FROM companies WHERE name = ?", (c["name"],))
        fields = dict(aliases=j(c.get("aliases", [])), tier=c.get("tier"), hq=c.get("hq"),
                      au_footprint=1 if c.get("au_footprint") else 0, why=c.get("why"),
                      careers_url=c.get("careers_url"), screen_boost=float(c.get("screen_boost", 0) or 0))
        cid = upsert_company(conn, c["name"], **fields)
        for h in c.get("team_hypotheses", []):
            if not one(conn, "SELECT id FROM teams WHERE company_id = ? AND name = ?", (cid, h)):
                insert(conn, "teams", {"company_id": cid, "name": h, "confidence": 0.3, "verified": 0})
        if not existing:
            n += 1
    for c in seeds.get("excluded", []):
        upsert_company(conn, c["name"], status="excluded", why=c.get("reason"))
    return n


def screen(conn, settings) -> list[dict]:
    """确定性筛选：不用模型。规则写在这里，你能一眼看懂为什么某家进了 pilot。"""
    cfg = settings.scoring.get("screen", {})
    tier_weight = {int(k): float(v) for k, v in cfg.get("tier_weight", {1: 3.0, 2: 2.4, 3: 2.8, 4: 2.5}).items()}
    au_bonus = float(cfg.get("au_bonus", 0.5)) if settings.profile.get("long_term", {}).get("au_bridge_bonus") else 0.0
    per_team = float(cfg.get("team_hypothesis_bonus", 0.1))
    size = int(settings.seeds.get("pilot_size", 20))
    scored = []
    for c in rows(conn, "SELECT * FROM companies WHERE status != 'excluded'"):
        n_teams = one(conn, "SELECT COUNT(*) AS n FROM teams WHERE company_id = ?", (c["id"],))["n"]
        score = (tier_weight.get(c.get("tier") or 3, 2.0) + (au_bonus if c.get("au_footprint") else 0)
                 + min(n_teams, 3) * per_team + float(c.get("screen_boost") or 0))
        scored.append((score, c))
    scored.sort(key=lambda x: (-x[0], x[1]["tier"] or 9, x[1]["name"]))
    pilot = []
    for i, (score, c) in enumerate(scored):
        status = "pilot" if i < size else "bench"
        update(conn, "companies", c["id"], {"screen_score": round(score, 2), "status": status})
        if status == "pilot":
            pilot.append({**c, "screen_score": score, "status": status})
    return pilot


def enrich(conn, router, settings, company_ref: str | None = None, packet: bool = False, force: bool = False) -> list[str]:
    targets = [find_company(conn, company_ref)] if company_ref else pilot_companies(conn)
    messages = []
    for c in targets:
        if not c:
            messages.append(f"找不到公司：{company_ref}")
            continue
        if c.get("enrich") and not force:
            continue
        hyps = [t["name"] for t in rows(conn, "SELECT name FROM teams WHERE company_id = ?", (c["id"],))]
        seed = {**c, "aliases": unj(c.get("aliases"), []), "team_hypotheses": hyps}
        system, user = prompts.company_enrich(seed, settings.taxonomy)
        context = {"company_id": c["id"], "company_name": c["name"], "team_hypotheses": hyps,
                   "au_footprint": bool(c.get("au_footprint"))}
        if packet:
            p = export_packet("company_enrich", context, system, user, c["name"])
            messages.append(f"已导出 packet：{p}")
            continue
        result = router.call("company_enrich", system, user, context=context)
        messages.append(ingest_enrich(conn, settings, context, result))
    return messages


def ingest_enrich(conn, settings, context: dict, result: dict) -> str:
    cid = int(context["company_id"])
    update(conn, "companies", cid, {"enrich": j(result), "status": one(conn, "SELECT status FROM companies WHERE id=?", (cid,))["status"]})
    for t in result.get("teams", []):
        upsert_team(conn, cid, t["name"], bu=t.get("bu"), direction=t.get("direction", "unknown"),
                    description=t.get("description"), confidence=float(t.get("confidence", 0.3)))
    return f"{context.get('company_name')}：写入 {len(result.get('teams', []))} 个团队假设"


def run(conn, router, settings, company: str | None = None, packet: bool = False) -> list[str]:
    n = load_seeds(conn, settings)
    pilot = screen(conn, settings)
    out = [f"载入种子公司 {n} 家（新增），pilot {len(pilot)} 家"]
    out += enrich(conn, router, settings, company, packet=packet)
    return out
