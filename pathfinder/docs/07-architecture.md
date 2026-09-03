# 07 · 架构

> 一句话：模型做判断，代码做记账；系统起草，人来发送。

## 三层分离

```mermaid
flowchart LR
  CFG[config/*.yaml<br/>profile · scoring · taxonomy · seeds · sources · models] --> J
  subgraph J[判断层 stages/]
    direction LR
    scan --> discover --> research --> people --> rank --> outreach --> cards --> brief
  end
  J -- "prompt + schema" --> M[模型 llm/router<br/>Kimi K3 · GLM-5.3 · DeepSeek · Claude(可选) · mock]
  M -- "JSON（校验后）" --> J
  J -- "特征 + 证据（带 URL）" --> DB[(记账层 db.py · SQLite)]
  DB -- "确定性评分 · 状态机 · 排期" --> P[呈现层 templates/<br/>作战卡 · 日报 · 触达文案]
  P -- 起草 --> H((你))
  H -- "pf crm touch / people add / packet ingest" --> DB
```

## 一次模型调用（router.call）

```mermaid
flowchart LR
  A[1 选 provider<br/>routing → 有 key → mock] --> B[2 组 prompt<br/>身份·材料·用途 + schema] --> C[3 调模型<br/>可带联网工具] --> D[4 抠 JSON] --> E[5 修正 + 校验] --> F[6 入库 ingest] --> G[(runs 表)]
  E -- "校验失败：把错误喂回去，重试 1 次" --> C
```

## 证据规则

```mermaid
flowchart TD
  S[pf research 一家公司] --> Q1{模型能联网？<br/>PF_SEARCH_PROVIDER=native}
  Q1 -- 是 --> N[模型边搜边写<br/>Kimi $web_search · GLM web_search · Claude web_search]
  Q1 -- 否 --> Q2{有搜索 API？<br/>zhipu · bocha · tavily}
  Q2 -- 是 --> E[先搜证据，再喂给模型]
  Q2 -- 否 --> P[导出 packet → 你 / Claude Code 完成 → pf packet ingest]
  N --> G{{证据门：无 URL 的信号丢弃；置信度 ≥ 0.6 才 verified}}
  E --> G
  P --> G
  G --> DB[(teams · signals)]
```

## 数据模型

```mermaid
erDiagram
  companies ||--o{ teams : has
  companies ||--o{ jobs : has
  companies ||--o{ people : has
  teams ||--o{ signals : has
  teams ||--o{ people : "belongs to"
  companies ||--o{ opportunities : ""
  teams ||--o{ opportunities : ""
  jobs |o--o{ opportunities : "job 可空"
  people |o--o{ opportunities : "首选联系人"
  opportunities ||--o{ touchpoints : ""
  opportunities ||--o{ tasks : ""
  people ||--o{ touchpoints : ""
  companies ||--o{ assets : "公开作品"
```

## CRM 状态机

```mermaid
stateDiagram-v2
  direction LR
  [*] --> identified
  identified --> researched : research 验证团队
  researched --> people_found : people assess
  people_found --> outreach_drafted : pf outreach
  outreach_drafted --> contacted : first_msg（+60h follow-up 1）
  contacted --> replied : reply（取消 follow-up，+24h 推进）
  contacted --> parked : 2 次 follow-up 无回复
  replied --> in_conversation : call / meeting（+24h 感谢 + 价值）
  in_conversation --> referral_requested : ask（+5d 确认）
  referral_requested --> referred : referral
  referred --> applied
  applied --> interviewing
  interviewing --> offer
  offer --> closed_won
```

人物关系与路径等级：`cold/contacted L1 → replied L2 → warm L3（HM 则 L4）→ advocate L5（HM）`。

## 模型分工（2026-09）

| 任务 | provider | 联网 |
|---|---|---|
| title_expand | kimi · kimi-k3 | — |
| company_enrich | zhipu · glm-5.3 | — |
| jd_classify | deepseek · deepseek-chat | — |
| team_research | kimi · kimi-k3 | $web_search 内置工具 |
| people_assess | zhipu · glm-5.3 | web_search 工具 |
| fit_assess | deepseek · deepseek-chat | — |
| outreach_write / card_write | kimi（可改 anthropic） | — |

降级顺序 kimi → zhipu → deepseek → qwen → anthropic → mock。模型 ID 以各家官网为准。
