"""每个模型任务的 prompt。全部中文，因为要处理的是中文招聘语境。

写 prompt 的三条规矩（docs/01 里有展开）：
1. 先给身份和边界（不编造、没证据就说没有）；
2. 再给输入材料（结构化地贴进去，不要让模型猜）；
3. 最后说清楚输出用途（模型知道下游是打分/私信，输出会更贴合）。
schema 由 router 统一追加，这里不重复。
"""
from __future__ import annotations

import json

from ..schemas import DIRECTIONS, ROLE_TYPES


def _j(obj) -> str:
    return json.dumps(obj, ensure_ascii=False, indent=1)


def profile_brief(profile: dict) -> str:
    exp = "\n".join(
        f"- {e.get('title')}：{e.get('what')}；结果：{e.get('result')}" for e in profile.get("experience", [])
    )
    assets = "；".join(
        f"{a.get('title')}（{a.get('note')}）{a.get('url')}" if isinstance(a, dict) else str(a)
        for a in profile.get("proof_assets", [])[:7]
    )
    return (
        f"姓名：{profile.get('name')}｜常驻：{profile.get('based_in')}\n"
        f"定位：{profile.get('headline')}\n{profile.get('positioning', '').strip()}\n"
        f"经历：\n{exp}\n"
        f"技能：{'、'.join(profile.get('skills', {}).get('core', []))}；"
        f"技术：{'、'.join(profile.get('skills', {}).get('tech', []))}\n"
        f"约束：经验 {profile.get('constraints', {}).get('years_experience')} 年；"
        f"城市偏好 {profile.get('constraints', {}).get('preferred_cities')}；"
        f"最早入职 {profile.get('constraints', {}).get('can_start_from')}\n"
        f"长期：{profile.get('long_term', {}).get('opc_direction')}；"
        f"{profile.get('long_term', {}).get('au_return_year')} 年计划回澳洲。\n"
        f"公开作品（可在私信里作为作品敲门的素材）：{assets or '暂无'}"
    )


BASE_SYSTEM = (
    "你是一名熟悉中国 AI 行业招聘的求职情报分析师，也是候选人的策略顾问。"
    "你只基于给定材料和你确定的公开事实作答；不确定就降低置信度或留空，绝不编造具体人名、URL、数字。"
    "你的输出会被程序直接消费（打分、入库、生成私信），所以字段必须准确、简洁、可核实。"
)


def title_expand(category: dict, notes: str = "") -> tuple[str, str]:
    system = BASE_SYSTEM + "你尤其熟悉 BOSS 直聘、牛客、脉脉、猎聘、LinkedIn 上的岗位命名习惯。"
    user = (
        f"岗位类别：{category['name']}\n原型描述：{category.get('archetype')}\n"
        f"已知叫法：{_j(category.get('titles', []))}\n"
        f"职责关键词：{_j(category.get('responsibility_keywords', []))}\n{notes}\n\n"
        "任务：\n1. 补充 10-20 个国内真实存在的其他叫法（含大厂内部叫法、校招叫法、外企在华叫法、常见错写）。\n"
        "2. 给出 10-15 条搜索查询，用 {company} 作为公司名占位符，例如「{company} 大模型解决方案 招聘」。\n"
        "3. 排除纯算法、纯销售、纯产品岗位的叫法。\n"
        f"输出 category_id={category['id']}。"
    )
    return system, user


def company_enrich(company: dict, taxonomy: dict) -> tuple[str, str]:
    system = BASE_SYSTEM + "你对国内互联网大厂、大模型公司、企业服务商的组织结构有较准确的公开认知。"
    user = (
        f"公司：{company['name']}（别名 {company.get('aliases')}）\n"
        f"我们的假设（待验证）：{_j(company.get('team_hypotheses', []))}\n"
        f"为什么关注：{company.get('why')}\n"
        f"团队方向枚举：{DIRECTIONS}；方向关键词：{_j(taxonomy.get('direction_keywords', {}))}\n\n"
        "任务：列出该公司最可能招聘【AI 售前/解决方案、AI 应用/Agent、校招/管培】的 BU 或团队（3-6 个）。"
        "每个团队给：名称、所属 BU、方向、一句话描述、置信度（0-1）、如何验证（去哪个公开来源查什么）。"
        "另外总结：hiring_style（校招/社招节奏、内推文化、常见流程）、culture_notes、watchouts（例如：解决方案岗实际偏销售、城市限制、外包比例）。"
        "不要写具体人名。"
    )
    return system, user


