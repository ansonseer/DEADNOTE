"""CRM：机会状态机 + 触点记录 + 跟进排期 + 人脉账户。

规则全部是确定性的（代码），所以你随时能解释"为什么今天要做这件事"。
"""
from __future__ import annotations

from datetime import datetime

from .db import (STAGES, TERMINAL_STAGES, get, hours_from_now, insert, j, now, one, parse_ts, rows, unj, update)

PATH_LADDER = {0: "无渠道", 1: "冷联系", 2: "普通内推", 3: "Warm Referral", 4: "HM 推荐", 5: "Sponsor"}
OUT_KINDS = {"first_msg", "followup", "value_given", "ask", "note"}
IN_KINDS = {"reply", "call", "meeting", "referral", "note"}
HM_ROLES = {"hiring_manager", "team_lead", "exec"}


def _cadence(settings) -> dict:
    return settings.scoring.get("cadence", {})


def set_stage(conn, settings, opp_id: int, stage: str, note: str | None = None) -> dict:
    if stage not in STAGES:
        raise ValueError(f"未知阶段 {stage}，可选：{STAGES}")
    opp = get(conn, "opportunities", opp_id)
    if not opp:
        raise ValueError(f"没有机会 #{opp_id}")
    from .stages.rank import NEXT_ACTION
    cad = _cadence(settings)
    due = {"referral_requested": cad.get("referral_check_hours", 120), "replied": cad.get("reply_next_action_hours", 24),
           "in_conversation": cad.get("conversation_value_touch_hours", 168)}.get(stage)
    fields = {"stage": stage, "next_action": NEXT_ACTION.get(stage, ""), "next_action_at": hours_from_now(due) if due else None}
    update(conn, "opportunities", opp_id, fields)
    if due:
        _add_task(conn, opp_id, opp.get("person_id"), NEXT_ACTION.get(stage, stage), hours_from_now(due), opp.get("tier") or "B")
    if note:
        insert(conn, "touchpoints", {"opportunity_id": opp_id, "person_id": opp.get("person_id"), "kind": "note", "direction": "out",
                                     "content": note, "at": now()})
    return get(conn, "opportunities", opp_id)


def _add_task(conn, opp_id, person_id, action, due_at, priority="B") -> int:
    return insert(conn, "tasks", {"opportunity_id": opp_id, "person_id": person_id, "action": action, "due_at": due_at, "priority": priority})


def _cancel_pending(conn, person_id: int, contains: str = "follow-up") -> None:
    conn.execute("UPDATE tasks SET done_at = ? WHERE person_id = ? AND done_at IS NULL AND action LIKE ?",
                 (now(), person_id, f"%{contains}%"))
    conn.commit()


def log_touch(conn, settings, person_id: int, kind: str, channel: str = "", direction: str | None = None,
              content: str = "", outcome: str = "", opp_id: int | None = None) -> dict:
    """记录一次触点，并按规则推进关系、路径等级、机会阶段与跟进任务。"""
    person = get(conn, "people", person_id)
    if not person:
        raise ValueError(f"没有人物 #{person_id}")
    direction = direction or ("out" if kind in OUT_KINDS and kind not in IN_KINDS else "in")
    if kind not in OUT_KINDS | IN_KINDS:
        raise ValueError(f"未知触点类型 {kind}，可选：{sorted(OUT_KINDS | IN_KINDS)}")
    if opp_id is None:
        opp = one(conn, "SELECT * FROM opportunities WHERE person_id = ? ORDER BY fit_score DESC LIMIT 1", (person_id,))
        opp_id = opp["id"] if opp else None
    else:
        opp = get(conn, "opportunities", opp_id)
    insert(conn, "touchpoints", {"opportunity_id": opp_id, "person_id": person_id, "channel": channel, "direction": direction,
                                 "kind": kind, "content": content, "outcome": outcome, "at": now()})
    cad = _cadence(settings)
    fields: dict = {"last_touch_at": now()}
    rel, level = person.get("relationship") or "cold", int(person.get("path_level") or 0)
    role = person.get("role_type") or "employee"
    stage = None
    tier = (opp or {}).get("tier") or "B"

    if direction == "out":
        if kind == "first_msg":
            rel = "contacted" if rel == "cold" else rel
            level = max(level, 1)
            stage = "contacted"
            _add_task(conn, opp_id, person_id, f"follow-up 1：给价值（{person['name']}）", hours_from_now(cad.get("followup_1_hours", 60)), tier)
        elif kind == "followup":
            n_follow = one(conn, "SELECT COUNT(*) AS n FROM touchpoints WHERE person_id = ? AND kind = 'followup'", (person_id,))["n"]
            _cancel_pending(conn, person_id)
            if n_follow < cad.get("max_followups", 2):
                _add_task(conn, opp_id, person_id, f"follow-up {n_follow + 1}：收尾并问是否有更合适的人（{person['name']}）",
                          hours_from_now(cad.get("followup_2_hours", 168)), tier)
            else:
                fields["relationship"] = "parked"
                rel = "parked"
                fields["notes"] = ((person.get("notes") or "") + f"\n[{now()}] {n_follow} 次跟进无回复，暂停；换同团队另一位联系人。").strip()
        elif kind == "value_given":
            fields["value_given"] = int(person.get("value_given") or 0) + 1
        elif kind == "ask":
            fields["asks"] = int(person.get("asks") or 0) + 1
            stage = "referral_requested"
            _add_task(conn, opp_id, person_id, f"确认内推/推荐进度（{person['name']}）", hours_from_now(cad.get("referral_check_hours", 120)), tier)
    else:
        _cancel_pending(conn, person_id)
        if kind == "reply":
            rel = "replied" if rel in ("cold", "contacted", "parked") else rel
            level = max(level, 2)
            stage = "replied"
            _add_task(conn, opp_id, person_id, f"24h 内回复并推进对话（{person['name']}）", hours_from_now(cad.get("reply_next_action_hours", 24)), tier)
        elif kind in ("call", "meeting"):
            rel = "warm"
            level = max(level, 4 if role in HM_ROLES else 3)
            stage = "in_conversation"
            _add_task(conn, opp_id, person_id, f"会后 24h 内发感谢 + 一个具体价值（{person['name']}）", hours_from_now(24), tier)
        elif kind == "referral":
            rel = "advocate"
            level = max(level, 5 if role in HM_ROLES else 3)
            stage = "referred"
    fields.update({"relationship": rel, "path_level": level})
    update(conn, "people", person_id, fields)
    if stage and opp_id:
        current = (opp or {}).get("stage") or "identified"
        if STAGES.index(stage) > STAGES.index(current) or current in TERMINAL_STAGES:
            set_stage(conn, settings, opp_id, stage)
    return get(conn, "people", person_id)


