"""离线 mock：每个任务返回一份符合 schema 的、和输入沾边的假结果。

用途：1) 不花钱先把管道跑通；2) 写测试；3) 演示作战卡长什么样。
所有内容都是明显的占位文本，不代表任何真实公司/人物的事实。
"""
from __future__ import annotations

import hashlib


def _h(*parts: str) -> int:
    return int(hashlib.md5("|".join(parts).encode("utf-8")).hexdigest()[:6], 16)


def mock_result(task: str, ctx: dict) -> dict:
    company = ctx.get("company_name", "某公司")
    team = ctx.get("team_name", f"{company} AI 解决方案团队")
    seed = _h(task, company, team)

    if task == "title_expand":
        cid = int(ctx.get("category_id", 1))
        base = {1: ["AI 售前工程师", "大模型解决方案架构师", "行业解决方案专家"],
                2: ["大模型应用工程师", "Agent 开发工程师", "AI 应用工程师"],
                3: ["技术管培生", "解决方案工程师（应届）", "Graduate Engineer"]}[cid]
        return {
            "category_id": cid,
            "titles": base + [f"{base[0]}（mock 扩展）"],
            "search_queries": [f"{{company}} {t} 招聘" for t in base] + [f"{{company}} {base[0]} 牛客 内推"],
            "notes": "mock：真实运行时由国内模型扩展。",
        }

    if task == "company_enrich":
        hyps = ctx.get("team_hypotheses") or [f"{company} 大模型解决方案团队"]
        return {
            "teams": [
                {"name": h, "bu": ctx.get("bu", "AI 事业部"), "direction": ["enterprise_ai", "agent", "industry_delivery"][i % 3],
                 "description": f"（mock）负责 {company} 面向企业客户的大模型方案与交付。",
                 "confidence": 0.5, "how_to_verify": "查官网招聘页 + 近半年会议议程里的团队署名。"}
                for i, h in enumerate(hyps[:4])
            ],
            "hiring_style": "（mock）社招常年开放解决方案岗；校招每年 8-10 月；内推需在系统里填写内推码。",
            "culture_notes": "（mock）ToB 交付节奏，重视客户现场能力。",
            "watchouts": "（mock）部分『解决方案』岗位实际偏销售支持，需看 JD 是否含 PoC/工程要求。",
        }

    if task == "jd_classify":
        title = ctx.get("title", "")
        cid = ctx.get("category_hint", 1)
        return {
            "category_id": int(cid),
            "role_match": 6 + seed % 4,
            "seniority_fit": 5 + seed % 5,
            "direction": ["enterprise_ai", "agent", "industry_delivery", "platform"][seed % 4],
            "years_required": "1-3 年",
            "city": ctx.get("city") or "上海",
            "negative_hits": [],
            "key_responsibilities": ["理解客户需求并输出方案", "搭建 PoC / Demo", "配合交付与迭代"],
            "key_requirements": ["熟悉 LLM 应用开发", "良好的沟通表达", "有 Agent / RAG 项目经验"],
            "summary": f"（mock）{title or '解决方案岗'}：偏客户侧的 AI 方案与 PoC 工作。",
        }

    if task == "team_research":
        return {
            "team_name": team,
            "direction": ctx.get("direction", "enterprise_ai"),
            "what_they_do_now": f"（mock）{team} 近半年在推企业 Agent 平台化与行业 PoC，公开分享过多个客户案例。",
            "signals": [
                {"kind": "talk", "title": f"{company} 团队在技术大会分享企业 Agent 落地", "url": "https://example.com/talk",
                 "date": "2026-07-15", "summary": "（mock）分享了 PoC 到上线的路径与踩坑。", "strength": 3},
                {"kind": "hiring", "title": f"{company} 解决方案岗位在招", "url": "https://example.com/jobs",
                 "date": "2026-08-20", "summary": "（mock）官网可见 1-3 年经验的解决方案岗位。", "strength": 2},
            ],
            "why_they_need_this_role": "（mock）客户 PoC 数量增长快，需要既能沟通又能快速搭建的人。",
            "conversation_hooks": ["企业 Agent PoC 里最难说服客户的一环是什么", "知识库问答在真实客户数据上的准确率怎么评测", "PoC 到上线时权限/成本如何收口"],
            "confidence": 0.55,
        }

    if task == "people_assess":
        people = ctx.get("people") or [{"name": "示例联系人", "title": "解决方案负责人"}]
        out = []
        for i, p in enumerate(people):
            t = (p.get("title") or "")
            role = "team_lead" if ("负责人" in t or "Lead" in t or "经理" in t) else ("senior_ic" if ("高级" in t or "Senior" in t or "专家" in t) else "employee")
            out.append({
                "name": p["name"], "role_type": role,
                "why_contact": f"（mock）{p['name']} 是 {team} 的{'负责人' if role == 'team_lead' else '核心成员'}，直接拥有招聘话语权或能引荐。",
                "hook": f"（mock）曾公开分享过 {company} 的企业 Agent PoC 经验。",
                "suggested_channel": "linkedin" if i % 2 else "maimai",
                "path_level_potential": 4 if role == "team_lead" else 3,
                "long_term_tags": ["hiring_now", "peer"] + (["au_cn_bridge"] if ctx.get("au_footprint") else []),
                "risk": "（mock）公开信息有限，需先核实是否仍在该团队。",
            })
        return {"people": out, "recommended_first": out[0]["name"], "rationale": "（mock）优先联系拥有 headcount 决策权的人。"}

    if task == "fit_assess":
        return {
            "experience_overlap": 6 + seed % 4,
            "matched_points": [
                {"jd_need": "与业务沟通并输出方案", "your_evidence": "悉尼企业 AI 落地项目中负责与业务负责人梳理流程"},
                {"jd_need": "快速搭建 PoC", "your_evidence": "用 Agent / Workflow / RAG 数天内做出可演示的 MVP"},
            ],
            "gaps": ["国内行业客户经验较少", "对该公司平台的产品细节需补课"],
            "why_fit_summary": "（mock）悉尼企业 AI 落地经历与该团队的企业 Agent PoC 需求高度匹配。",
        }

    if task == "outreach_write":
        person = ctx.get("person_name", "您")
        return {
            "channel": ctx.get("channel", "maimai"),
            "first_message": f"（mock）{person} 你好，看了你关于企业 Agent PoC 的分享，其中「先用一个部门的真实流程做验收」这点和我在悉尼做企业 AI 落地时的经验很像。想请教一个问题：你们在 PoC 阶段是怎么定义『可上线』的标准的？",
            "followup_1": "（mock）补充一个我这边的小实验结果：用同样的评测方法在客户真实数据上跑，准确率从 62% 提到 81%，主要靠改检索切片策略。附上简短总结，供参考。",
            "followup_2": "（mock）最近一次打扰：如果你这边不方便，是否有更合适的同事我可以请教？谢谢。",
            "referral_transition": "（mock）聊下来觉得你们团队的方向和我的经历很贴，想正式了解一下今年是否有 junior / graduate 的 headcount，如果合适我想走一下流程，走内推还是直接发简历给你更方便？",
            "email_subject": "",
            "notes": "（mock）发送前先在对方最近一篇分享下留一条有内容的评论。",
        }

    if task == "card_write":
        return {
            "why_fit": f"（mock）{team} 需要能和业务沟通并快速做 PoC 的人，你的悉尼企业 AI 落地经历正是这一类证据。",
            "team_now": f"（mock）{team} 近半年在推企业 Agent 平台化与行业 PoC。",
            "why_this_person": "（mock）该联系人直接负责团队方向与招聘，且有公开分享，回复率通常更高。",
            "referral_assessment": "（mock）可走内推；如对话建立，有机会升级为 HM 推荐（路径等级 4）。",
            "next_action": "（mock）今天：评论 + 私信；48-72h：follow-up 给价值；7 天：问 headcount。",
            "risks": "（mock）岗位可能要求 3 年以上经验；备选：先争取实习/项目合作。",
        }

    raise ValueError(f"mock 不认识任务 {task}")