def jd_classify(job: dict, taxonomy: dict, profile: dict) -> tuple[str, str]:
    cats = [{"id": c["id"], "name": c["name"], "archetype": c.get("archetype")} for c in taxonomy.get("categories", [])]
    system = BASE_SYSTEM + "你负责给岗位打标签，供后续评分。"
    user = (
        f"岗位标题：{job.get('title')}\n公司：{job.get('company_name')}\n城市：{job.get('city') or '未知'}\n"
        f"来源：{job.get('source') or job.get('url') or '未知'}\n"
        f"JD 全文或摘要：\n{(job.get('jd_text') or '')[:4000] or '（无 JD 文本，只能按标题判断，请降低 role_match）'}\n\n"
        f"类别定义：{_j(cats)}\n负向信号：{_j(taxonomy.get('negative_signals', {}))}\n"
        f"候选人约束：经验 {profile.get('constraints', {}).get('years_experience')} 年、"
        f"城市偏好 {profile.get('constraints', {}).get('preferred_cities')}\n\n"
        "任务：\n- category_id：0 不相关 / 1 售前解决方案 / 2 AI 应用 / 3 校招管培。\n"
        "- role_match（0-10）：与「和业务沟通 → 方案 → PoC → 工程落地」这个 FDE 原型的贴合度。\n"
        "- seniority_fit（0-10）：以候选人经验年限和校招资格衡量的可行性（要求 5 年以上 → 低分）。\n"
        "- direction：该岗位所在团队最可能的方向。\n- negative_hits：命中的负向词原文。\n"
        "- key_responsibilities / key_requirements：各 3-6 条，摘录原文关键词。\n- summary：40 字以内。"
    )
    return system, user


def team_research(company: dict, teams: list[dict], evidence: list[dict], taxonomy: dict, web_search: bool) -> tuple[str, str]:
    system = BASE_SYSTEM + (
        "你可以使用 web_search 工具查证（优先官方来源、会议议程、技术博客、机器之心/InfoQ/36氪 等权威媒体），最多 8 次。"
        if web_search else
        "本次没有联网，只能使用下面给出的证据；证据不足时压低 confidence，不要补写没有 URL 的 signal。"
    )
    user = (
        f"公司：{company['name']}\n候选团队（假设）：{_j([{k: t.get(k) for k in ('name', 'bu', 'direction', 'description')} for t in teams])}\n"
        f"证据材料（搜索结果）：{_j(evidence) if evidence else '（无）'}\n"
        f"方向关键词：{_j(taxonomy.get('direction_keywords', {}))}\n\n"
        "任务：为最值得进入的那个团队写一份研究摘要：\n"
        "- team_name：确认后的团队名（如证据不足就沿用假设名并压低置信度）\n"
        "- what_they_do_now：最近 6 个月在做什么（产品、客户、行业、公开分享）\n"
        "- signals：每条必须有 url；kind 取 news/product/hiring/talk/org/open_source；strength 1-3；date 用 YYYY-MM-DD 或空\n"
        "- why_they_need_this_role：为什么现在需要「能和业务沟通并快速做 PoC」的人\n"
        "- conversation_hooks：3-5 个可以在私信里聊的具体话题（要具体到产品/场景，不要泛泛的『AI 落地』）\n"
        "- confidence：0-1。"
    )
    return system, user


def people_assess(company: dict, team: dict, people: list[dict], profile: dict) -> tuple[str, str]:
    system = BASE_SYSTEM + "你负责判断谁最值得联系、为什么、怎么开口。你尊重平台规则与隐私：只使用给定的公开信息。"
    user = (
        f"公司：{company['name']}｜团队：{team.get('name')}（方向 {team.get('direction')}）\n"
        f"团队研究摘要：{(team.get('what_they_do_now') or '')[:800]}\n"
        f"候选人档案：\n{profile_brief(profile)}\n\n"
        f"人物列表（公开信息）：{_j(people)}\n"
        f"role_type 枚举：{ROLE_TYPES}\n\n"
        "任务：对每个人给出 role_type、why_contact（为什么是他/她而不是别人）、hook（引用其公开分享/文章/演讲里的具体点）、"
        "suggested_channel、path_level_potential（1 冷联系 2 普通内推 3 warm referral 4 HM 推荐 5 sponsor）、"
        "long_term_tags（除了 hiring_now，还要判断是否可能成为：future_client_au、au_cn_bridge、collaborator、distribution、mentor、peer、alumni）、"
        "risk（例如：疑似已离职、是 HR 而非业务、公开信息太少）。\n"
        "recommended_first：选一个最先联系的人名，并给 rationale。人物列表里没有的人不要出现。"
    )
    return system, user