def due_tasks(conn, within_hours: float = 24) -> list[dict]:
    horizon = hours_from_now(within_hours)
    return rows(conn, """SELECT t.*, p.name AS person_name, c.name AS company, o.tier
                         FROM tasks t LEFT JOIN people p ON p.id = t.person_id
                         LEFT JOIN opportunities o ON o.id = t.opportunity_id
                         LEFT JOIN companies c ON c.id = o.company_id
                         WHERE t.done_at IS NULL AND (t.due_at IS NULL OR t.due_at <= ?)
                         ORDER BY CASE o.tier WHEN 'A1' THEN 0 WHEN 'A2' THEN 1 WHEN 'B' THEN 2 ELSE 3 END, t.due_at""", (horizon,))


def upcoming_tasks(conn) -> list[dict]:
    return rows(conn, """SELECT t.*, p.name AS person_name, c.name AS company, o.tier FROM tasks t
                         LEFT JOIN people p ON p.id = t.person_id LEFT JOIN opportunities o ON o.id = t.opportunity_id
                         LEFT JOIN companies c ON c.id = o.company_id
                         WHERE t.done_at IS NULL AND t.due_at > ? ORDER BY t.due_at LIMIT 20""", (hours_from_now(24),))


def complete_task(conn, task_id: int) -> None:
    update(conn, "tasks", task_id, {"done_at": now()})


def stale_contacts(conn, settings) -> list[dict]:
    """发了消息、没回复、又没有待办的人：系统的漏网之鱼。"""
    cad = _cadence(settings)
    out = []
    for p in rows(conn, "SELECT * FROM people WHERE relationship = 'contacted'"):
        pending = one(conn, "SELECT id FROM tasks WHERE person_id = ? AND done_at IS NULL", (p["id"],))
        last = parse_ts(p.get("last_touch_at"))
        if pending or not last:
            continue
        hours = (datetime.now(last.tzinfo) - last).total_seconds() / 3600
        if hours >= cad.get("followup_1_hours", 60):
            out.append({**p, "hours_since": round(hours)})
    return out


def account_warnings(conn, settings) -> list[dict]:
    ratio = float(settings.scoring.get("relationship_account", {}).get("min_value_to_ask_ratio", 1.0))
    return [p for p in rows(conn, "SELECT * FROM people WHERE asks > 0") if (p.get("value_given") or 0) < ratio * p["asks"]]


def metrics(conn) -> dict:
    by_stage = {r["stage"]: r["n"] for r in rows(conn, "SELECT stage, COUNT(*) AS n FROM opportunities GROUP BY stage")}
    people = {r["relationship"]: r["n"] for r in rows(conn, "SELECT relationship, COUNT(*) AS n FROM people GROUP BY relationship")}
    contacted = sum(v for k, v in people.items() if k in ("contacted", "replied", "warm", "advocate", "parked"))
    replied = sum(v for k, v in people.items() if k in ("replied", "warm", "advocate"))
    counts = {t: one(conn, f"SELECT COUNT(*) AS n FROM {t}")["n"] for t in ("companies", "teams", "jobs", "people", "opportunities", "touchpoints", "assets")}
    counts["pilot_companies"] = one(conn, "SELECT COUNT(*) AS n FROM companies WHERE status = 'pilot'")["n"]
    counts["verified_teams"] = one(conn, "SELECT COUNT(*) AS n FROM teams WHERE verified = 1")["n"]
    counts["relevant_jobs"] = one(conn, "SELECT COUNT(*) AS n FROM jobs WHERE status = 'classified' AND category_id BETWEEN 1 AND 3")["n"]
    runs = one(conn, "SELECT COUNT(*) AS n, COALESCE(SUM(input_tokens),0) AS i, COALESCE(SUM(output_tokens),0) AS o FROM runs")
    return {"by_stage": by_stage, "people": people, "contacted": contacted, "replied": replied,
            "reply_rate": round(replied / contacted, 2) if contacted else None, "counts": counts,
            "llm_calls": runs["n"], "tokens_in": runs["i"], "tokens_out": runs["o"]}


def add_asset(conn, kind: str, title: str, url: str = "", status: str = "idea", company_ref=None, person_id=None, notes="") -> int:
    from .db import find_company
    company = find_company(conn, company_ref) if company_ref else None
    return insert(conn, "assets", {"kind": kind, "title": title, "url": url or None, "status": status,
                                   "company_id": (company or {}).get("id"), "person_id": person_id, "notes": notes or None})
