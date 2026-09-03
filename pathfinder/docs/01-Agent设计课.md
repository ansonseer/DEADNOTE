# 01 · Agent 设计课：以这个项目为教材

> 目标：读完这篇，你能解释这个系统的每一个设计决定，并且能自己改它、扩它。
> 代码里每个文件顶部都有一段"为什么这么做"，本文把它们串起来。

---

## 0. 先回答你的问题：需要 Coze 这样的载体，或 Cursor 这样的 SDK 吗？

先把几个经常被混在一起的东西分开：

| 东西 | 它是什么 | 适合 | 不适合 | 本项目的用法 |
|---|---|---|---|---|
| **Coze / 扣子** | 低代码 bot 搭建平台（拖插件、编排、发布到飞书/微信） | 对话型 bot、快速 demo、给非技术同事用 | 有数据库、评分规则、版本控制、多模型分工的**数据流水线**；难测试、平台锁定 | 不用。以后可以用它做一个"每天早上把日报推到飞书"的壳 |
| **Dify** | 开源的工作流 / Agent 平台，很多国内企业在用 | 可视化编排、私有化部署；**会用 Dify 本身就是简历信号** | 同上，复杂逻辑还是要写代码 | 第二阶段可选：把 research 阶段搬成 Dify workflow，顺便学 |
| **Cursor** | 带 AI 的 IDE，帮你写代码 | 写代码 | 它不是 agent 的运行时，也不是载体 | 和 Claude Code 是同类工具，二选一即可。你已经在用 Claude Code |
| **Claude Code** | 终端里的编码 agent：自带文件、终端、搜索、网页抓取工具 | **建造者 + 操作员**：搭系统、跑 packet、做研究 | 长期定时运行（它是会话式的） | 本项目的建造者；也是 packet 模式下最好用的"研究员" |
| **Kimi / GLM / DeepSeek API** | 国内模型；Kimi 与智谱自带联网搜索 | 中文招聘语境的研究主力 | 需要跨来源引用严格时要盯着校验 | 研究阶段的默认模型（第 4 节） |
| **Claude API + tool use / Tool Runner** | 你写工具函数，SDK 帮你跑"模型调用 → 执行工具 → 再调用"的循环 | 自定义工具的自主 agent（如：自主搜索 20 家公司） | 只想调一次模型的场景（杀鸡用牛刀） | 进阶：把 research 阶段升级成自主搜索 agent（第 10 节） |
| **Claude Agent SDK** | 把 Claude Code 打包成库（自带读写文件/终端/搜索工具） | 想在自己的服务器上跑一个"像 Claude Code 的 agent" | 简单流水线 | 备选，不急 |
| **Managed Agents（Anthropic 托管）** | Anthropic 帮你跑循环 + 沙箱，可定时 | "每晚自动扫一遍市场" | 数据必须留本地时 | 以后想全自动时再看 |
| **LangGraph 等编排框架** | 状态图式编排 | 分支复杂、需要回滚/人审的多步流程 | 我们这种线性流水线 | 不用 |

**结论**：
1. 现在（Pilot）：**Python CLI（本仓库）+ Claude Code 当操作员 + 国内模型 API（Kimi / 智谱自带联网，DeepSeek 做分类）**。零框架、零平台，每一行都是你的。
2. 三个月后：如果每天都在用，加一个飞书 bot 或 Dify 前端只是"壳"，核心不变。
3. 需要自动化研究时：把 `research` 阶段换成 Claude 的 `web_search` 工具或 Tool Runner 循环（第 10 节），其他阶段不动。

一句话：**先把流程做对，再谈载体。载体是最后才需要决定的事。**

---

## 1. Agent 到底是什么

```
Agent = 模型（判断） + 工具（行动） + 循环（多步） + 状态（记忆）
```

自主程度是一条光谱：

```
单次调用 ──── 工作流（代码控制流程，模型做每一步判断）──── 自主 Agent（模型决定下一步做什么）
   便宜、稳定、可测                                            灵活、贵、难调、容易跑偏
```

