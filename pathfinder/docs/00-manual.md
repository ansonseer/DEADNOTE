# 00 · 总览与操作手册

## 这是什么

一个把求职从「海投 → 等 HR 捞」改成「研究市场 → 找到问题的 owner → 用作品证明 → 再进流程」的系统。
它同时是三样东西：**情报系统**（哪些团队真的适合你、他们在做什么）、**人脉路径系统**（谁值得联系、怎么从普通内推升级到 HM 推荐）、**CRM**（记住每一次触达，告诉你今天做什么）。

## Workflow ↔ 命令

| # | 步骤 | 命令 | 谁做判断 | 产出 |
|---|---|---|---|---|
| 1 | 市场扫描 | `pf scan` | 代码（seeds.yaml） | companies 表 |
| 2 | 公司筛选 | `pf scan`（内含） | 代码（scoring.yaml/screen） | 20 家 pilot |
| 3 | 岗位发现 | `pf discover` / `pf jobs add` | Kimi 扩叫法；DeepSeek 打标签；搜索或你手动 | jobs 表 |
| 4 | 团队研究 | `pf research` | Kimi K3 联网（或 GLM） | teams + signals |
| 5 | 业务背景 | `pf research`（内含） | 同上 | why_they_need_this_role、hooks |
| 6 | 找人 | `pf people packet` → `pf people add` | **你**（脉脉/LinkedIn/会议/公众号） | people 表 |
| 7 | 判断人脉价值 | `pf people assess` | GLM-5.3 | 角色、hook、路径潜力、长期标签 |
| 8 | 评分排序 | `pf rank` / `pf top` | 代码（scoring.yaml） | opportunities + 优先级 |
| 9 | 个性化触达 | `pf outreach <id>` | Kimi（可改 Claude） | 第一条私信 + 2 次 follow-up + 转岗位话术 |
| 10 | 作战卡 | `pf cards` | Kimi 写叙述，代码拼卡 | data/cards/*.md |
| 11 | 跟进 / 内推 / 面试 | `pf crm touch` / `pf crm stage` / `pf brief` | 代码（状态机 + 节奏） | 日报、待办 |

一键：`pf run-all` 按顺序跑 1–10（找人这步会导出清单等你录入）。

## 安装

```bash
cd pathfinder
pip install -e ".[llm,dev]"     # 只想离线跑 mock：pip install -e .
cp .env.example .env            # 填 key；不填也能跑 demo 和 packet 模式
pf demo --reset                 # 用虚构示例 + mock 模型跑一遍，看作战卡长什么样
```

## 第 0 步：体检

```bash
pf doctor            # key 是否配上、模型 ID 在平台上是否存在、能否返回合法 JSON
pf doctor --search   # 再测一次联网搜索（Kimi $web_search / 智谱 web_search）
```
任何一列打 ✗ 都先解决它再往下跑：缺 key 看 `.env`；模型不存在改 `config/models.yaml`；连接错误看网络代理。

## 三种运行模式

1. **mock**（`--mock` 或 `PF_MOCK=1`）：不调任何模型，用来看流程、写测试、演示。
2. **packet**（没有搜索 API / 想亲自研究）：`pf research --packet` 等命令把 prompt + schema 导出成 Markdown，你贴给 Claude Code 或 Kimi 网页版，把 JSON 填回 `.result.json`，`pf packet ingest 文件` 入库。**零 key 也能跑完 Pilot。**
3. **API**：填好 `.env`（Kimi + 智谱 + DeepSeek 三个 key 即可），`pf run-all`。`PF_SEARCH_PROVIDER=native` 时研究阶段由 Kimi / 智谱自己联网搜；`zhipu` 则用智谱 Web Search API 先搜再喂给模型。

## 第一次真正使用（不是 demo）

```bash
vim config/profile.yaml          # 把 TODO 换成你的真实项目、数字、约束。这是所有文案的弹药库。
pf init                          # 建库、载入 26 家种子公司、筛出 20 家 pilot
pf scan                          # 给 pilot 公司生成团队假设（或 --packet）
pf discover                      # 岗位叫法扩展；没配搜索会生成查询清单 data/packets/discover_checklist.md
pf jobs add --company 阿里云 --title "大模型解决方案架构师" --url ... --city 杭州 --jd-file jd.txt
pf discover --company 阿里云     # 给录入的岗位打标签
pf research --company 阿里云     # 团队研究（有搜索 / claude_web 时自动；否则导出 packet）
pf people packet --company 阿里云   # 找人清单：找谁、去哪找
pf people add --company 阿里云 --name 张三 --title "解决方案架构师" --team 百炼 --maimai URL --evidence "分享标题|URL|摘要"
pf people assess --company 阿里云
pf rank && pf top
pf outreach 3                    # 机会 #3 的文案
pf cards                         # Top 10 作战卡 → data/cards/
pf brief                         # 每天早上看这个
```

发了消息之后：

```bash
pf crm touch 5 --kind first_msg --channel maimai       # 系统会在 60h 后生成 follow-up 任务
pf crm touch 5 --kind reply --content "他回了，愿意聊"   # 关系→replied，路径→L2，取消 follow-up
pf crm touch 5 --kind meeting --channel wechat           # 关系→warm，团队负责人则路径→L4
pf crm touch 5 --kind value_given --content "发了评测对比"
pf crm touch 5 --kind ask --content "问 headcount"       # 阶段→referral_requested，5 天后提醒
pf crm stage 3 interviewing
pf crm asset --kind post --title "企业 Agent PoC 评测小结" --url ... --status published --company 阿里云
```

## 目录

```
pathfinder/
├── config/        六份配置：profile / scoring / taxonomy / seeds / sources / models（改这里，不改代码）
├── pathfinder/    代码：db（记账）、llm（判断）、stages（11 步）、crm（状态机）、cli
├── templates/     作战卡、日报、触达文案框架
├── examples/demo/ 虚构示例数据
├── tests/         端到端测试（mock）
├── docs/          你现在读的这些
└── data/          运行时数据（已 gitignore；永远不要提交）
```

## 常见问题

- **模型编造了团队/人名怎么办？** 不会入库没有 URL 的信号；人名只能由你录入。作战卡上"假设，待验证"的团队别拿去写私信。
- **国内模型和 Claude 必须都配吗？** 不必须。默认全部走国内模型；Claude 是可选的写作备选。缺哪个就按 `models.yaml` 的 `fallback_order` 降级，最后落到 mock 并在 `pf status` 里显示。
- **数据在哪？** `data/pathfinder.db`（SQLite，用任何工具都能打开）+ `data/cards`、`data/briefs`、`data/outreach`、`data/packets`。
