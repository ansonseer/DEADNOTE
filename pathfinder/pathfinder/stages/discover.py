"""阶段 3：岗位发现。

1) 岗位名扩展（国内模型）→ titles.json；
2) 按公司 × 类别生成查询 → 搜索（或导出查询清单让你手动看官网 / BOSS）→ jobs 表；
3) 给每条岗位打标签（jd_classify）：类别、role_match、seniority_fit、方向、负向命中。
"""
from __future__ import annotations

import json
from pathlib import Path

from ..config import data_dir
from ..db import find_company, insert, j, now, one, pilot_companies, rows, unj, update
from ..llm import prompts
from ..packets import export_packet
from ..render import write

JOB_URL_HINTS = ("zhipin.com", "liepin.com", "lagou.com", "nowcoder.com", "talent.", "careers.", "jobs.", "career.", "campus.", "linkedin.com/jobs", "shixiseng.com")


def titles_path() -> Path:
    return data_dir() / "titles.json"


def load_titles(settings) -> dict:
    """taxonomy.yaml 的叫法 + 模型扩展的叫法（如果有缓存）。"""
    base = {}
    for c in settings.taxonomy.get("categories", []):
        base[str(c["id"])] = {"titles": list(c.get("titles", [])), "search_queries": [], "notes": ""}
    p = titles_path()
    if p.exists():
        cached = json.loads(p.read_text(encoding="utf-8"))
        for cid, data in cached.items():
            if cid in base:
                base[cid]["titles"] = list(dict.fromkeys(base[cid]["titles"] + data.get("titles", [])))
                base[cid]["search_queries"] = data.get("search_queries", [])
                base[cid]["notes"] = data.get("notes", "")
    return base


def expand_titles(conn, router, settings, force: bool = False, packet: bool = False) -> list[str]:
    p = titles_path()
    cached = json.loads(p.read_text(encoding="utf-8")) if p.exists() else {}
    out = []
    for c in settings.taxonomy.get("categories", []):
        cid = str(c["id"])
        if cid in cached and not force:
            continue
        system, user = prompts.title_expand(c)
        context = {"category_id": c["id"], "category_name": c["name"]}
        if packet:
            out.append(f"已导出 packet：{export_packet('title_expand', context, system, user, f'cat{cid}')}")
            continue
        result = router.call("title_expand", system, user, context=context)
        out.append(ingest_titles(conn, settings, context, result))
    return out


def ingest_titles(conn, settings, context: dict, result: dict) -> str:
    p = titles_path()
    cached = json.loads(p.read_text(encoding="utf-8")) if p.exists() else {}
    cid = str(result.get("category_id") or context.get("category_id"))
    cached[cid] = {"titles": result.get("titles", []), "search_queries": result.get("search_queries", []),
                   "notes": result.get("notes", ""), "updated_at": now()}
    write(p, json.dumps(cached, ensure_ascii=False, indent=1))
    return f"类别 {cid}：{len(result.get('titles', []))} 个叫法，{len(result.get('search_queries', []))} 条查询"


def build_queries(company: dict, titles: dict, per_category: int = 3) -> list[str]:
    name = company["name"].split(" / ")[0]
    queries = []
    for cid, data in titles.items():
        qs = [q.replace("{company}", name) for q in data.get("search_queries", [])][:per_category]
        if not qs:
            qs = [f"{name} {t} 招聘" for t in data.get("titles", [])[:per_category]]
        queries += qs
    return list(dict.fromkeys(queries))


def guess_category(title: str, settings) -> int:
    t = (title or "").lower()
    for c in settings.taxonomy.get("categories", []):
        for known in c.get("titles", []):
            if known.lower() in t:
                return int(c["id"])
    if any(k in t for k in ("解决方案", "售前", "solution", "forward deployed", "顾问")):
        return 1
    if any(k in t for k in ("agent", "智能体", "应用", "rag", "llm", "大模型")):
        return 2
    if any(k in t for k in ("校招", "管培", "应届", "graduate", "实习")):
        return 3
    return 0


def add_job(conn, company_id: int, title: str, url: str | None = None, city: str | None = None,
            jd_text: str | None = None, source: str = "manual", team_id: int | None = None,
            posted_at: str | None = None, verified: int = 0) -> int:
    existing = None
    if url:
        existing = one(conn, "SELECT id FROM jobs WHERE company_id = ? AND url = ?", (company_id, url))
    if not existing:
        existing = one(conn, "SELECT id FROM jobs WHERE company_id = ? AND title = ? AND (url IS NULL OR url = '')", (company_id, title))
    if existing:
        fields = {k: v for k, v in dict(city=city, jd_text=jd_text, team_id=team_id, posted_at=posted_at).items() if v}
        if verified:
            fields["verified"] = 1
        update(conn, "jobs", existing["id"], fields)
        return existing["id"]
    return insert(conn, "jobs", {"company_id": company_id, "title": title, "url": url, "city": city, "jd_text": jd_text,
                                 "source": source, "team_id": team_id, "posted_at": posted_at, "verified": verified,
                                 "status": "candidate"})


