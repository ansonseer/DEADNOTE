# AI-Native 建造者手册：12 小时飞行版

> 这本手册只训练一件事：**判断力**。
> 不是教你手写代码，而是教你在 AI 交付的东西面前知道对不对、出了问题知道在哪一层、以及怎么用最便宜的方式确认。

31 章，正文约 25 万中文字。每章固定结构：为什么重要 → 核心机制 → AI 最常犯的错与怎么识别 → 判断清单 → 飞机上的练习（无网络可做，附评判标准）→ 落地后的练习 → 一句话记忆钩子。

## 怎么用

- **飞机上**：按下面的 12 小时节奏读，读完一章合上书复述"核心机制"和"三种典型坏法"。累了做练习，不要硬读。每两小时在纸上默画第 00 章的两张分层图。
- **落地后**：每章"落地后的练习"都是在 Claude Code 里把系统弄坏再修好。建 `judgment-log.md`（第 00 章）和 `verification.md`，从第一天开始记。
- **长期**：当"诊断清单库"反复翻。第 22 章（按层诊断）和第 30 章（操演集）是最常回来的两章。

## 12 小时阅读节奏（约 737 分钟，含练习与休息）

| 时段 | 章节 | 意图 |
|---|---|---|
| 0:00–2:00 | 00 → 01 → 02 → 03 | 装上坐标系；一段代码、一个请求、一个页面分别经过什么 |
| 2:00–4:00 | 04 → 05 → 06，+20 分钟练习 | 后端契约与数据库：生产环境怎么坏 |
| 4:00–5:30 | 07 → 08 → 09 | 系统怎么变快、怎么丢东西；工程闭环；安全 |
| 5:30–5:50 | 休息 | 睡一会儿或吃饭，不要带着疲劳读机制 |
| 5:50–7:50 | 10 → 11 → 13 → 14 | LLM 的机制与倾向；context；workflow vs agent |
| 7:50–10:15 | 15 → 16 → 17 → 18 → 19 | agent 怎么坏；RAG；微调蒸馏量化；harness；skills 边界 |
| 10:15–11:55 | 22 → 24 → 27 | 按层诊断总图；从公司背景合成架构；OPC + FDE + 自媒体飞轮 |
| 11:55–12:15 | 29，+写下落地后 30 天计划 | 把终极目的接回每天的选择 |

**落地后第一周补读**：12（推理与经济学）、20（多 agent）、21（evals）、23（FDE discovery）、25（案例推演集）、26（训练系统）、28（硬件/机器人/世界模型）、30（操演集 + 90 天 Lab）。
如果你更想在飞机上先读战略，把 10:15 之后的时段换成 23 → 24 → 27 → 28 → 29，把 22 留到落地后。

## 目录

