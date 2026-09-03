# 02 · 评分规则与优先级

所有分数由 `pathfinder/stages/rank.py: compute_score` 按 `config/scoring.yaml` 计算。模型不打总分，只给特征。

## Fit Score（0–100）

| 维度 | 满分 | 算法 | 特征来自 |
|---|---|---|---|
| role_match 岗位贴合 | 30 | `role_match/10 × 类别优先级` | jd_classify（无岗位时按团队方向估 5 或 3） |
| team_direction 团队方向 | 20 | `方向系数 × (已验证 1.0 / 未验证 0.7)` | team_research |
| experience_overlap 经历重叠 | 20 | `overlap/10` | fit_assess（读你的 profile.yaml） |
| feasibility 进入可行性 | 15 | `0.7 × 资历可行/10 + 0.3 × 城市系数` | jd_classify + profile 的城市偏好 |
| path 人脉路径 | 15 | `0.6 × 当前等级系数 + 0.4 × 可达等级系数` | people 表的 path_level + people_assess 的潜力 |
| 加分 | +7 | 中澳双足迹 +3、30 天内新信号 +2、已有针对该团队的作品 +2 | companies / signals / assets |

方向系数：agent 1.0、enterprise_ai 1.0、industry_delivery 0.9、platform 0.8、consumer 0.4、model_research 0.2、unknown 0.5。
路径系数（L0–L5）：0 / 0.3 / 0.5 / 0.7 / 0.85 / 1.0。

## 优先级分层

| 层 | 分数 | 含义 | 日报里的待遇 |
|---|---|---|---|
| A1 | ≥ 85 | 团队方向对、岗位对、有人可联系、路径能升级 | 今天就发 |
| A2 | 75–84 | 差一个条件（多半是还没找到对的人） | 本周补齐条件 |
| B | 60–74 | 值得跟，但不急 | 有余力再做 |
| C | < 60 | 记录在案 | 不投入 |

## 人脉路径阶梯（path_level）

| 等级 | 名称 | 达成条件（crm.log_touch 自动推进） |
|---|---|---|
| L0 | 无渠道 | 只知道名字 |
| L1 | 冷联系 | 有可触达的渠道 |
| L2 | 普通内推 | 对方回复过（任何员工都能帮你走系统内推） |
| L3 | Warm Referral | 通过电话/会议聊过，对方愿意推荐 |
| L4 | HM 推荐 | 聊过的人本身是 hiring manager / team lead |
| L5 | Sponsor | HM 主动推动你的流程（`--kind referral` 且角色是 HM） |

评分同时看"当前"和"可达"（0.6 : 0.4），所以刚录入的人只要角色对、就已经贡献分数；随着关系推进分数继续涨。

## 一个例子（demo 里的 Top 1）

```
role_match        27.0/30   贴合 9/10 × 类别优先级 1.0
team_direction    14.0/20   agent 1.0 × 未验证 0.7
experience_overlap 16.0/20  8/10
feasibility        9.7/15   资历 5/10；城市 上海 1.0
path               7.8/15   当前 L1 → 可达 L4
bonuses            2/7      fresh_signal
总分              76.5 → A2
```
把团队验证掉（research 拿到真实 URL、置信度 ≥ 0.6），方向分从 14 → 20，直接进 A1。这就是为什么"先研究、再触达"。

## 怎么校准

1. 每周把 Top 10 的顺序和直觉比一遍。不一致的，先看 `pf show <id>` 的 `breakdown.features`：是特征错（模型判断）还是权重错（配置）。
2. 特征错 → 改 prompt 或换模型；权重错 → 改 `scoring.yaml`，`pf rank` 重算，不需要重新调模型。
3. 别追求"完美分数"。分数的作用是**排序**和**解释**，不是预测。