def search_jobs(conn, searcher, settings, company_ref: str | None = None, max_queries: int = 6) -> list[str]:
    titles = load_titles(settings)
    targets = [find_company(conn, company_ref)] if company_ref else pilot_companies(conn)
    out = []
    checklist_lines = []
    for c in targets:
        if not c:
            continue
        queries = build_queries(c, titles)[:max_queries]
        if not searcher.enabled:
            checklist_lines.append(f"\n## {c['name']}（官网招聘：{c.get('careers_url') or '未知'}）")
            checklist_lines += [f"- [ ] {q}" for q in queries]
            continue
        added = 0
        for q in queries:
            results = searcher.search(q, n=8)
            insert(conn, "queries", {"stage": "discover", "company_id": c["id"], "query": q, "provider": searcher.name, "n_results": len(results)})
            for r in results:
                if not r.url or not any(h in r.url for h in JOB_URL_HINTS):
                    continue
                before = one(conn, "SELECT COUNT(*) AS n FROM jobs", ())["n"]
                add_job(conn, c["id"], r.title[:120], url=r.url, jd_text=r.snippet, source=searcher.name, posted_at=r.date or None)
                added += one(conn, "SELECT COUNT(*) AS n FROM jobs", ())["n"] - before
        out.append(f"{c['name']}：{len(queries)} 条查询，新增 {added} 条候选岗位")
    if checklist_lines:
        p = write(data_dir() / "packets" / "discover_checklist.md",
                  "# 岗位发现清单（未配置搜索 API 时手动执行）\n\n"
                  "逐条在 官网招聘页 / BOSS 直聘 / 牛客 / LinkedIn 搜索，找到相关岗位后用：\n"
                  "`pf jobs add --company 公司名 --title 岗位名 --url 链接 --city 城市 --jd-file jd.txt`\n" + "\n".join(checklist_lines))
        out.append(f"未配置搜索：已生成查询清单 {p}")
    return out


def classify(conn, router, settings, company_ref: str | None = None, packet: bool = False, force: bool = False) -> list[str]:
    sql = "SELECT j.*, c.name AS company_name FROM jobs j JOIN companies c ON c.id = j.company_id WHERE 1=1"
    params: list = []
    if not force:
        sql += " AND j.status = 'candidate'"
    if company_ref:
        c = find_company(conn, company_ref)
        if not c:
            return [f"找不到公司：{company_ref}"]
        sql += " AND j.company_id = ?"
        params.append(c["id"])
    out = []
    for job in rows(conn, sql, params):
        system, user = prompts.jd_classify(job, settings.taxonomy, settings.profile)
        context = {"job_id": job["id"], "company_name": job["company_name"], "title": job["title"], "city": job.get("city"),
                   "category_hint": guess_category(job["title"], settings)}
        if packet:
            label = job["company_name"] + "_" + job["title"]
            out.append(f"已导出 packet：{export_packet('jd_classify', context, system, user, label)}")
            continue
        result = router.call("jd_classify", system, user, context=context)
        out.append(ingest_classify(conn, settings, context, result))
    return out or ["没有待分类的岗位"]


def ingest_classify(conn, settings, context: dict, result: dict) -> str:
    job_id = int(context["job_id"])
    negatives = result.get("negative_hits", [])
    rejected = result.get("category_id", 0) == 0 or (len(negatives) >= 2 and result.get("role_match", 0) < 4)
    update(conn, "jobs", job_id, {"features": j(result), "category_id": int(result.get("category_id", 0)),
                                  "city": result.get("city") or None, "seniority": result.get("years_required"),
                                  "status": "rejected" if rejected else "classified"})
    return f"岗位 #{job_id} {context.get('title')} → 类别 {result.get('category_id')}，role_match {result.get('role_match')}，{'排除' if rejected else '保留'}"


def run(conn, router, searcher, settings, company: str | None = None, packet: bool = False) -> list[str]:
    out = expand_titles(conn, router, settings, packet=packet)
    out += search_jobs(conn, searcher, settings, company)
    out += classify(conn, router, settings, company, packet=packet)
    return out
