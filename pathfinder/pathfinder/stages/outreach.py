"""阶段 9：个性化触达。系统起草，人来发送。"""
from __future__ import annotations

from ..config import data_dir
from ..db import get, j, one, unj, update
from ..llm import prompts
from ..render import write

PATTERNS = {
    "peer_exchange": "同行交流：以对方公开分享/团队正在解决的问题切入，提出一个具体问题；不提岗位。",
    "artifact": "作品敲门：你基于对方平台/场景做了一个小实验或拆解，分享结果并请教反馈；不提岗位。",
    "affinity": "同源切入：校友 / 同乡 / 海归 / 同一社区 的共同点开场，再转到对方团队正在做的事；不提岗位。",
    "au_bridge": "中澳桥梁：以你在澳洲企业落地 AI 的一线观察，和对方讨论出海/跨境或海外客户的差异；不提岗位。",
}

CHANNEL_KEYS = {"maimai": "脉脉私信", "linkedin": "LinkedIn 邀请附言", "wechat": "微信", "email": "邮件",
                "zhihu": "知乎 / 即刻 / 公众号留言", "jike": "知乎 / 即刻 / 公众号留言", "github": "GitHub Issue / PR", "other": "其他"}


def channel_rule(settings, channel: str) -> str:
    label = CHANNEL_KEYS.get(channel, channel)
    for c in settings.sources.get("outreach_channels", []):
        if c["channel"] == label:
            return f"{c['limit']}；适合：{c['best_for']}"
    return "字数尽量控制在 150 字以内"


def pick_channel(person: dict) -> str:
    assess = unj(person.get("assess"), {}) or {}
    channels = unj(person.get("channels"), {}) or {}
    if assess.get("suggested_channel") in channels:
        return assess["suggested_channel"]
    for k in ("maimai", "linkedin", "wechat", "email", "zhihu", "jike", "github"):
        if k in channels:
            return k
    return assess.get("suggested_channel") or "maimai"


def draft(conn, router, settings, opp_id: int, channel: str | None = None, pattern: str = "peer_exchange",
          person_id: int | None = None, force: bool = False) -> dict:
    opp = get(conn, "opportunities", opp_id)
    if not opp:
        raise ValueError(f"没有机会 #{opp_id}")
    company = get(conn, "companies", opp["company_id"])
    team = get(conn, "teams", opp["team_id"]) if opp.get("team_id") else {}
    person = get(conn, "people", person_id or opp.get("person_id") or 0)
    if not person:
        raise ValueError("这个机会还没有关联联系人：先 pf people add，再 pf rank")
    if opp.get("outreach") and not force:
        return unj(opp["outreach"])
    research = unj((team or {}).get("research"), {}) or {}
    team_ctx = {**(team or {}), **research}
    channel = channel or pick_channel(person)
    if pattern not in PATTERNS:
        raise ValueError(f"未知模式 {pattern}，可选：{list(PATTERNS)}")
    if pattern == "peer_exchange" and company.get("au_footprint") and "au_cn_bridge" in (unj(person.get("tags"), []) or []):
        pattern = "au_bridge"
    system, user = prompts.outreach_write(settings.profile, company, team_ctx, person, channel, channel_rule(settings, channel),
                                          research.get("conversation_hooks", []), PATTERNS[pattern])
    context = {"company_name": company["name"], "team_name": (team or {}).get("name"), "person_name": person["name"], "channel": channel}
    result = router.call("outreach_write", system, user, context=context)
    result["pattern"] = pattern
    fields = {"outreach": j(result), "person_id": person["id"]}
    if opp.get("stage") in ("identified", "researched", "people_found"):
        fields["stage"] = "outreach_drafted"
        fields["next_action"] = "亲手发送第一条私信，并记录：pf crm touch"
    update(conn, "opportunities", opp_id, fields)
    write(data_dir() / "outreach" / f"opp_{opp_id}_{person['name']}.md", render_markdown(company, team, person, result))
    return result


def render_markdown(company: dict, team: dict, person: dict, r: dict) -> str:
    def block(title, text):
        return f"## {title}（{len(text or '')} 字）\n\n{text or '（空）'}\n"
    return (f"# 触达文案：{company['name']} / {(team or {}).get('name')} → {person['name']}（{person.get('title')}）\n\n"
            f"渠道：{r.get('channel')}｜模式：{r.get('pattern')}\n\n"
            + block("第一条私信", r.get("first_message"))
            + block("Follow-up 1（48–72h，给价值）", r.get("followup_1"))
            + block("Follow-up 2（7 天，收尾）", r.get("followup_2"))
            + block("转到岗位 / 内推的那句话", r.get("referral_transition"))
            + (f"## 邮件标题\n\n{r['email_subject']}\n\n" if r.get("email_subject") else "")
            + f"## 发送前提醒\n\n{r.get('notes')}\n")