这个项目 90% 是**工作流**：11 个步骤的顺序由代码写死（`cli.py: run-all`），模型只在 8 个明确的判断点出现（`schemas.py: BY_TASK`）。

为什么不做成"一个 Agent 自己搞定一切"？四个判断标准（来自 Anthropic 的 agent 设计指南）：
- **复杂度**：任务能不能事先说清楚？求职流程能。→ 工作流。
- **价值**：结果值不值得多花 10 倍 token？作战卡值，但流程本身不需要模型来"发明"。
- **可行性**：模型擅长吗？分类、综合、写文案擅长；"记住上周联系过谁"不擅长 → 交给数据库。
- **错误代价**：私信发错人、判断错团队的代价很高 → 每一步都要能被人检查（所以有 packet、有作战卡、有"系统起草、人来发送"）。

---

## 2. 三层分离：记账层 / 判断层 / 呈现层

```
config/*.yaml ─┐
               ▼
      ┌──────────────┐    prompt+schema    ┌──────────────┐
      │   判断层      │◄──────────────────►│  模型/搜索    │  llm/, search.py
      │ (stages/*)   │    JSON+校验         └──────────────┘
      └──────┬───────┘
             │ 只写"特征 + 证据"
             ▼
      ┌──────────────┐
      │   记账层      │  db.py（SQLite）：公司/团队/岗位/信号/人物/机会/触点/任务/作品/调用记录
      └──────┬───────┘
             │ 确定性计算：评分、状态机、排期
             ▼
      ┌──────────────┐
      │   呈现层      │  templates/ + render.py：作战卡、日报、触达文案
      └──────────────┘
```

三条铁律：
1. **模型的输出先过 schema，再进数据库**（`router.call` → `schemas.validate`）。模型说"这个团队在做 Agent"，数据库里存的是 `direction=agent, confidence=0.55, signals=[...url...]`。
2. **数据库里的每条判断都带来源**：`signals.url`、`people.evidence`、`jobs.url`。没有 URL 的信号不入库（`research.ingest_research`）。
3. **分数和日程由代码算**（`rank.compute_score`、`crm.log_touch`）。你随时可以解释"为什么这家是 A2"，也可以改 `scoring.yaml` 重算。

---

## 3. 一次模型调用的解剖（`llm/router.py: Router.call`）

