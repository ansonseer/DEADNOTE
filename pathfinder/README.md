# pathfinder — 中国 AI 求职情报 + 人脉路径 + 内推 + CRM

> 把求职从「我把简历发出去，看谁要我」变成「我先研究市场 → 找到最匹配的业务问题 → 找到拥有这个问题的人 → 用我的经历证明我能解决 → 再进入招聘流程」。
> 这也是 Forward-Deployed 工作方式本身：不是等需求，而是主动找到需求、找到 owner，然后切进去。

目标岗位：AI 售前 / AI 解决方案工程师 / 大模型解决方案工程师（核心）、AI 应用 / Agent 工程师、技术型管培 / 校招 / 0–3 年 AI 岗。

## 它解决的五个问题

| 问题 | 系统怎么做 | 在哪 |
|---|---|---|
| 哪些公司和团队真的适合你 | 26 家种子公司、按 BU / 团队假设研究，不看公司名看团队 | `config/seeds.yaml` → `pf scan` |
| 他们实际上在招什么 | 岗位语义词典 + 国内模型扩展叫法 + JD 打标签 | `config/taxonomy.yaml` → `pf discover` |
| 为什么他们现在需要这种人 | 带证据的团队研究：新闻 / 分享 / 产品动态 / 招聘信号，每条带 URL | `pf research` |
| 谁是最值得联系的人 | 角色优先级 + 人脉路径阶梯（普通内推 → Warm Referral → HM 推荐 → Sponsor） | `pf people` |
| 怎么把联系变成面试 | 第一条不提内推；follow-up 给价值；状态机 + 节奏 + 日报 | `pf outreach` / `pf crm` / `pf brief` |

最终你每天看到的不是一堆职位，而是 Top 10 **作战卡**：公司、BU / Team、岗位、为什么适合你、团队最近在做什么、谁最值得联系、为什么、第一条私信、能不能走内推、内推强度、下一步。

## 30 秒看效果

```bash
cd pathfinder
pip install -e .
pf demo --reset      # 虚构示例 + mock 模型：跑完 11 步，打印日报和第一张作战卡
cp .env.example .env # 填入 Kimi / 智谱 / DeepSeek 的 key
pf doctor --search   # 体检：key、模型名、JSON 调用、联网搜索
```

## 架构一句话

**模型做判断，代码做记账。** 8 个模型任务（每个都有 prompt / JSON schema / 校验 / mock），11 步流水线由代码编排，评分和跟进节奏是确定性的、可解释的、改配置就能调。研究主力是国内模型：Kimi K3 用内置 `$web_search` 联网做团队研究，GLM-5.3 用 `web_search` 工具做公司与人物判断，DeepSeek 做批量分类；Claude 是可选的写作备选；Claude Code 负责搭建和当"研究员"。没有 API key 也能通过 packet 模式跑完整个 Pilot。

```
config/*.yaml ──► stages/（scan → discover → research → people → rank → outreach → cards → brief）
                     │ prompt + schema                       ▲ 确定性评分 / 状态机
                     ▼                                       │
               llm/router ──► Kimi K3 / GLM-5.3 / DeepSeek / Claude(可选) / mock ──► SQLite（db.py）──► Markdown（templates/）
```

## 文档

| 文件 | 内容 |
|---|---|
| [docs/00-manual](docs/00-manual.md) | 11 步 ↔ 命令、三种运行模式、第一次真正使用 |
| [docs/01-agent-design-course](docs/01-agent-design-course.md) | **Coze / Dify / Cursor / Claude Code / SDK 怎么选**；Agent 的解剖；三层分离；模型分工；证据规则；评估；三个练习 |
| [docs/02-scoring](docs/02-scoring.md) | Fit Score 公式、A1/A2/B/C、路径阶梯、怎么校准 |
| [docs/03-people-and-paths](docs/03-people-and-paths.md) | 找谁、去哪找、路径怎么升级、节奏、人脉账户、边界 |
| [docs/04-outreach](docs/04-outreach.md) | 第一条私信、四种开场、follow-up、转岗位、渠道差异 |
| [docs/05-pilot-runbook](docs/05-pilot-runbook.md) | 20 → 50 → 30 → 10 的逐日计划与判断标准 |
| [docs/06-long-term-strategy](docs/06-long-term-strategy.md) | 2026–2028 时间线、三条线并行、回澳三路径、OPC 雏形、人脉资产、内容飞轮 |
| [docs/07-architecture](docs/07-architecture.md) | 三层分离、模型调用解剖、证据规则、数据模型、CRM 状态机（mermaid） |

## 原则

- **没有证据来源的研究不做**：研究阶段要么带搜索，要么导出 packet；没有 URL 的信号不入库。
- **系统起草，人来发送**：不自动发任何消息；只记录公开职业信息；`data/` 永不提交。
- **改配置，不改代码**：权重、词典、种子、模型分工都在 `config/`。

## 测试

```bash
pip install -e ".[dev]" && pytest -q
```