def fit_assess(profile: dict, company: dict, team: dict | None, job: dict | None) -> tuple[str, str]:
    system = BASE_SYSTEM + "你负责评估候选人经历与岗位/团队的重叠度，宁可保守，不要讨好。"
    user = (
        f"候选人档案：\n{profile_brief(profile)}\n\n"
        f"公司：{company['name']}\n团队：{team.get('name') if team else '未知'}｜方向：{team.get('direction') if team else '未知'}\n"
        f"团队近况：{(team or {}).get('what_they_do_now') or '未知'}\n"
        f"岗位：{(job or {}).get('title') or '（暂无具体岗位，按团队方向评估）'}\n"
        f"JD 要点：{_j((job or {}).get('features') or {})}\n\n"
        "任务：experience_overlap（0-10）；matched_points 每条必须引用候选人档案里的具体经历；gaps 直说；"
        "why_fit_summary ≤ 60 字，可直接放进作战卡。"
    )
    return system, user


def outreach_write(profile: dict, company: dict, team: dict, person: dict, channel: str, channel_rule: str,
                   hooks: list[str], pattern: str) -> tuple[str, str]:
    system = BASE_SYSTEM + (
        "你是一位擅长冷启动人脉的同行，写私信的原则：以对方的公开内容或团队正在解决的问题为切入；"
        "第一条不提内推、不发简历、不夸对方；提出一个具体问题或分享一个具体观察；语气平等、具体、克制；"
        "不要用『哥』『打扰了』『冒昧』开头；不堆形容词；每条消息都要让对方回复起来毫不费力。"
    )
    user = (
        f"候选人档案：\n{profile_brief(profile)}\n\n"
        f"公司：{company['name']}｜团队：{team.get('name')}｜团队近况：{(team.get('what_they_do_now') or '')[:600]}\n"
        f"对方：{person.get('name')}｜{person.get('title')}｜角色 {person.get('role_type')}\n"
        f"对方的公开内容/hook：{person.get('hook') or '（无，只能从团队近况切入）'}\n"
        f"可聊的话题：{_j(hooks)}\n"
        f"渠道：{channel}；渠道限制：{channel_rule}\n"
        f"文案模式：{pattern}\n\n"
        "任务：写 first_message（遵守渠道字数限制）、followup_1（48-72 小时后，给一个具体价值：你做过的小实验结果或一个相关资源，不催）、"
        "followup_2（7 天后，收尾并问是否有更合适的人）、referral_transition（对话建立后如何自然转到岗位、headcount 与内推的那一两句话）、"
        "email_subject（邮件渠道用，其他渠道留空）、notes（发送前的提醒：例如先关注/评论对方的哪篇内容）。"
    )
    return system, user


def card_write(profile: dict, company: dict, team: dict, job: dict | None, person: dict | None, fit: dict | None,
               breakdown: dict) -> tuple[str, str]:
    system = BASE_SYSTEM + "你负责把研究结果压缩成一张能直接行动的作战卡，每个字段 2-4 句，具体、可执行。"
    user = (
        f"候选人档案：\n{profile_brief(profile)}\n\n"
        f"公司：{company['name']}｜团队：{team.get('name')}｜方向：{team.get('direction')}\n"
        f"团队近况：{team.get('what_they_do_now')}\n为什么需要这类人：{team.get('why_they_need_this_role')}\n"
        f"岗位：{(job or {}).get('title') or '（暂无公开岗位，先建立对话再问 headcount）'}\n"
        f"最值得联系的人：{_j({k: (person or {}).get(k) for k in ('name', 'title', 'role_type', 'why_contact', 'hook', 'path_level')})}\n"
        f"经历匹配：{_j(fit or {})}\n评分拆解：{_j(breakdown)}\n\n"
        "任务：写 why_fit（为什么适合你）、team_now（这个团队最近在做什么）、why_this_person（为什么联系这个人）、"
        "referral_assessment（能不能走内推、能走多强、路径怎么升级）、next_action（今天/48h/7 天三步）、risks（最可能失败的原因与备选）。"
    )
    return system, user