```
1. 选 provider     models.yaml 的 routing[task] → 有 key 就用，没有就按 fallback_order 降级，最后 mock
2. 组 prompt       prompts.py：身份与边界 + 输入材料 + 输出用途；router 再追加 JSON Schema
3. 调模型          providers.py：Claude 用 output_config.format 强约束 JSON；国内模型用 json_object 模式
4. 抠 JSON         extract_json：容忍 ``` 围栏和废话
5. 温和修正 + 校验  coerce（7.0→7、越界夹到边界）→ validate（类型/枚举/必填/多余字段）
6. 失败重试一次     把校验错误原样喂回去："上一次输出未通过校验：$.people[0].role_type 值 'HR' 不在枚举..."
7. 记账            runs 表：provider、model、tokens、耗时、是否成功
```

每个任务都有四件套：**prompt（prompts.py）、schema（schemas.py）、mock（mock.py）、ingest（stages/*.py）**。加一个新任务就是加这四样。

一个细节：Claude 走 `output_config.format` 时 JSON 是**语法保证**的；国内模型的 `json_object` 只保证是合法 JSON，不保证字段对，所以 schema 校验 + 重试是必须的，不是锦上添花。

---

## 4. 模型分工怎么定

研究类任务全部交给国内模型，并用它们**自带的联网搜索**，这是 2026-09 的分工表（`config/models.yaml`）：

| 任务 | 需要什么能力 | 首选 | 联网 | 为什么 |
|---|---|---|---|---|
| title_expand 岗位叫法扩展 | 中文招聘黑话、平台命名习惯 | Kimi K3 | — | 国内语料密度高 |
| company_enrich 公司/团队假设 | 国内公司组织常识 | GLM-5.3 | — | 国内语境好，可顺手联网 |
| jd_classify 批量打标签 | 便宜、快、JSON 稳定 | DeepSeek | — | 50 条 JD 几分钱 |
| team_research 团队画像 | 跨来源综合、不编造、带引用 | Kimi K3 | `$web_search` 内置工具 | 模型自己决定搜什么，服务端执行 |
| people_assess 人物价值 | 判断力 + 分寸感 | GLM-5.3 | `web_search` 工具 | 可查证公开分享 |
| fit_assess 经历重叠 | 读懂你的档案、保守评估 | DeepSeek | — | 宁可低估 |
| outreach_write 私信 | 中文语感 + 克制 | Kimi K3 | — | 想用 Claude 写：routing 改成 anthropic |
| card_write 作战卡叙述 | 压缩、可执行 | Kimi K3 | — | 同上 |

两家的联网接口形状不同，`providers.py` 各做了一种：
- **Kimi**：声明 `{"type": "builtin_function", "function": {"name": "$web_search"}}`；模型发出 tool_call 后，客户端把 `arguments` 原样作为 tool 结果回传，搜索在 Moonshot 服务端执行；循环直到 `finish_reason != "tool_calls"`。
- **智谱**：`{"type": "web_search", "web_search": {"enable": true, "search_engine": "search_pro", "search_result": true}}`，一次调用；结果在响应的 `web_search` 字段，链接收进 citations。智谱另有独立的 Web Search API（`PF_SEARCH_PROVIDER=zhipu`），可以给任何模型喂证据。

模型 ID 会变（kimi-k2.5 与 moonshot-v1 已在 2026-08-31 下线，旗舰是 kimi-k3；智谱旗舰 glm-5.3，免费的 glm-4.7-flash 也能跑），配置里有注释，**以官网模型列表为准**。这两段接口按各家公开文档实现，并有假客户端的单元测试覆盖循环与解析，但本仓库没有拿真实 key 跑过：第一次接入请用 `pf research --company 某一家 -v` 跑单家验证。

成本量级（Pilot 一轮，粗估）：国内模型 ~150 次调用，几块到十几块人民币；联网搜索按各家计费另算。**一轮 Pilot 的模型成本低于一顿饭**，所以不要为了省钱降级模型。

想换模型：只改 `config/models.yaml`。想加一个 provider（比如豆包）：在 `providers:` 下加一段 `kind: openai_compat` 的配置即可。

---

## 5. 工具与证据规则

这个系统只有一种"工具"：**搜索**。研究阶段拿证据有四条路（`PF_SEARCH_PROVIDER`）：

| 模式 | 怎么工作 | 什么时候用 |
|---|---|---|
| `native`（推荐） | 研究模型用自己的联网工具边搜边写：Kimi `$web_search` / 智谱 `web_search` / Claude `web_search` | 有 Kimi 或智谱 key |
| `zhipu` / `bocha` / `tavily` / `serper` | 先用搜索 API 拿证据，再把结果贴给模型综合 | 想让不会联网的模型（DeepSeek）也能研究 |
| `none` | 不搜；`discover` 输出查询清单，`research` 导出 packet | 没有 key；或你想亲自看 |
| packet（贯穿所有模式） | 把 prompt + schema 打成 Markdown，交给 Claude Code / Kimi 网页版去做，再 `pf packet ingest` | 零 key 跑 Pilot；或某一家想人工深挖 |

**证据规则**（`research.py`）：
- 模型不能联网、也没有搜索 API、又不是 mock 时，`research` **拒绝调用模型**，改为导出 packet。原因：让模型"凭印象"写团队近况，得到的是看起来对的错话。
- 每条 signal 必须有 URL；`team.verified=1` 只在"有真实 URL 且置信度 ≥ 0.6"时成立；未验证的团队在评分里方向分 ×0.7。
- 模型联网时看过的页面（citations）会存进团队研究的 `sources`，作战卡"证据"一节会列出。

---

## 6. 人在回路的边界

- **系统起草，人来发送。** 没有任何自动发消息的代码，也不会有。发完你记一笔（`pf crm touch`），系统负责记住、排期、提醒。
- **只记录公开的职业信息**（职位、公开分享、公开主页链接）。不抓取、不存手机号，不建"黑名单"。`data/` 已在 `.gitignore` 里，永远不要提交。
- 平台规则：脉脉/LinkedIn 的免费私信额度和频率限制，是**保护你**的（一天发 30 条模板消息，账号和名声都会受伤）。日报每天只给你 3–5 个动作，是故意的。

---

## 7. 可观测与评估：怎么知道它在变好

看三张表：
- `runs`：每次模型调用的成本和成功率。schema 失败率高 → prompt 或 schema 要改。
- `queries`：搜过什么、命中几条。命中为 0 的查询模式要换。
- 漏斗（`crm.metrics`）：识别 → 研究 → 找到人 → 已联系 → 回复 → 对话 → 内推 → 面试。

**北极星指标只有一个：回复率**（replied / contacted）。它同时检验了"找对团队、找对人、说对话"三件事。Pilot 目标 ≥ 20%。

两个便宜的评估：
1. **JD 分类金标准**：手工标 10 条 JD 的类别和 role_match，跑 `jd_classify` 对比。换模型、改 prompt 后重跑，5 分钟。
2. **评分校准**：每周把 Top 10 的排序和你的直觉比一遍；不一致的那几个，问自己是特征错了（模型）还是权重错了（配置）。

---

## 8. 迭代顺序：配置 > prompt > 代码

大部分"系统不对劲"都能在配置层解决：
- 排序不对 → `scoring.yaml` 权重 / `seeds.yaml` 的 `screen_boost`
- 岗位漏掉 → `taxonomy.yaml` 加叫法
- 文案不像你 → `profile.yaml` 写具体（数字、项目名）
- 判断质量差 → `prompts.py`（先加约束和例子，再考虑换模型）
- 流程缺一步 → `stages/` 加文件 + `cli.py` 加命令

每周复盘 15 分钟：`pf status` → `pf brief` → 看 `runs` 里失败的调用 → 改一处配置。

---

## 9. 三个练习（建议按顺序做）

1. **加一个 provider**：在 `models.yaml` 加豆包（火山方舟的 OpenAI 兼容接口），把 `jd_classify` 路由过去，跑 `pf discover --company 阿里云`，看 `runs` 表。
2. **加一个评分维度**："团队规模是否适合新人"（小团队 = 能接触 HM，大团队 = 流程正规）。改 `scoring.yaml` 加权重，在 `rank.compute_score` 里加一项，作战卡自动多一行。
3. **加一个阶段**：`interview_prep`——从作战卡 + 团队信号生成一页面试准备（他们最近的产品、可能问的问题、你的三个故事）。四件套：prompt、schema、mock、ingest，再在 `cli.py` 加命令。

做完这三个，你就不再是"用 Agent 的人"，而是"能设计 Agent 的人"。这也是面 AI 解决方案岗时最硬的故事：**我用一个自己设计的 Agent 系统找到了这份工作。**

---

## 10. 进阶：把 research 升级成自主搜索 Agent

什么时候值得：当你每周要研究 20 家以上公司、且搜索 API 已经配好时。

方案 A（最省事，已实现）：`PF_SEARCH_PROVIDER=native`。Kimi 用内置 `$web_search` 循环，智谱用 `web_search` 工具，Claude 用服务端 `web_search_20260209`；引用自动收集进 `sources`。只差一个 key。

方案 B（完全自定义）：用 Anthropic SDK 的 Tool Runner，把 `search.py` 的 `search()` 和 `db.py` 的写入函数暴露成工具，让模型决定搜什么、搜几次、什么时候停。适合加入"读官网招聘页"之类的自定义工具。代价：不可复现、更贵、要加护栏（最大步数、域名白名单）。

方案 C（托管定时）：Managed Agents 每晚跑一遍市场扫描，把结果写回。适合你上班后没时间盯着的时候。

不管哪种，**记账层不变**：模型再自主，写进数据库的仍然是过了 schema 的特征 + 证据。这就是分层的价值。