| 章 | 标题 | 分钟 |
|---|---|---|
| **Part 0 · 总纲：判断力的操作系统** | | |
| 第 00 章 | [判断力是唯一的护城河：这本手册怎么用、分层诊断模型、验证三法](chapters/00-judgment-os.md) | 25 |
| **Part I · 机器的底座：AI-native 讲法的计算机基础** | | |
| 第 01 章 | [一段代码跑起来时到底发生了什么：process、memory、filesystem、shell、环境与依赖](chapters/01-machine-runtime.md) | 28 |
| 第 02 章 | [网络与 HTTP：一个请求的一生——状态码、超时、重试、幂等、CORS、流式](chapters/02-network-http.md) | 30 |
| 第 03 章 | [前端：浏览器是一台不可信的客户端——DOM、渲染、state、async、hydration](chapters/03-frontend.md) | 28 |
| 第 04 章 | [后端服务与 API：契约、边界、状态、并发与错误处理](chapters/04-backend-api.md) | 30 |
| 第 05 章 | [数据建模与数据库基础：关系模型、schema、索引、事务、ORM](chapters/05-database-basics.md) | 30 |
| 第 06 章 | [数据库在生产环境怎么坏：锁、慢查询、连接池、迁移、复制延迟、备份与恢复](chapters/06-database-production.md) | 40 |
| 第 07 章 | [缓存、队列、并发与分布式：系统怎么变快、怎么丢东西、怎么不一致](chapters/07-cache-queue-distributed.md) | 32 |
| 第 08 章 | [工程闭环与可观测性：git、测试、CI/CD、部署、日志与 trace——让 AI 的产出可验证、可回滚、可诊断](chapters/08-engineering-loop-observability.md) | 30 |
| 第 09 章 | [安全与身份：认证、授权、边界，以及 AI 时代的新攻击面](chapters/09-security.md) | 30 |
| **Part II · 模型：LLM 底层机制** | | |
| 第 10 章 | [LLM 底层 I：token、embedding、attention、KV cache、context window——从机制推出能力边界](chapters/10-llm-mechanics.md) | 32 |
| 第 11 章 | [LLM 底层 II：预训练、后训练、RLHF/RLVR 与 scaling——模型为什么会幻觉、谄媚、拒绝](chapters/11-llm-training.md) | 28 |
| 第 12 章 | [推理与经济学：sampling、latency、batching、prompt caching、structured output 与 tool calling 的机制](chapters/12-inference-economics.md) | 26 |
| **Part III · 把模型接到任务上** | | |
| 第 13 章 | [Context engineering：模型到底看到了什么、你怎么控制它看到什么](chapters/13-context-engineering.md) | 28 |
| 第 14 章 | [Workflow vs Agent：决策图、agent loop 的解剖、状态、终止条件与成本](chapters/14-workflow-vs-agent.md) | 30 |
| 第 15 章 | [Agent 失败模式图鉴：循环、目标漂移、假完成、工具误用、context 腐烂](chapters/15-agent-failure-modes.md) | 28 |
| 第 16 章 | [RAG：检索是一个系统问题，不是一个模型问题——全链路与失效方式](chapters/16-rag.md) | 30 |
| 第 17 章 | [微调、蒸馏与量化：三者的关系、机制与何时该做（大多数时候不该）](chapters/17-finetune-distill-quantize.md) | 28 |
| **Part IV · 设计 harness：从使用者到设计者** | | |
| 第 18 章 | [Harness 架构设计：system prompt、tools、permissions、hooks、memory、context 管理、沙箱、检查点与人类介入](chapters/18-harness-architecture.md) | 34 |
| 第 19 章 | [Skills 的边界判定：什么该是 skill、tool、prompt、代码还是模型](chapters/19-skills-boundaries.md) | 26 |
| 第 20 章 | [多 agent 编排：subagents、context 隔离、任务分解与协调失败](chapters/20-multi-agent.md) | 22 |
| 第 21 章 | [Evals 与可观测性：没有 eval 的 AI 应用只是在赌，没有 trace 的 agent 无法诊断](chapters/21-evals-observability.md) | 28 |
| 第 22 章 | [按层诊断：AI / agent 出问题时的排查总图、案例集与"何时换层"的判据](chapters/22-layered-diagnosis.md) | 34 |
| **Part V · FDE：根据公司背景整合出最合适的架构** | | |
| 第 23 章 | [读一家公司：业务、数据、权力、痛点——FDE 的 discovery 与诊断](chapters/23-fde-discovery.md) | 32 |
| 第 24 章 | [设计合成：buy/build、架构适配、最小可落地系统、成功指标与真正落地](chapters/24-fde-design-synthesis.md) | 36 |
| 第 25 章 | [案例推演集：四家公司从 discovery 到落地完整走一遍](chapters/25-fde-cases.md) | 36 |
| **Part VI · 长线战略与操演** | | |
| 第 26 章 | [判断力的训练系统：刻意练习、复盘、决策日志——把知识变成判断力](chapters/26-training-system.md) | 26 |
| 第 27 章 | [OPC + FDE + 自媒体：三条线互相喂养的飞轮与前 24 个月路线](chapters/27-opc-fde-media.md) | 30 |
| 第 28 章 | [通往硬件、机器人与世界模型：哪些能力迁移、哪些必须重学、现在就该铺的基础](chapters/28-hardware-robotics-world-models.md) | 30 |
| 第 29 章 | [哲学与路线：解放与集中人类思想——把终极目的接到每天的技术选择上](chapters/29-philosophy-and-route.md) | 18 |
| 第 30 章 | [操演集：纸上推演案例 + 90 天落地 Lab](chapters/30-drills-and-lab.md) | 40 |

## 离线格式

```bash
cd ai-native-handbook
python3 build.py          # -> dist/ai-native-handbook.html（单文件，手机/平板浏览器可离线打开）
python3 build.py --pdf    # 另生成 dist/ai-native-handbook.pdf（需要本机有 Chromium）
python3 count.py chapters/*.md   # 各章中文字数（不含代码块）
```

`dist/` 里的 HTML 与 PDF 已随仓库提交，上飞机前把它们存到手机里即可。

## 这本手册怎么来的

先由三位不同视角的课程设计者（系统架构、LLM/agent 研究、FDE/OPC 运营）独立设计大纲，合并成 31 章的蓝图；每章由一位作者依据合并后的简报写成，再由一位编辑做技术准确性与读者适配两路审稿并直接修订。写作规范见 `STYLE.md`，章节简报的合并结果体现在各章的"核心机制"与"AI 最常犯的错"里。

它是一份起点，不是终点。哪一章读起来不对，就用第 00 章的三个反问去质疑它：它凭什么知道？它怎么证明的？如果它错了，我怎么发现？
