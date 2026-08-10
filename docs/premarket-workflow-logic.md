 # 打板工作流 · 盘前简报 —— 逻辑与功能说明

 > 2026-08-11 按代码现状梳理（非设计稿）。用途：作为「盘前简报 6 项观察」逐项修复的共识底稿。
 > 冲突时以代码与 `specs/` 为准。

 ---

 ## 1. 页面地图（入口与路由）

 | 路由 | 页面 | 职责 |
 |---|---|---|
 | `/workflow` | Workflow.tsx | 工作流首页：盘前/盘中/盘后三阶段卡 + 顶级日期选择器（S048，`?date=` 写 URL，子页同携） |
 | `/workflow/pre-market` | PreMarketBriefing.tsx | 盘前简报（本文主角），纵向五段流 |
 | `/candidates` | Candidates.tsx | 候选池主页：阈值面板 + 重跑漏斗 + R1/R2/R3 层卡 + 最终候选诊断卡 |
 | `/workflow/candidates/:code` | CandidateDetail.tsx | 个股诊断卡路由页（与简报抽屉共用 `CandidateDetailPanel`） |
 | `/workflow/topology` | Topology.tsx | 关系网 / 漏斗流程 / 连板梯队三视角 |

 盘前简报同时内嵌了候选池漏斗（R1/R2/R3）与个股诊断抽屉 —— 这是本次「卡片重复」观察的结构性原因（见 §8 P1）。

 ---

 ## 2. 盘前简报端到端数据流

 ```
 GET /api/workflow/pre-market?date=          （routers/workflow.py:237）
   ├─ 内存态 _cache（data_date==date 且 running/done/error）→ 直接返回
   ├─ 快照 <VR_DATA_DIR>/workflow/pre-market/<date>.json → done + from_snapshot=true（纯读盘）
   ├─ date==最近交易日 且无快照 → idle（前端自动 POST refresh 触发采集）
   └─ 其余 → no_snapshot（显式「补采该日数据」入口）

 POST /api/workflow/pre-market/refresh        （后台 asyncio.create_task）
   _collect():
     ① factor_registry.afetch_all(date)   并行两因子：
        - limitup_screener  → 基因打分 LS-1 打分 / LS-2 战法 / LS-3 仓位
        - candidate_funnel  → 直接注册 R1/R2/R3/SELF 四层（与 §3 同一 run_funnel）
     ② _fetch_market_emotion(date)        ← 当前恒返 {}（bug，见 §8 P2）
     ③ _build_funnel_layers(date)         run_funnel 全跑一遍 → 落快照 funnel_layers
     ④ _save_snapshot()                   按日落盘（历史不可变）
 ```

 前端 `status==="done"` 时纵向渲染五段：

 | 段 | 组件 | 数据 |
 |---|---|---|
 | ① 市场情绪 | 内联 GlassCard×2 | `briefing.market_emotion`（综合评分 + 情绪阶段；当前恒空） |
 | ② 涨停基因因子漏斗 | FactorSection×N | `briefing.factors[].layers`（含 candidate_funnel 的 R1/R2/R3/SELF） |
 | ③ 候选池漏斗 | CandidateFunnelEmbed → FunnelLayers | 快照路径用 `briefing.funnel_layers`；**live 路径另发 GET /api/workflow/funnel/layers（整段漏斗重跑一遍）** |
 | ④ 战法胜率对比 | WinRateComparePanel | `GET /api/strategy/backtest?lookback_days=60` + ② LS-2 passed 合成胜率 |
 | ⑤ 个股抽屉 | Sheet → CandidateDetailPanel | `GET /api/workflow/candidates/{code}/diagnosis` + 工作流状态卡 |

 ---

 ## 3. 候选池漏斗 R1/R2/R3/SELF（backend/candidate_funnel/funnel.py）

 `run_funnel(stage, date, cfg)` 串行三层 + 自选并行；任一层采集失败标 `data_status="未取得"` 不静默返空。

 | 层 | 名称 | 输入 | 过滤口径 | passed 携带 |
 |---|---|---|---|---|
 | R1 | 宽源 | `sources.gene.fetch_genes(date)`（涨停基因候选，含 gene_score）+ board_ladder | `classify_exclusion`（ST/退市等名称规则剔除） | code/name/gene_score |
 | R2 | 收敛 | R1 输出 | 换手 `turnover_pct >= eff.turnover_cold`（缺换手剔除）；北向 `abs(nb) >= northbound_abs_min`（默认 0 → 不命中；nb=None 保留） | 同 R1 |
 | R3 | 定稿 | R2 输出 | 竞价异动(`auction_open_pct` 非空) OR 公告催化 OR 概念联动；可选 `ann_types` 严格匹配 | + `matched_triggers[]` |
 | SELF | 自选/手动 | watchlist | 无过滤，并行汇入 | — |

 最终候选 = R3 输出 ∪ SELF，每只构建诊断卡（§6）。

 **阈值与情绪档**：`resolve_thresholds(cfg, phase)` —— phase 取自 sentiment_weather 的 `weather_state`（同步取不到则沿用基数）。生效阈值写入各层 `conditions` chips（换手冷/热档、量比线、成交额下限、数据阶段 offset、情绪档位）。阈值调整入口：`/candidates` 页 ThresholdPanel → `PUT /api/workflow/funnel/config`（内存 `_store`，不落盘）；单层重跑 `PUT /funnel/layers/{id}/rerun`（实现=整段重跑只返目标层）。

 **性能现状**：`GET /api/workflow/funnel/layers`、`GET /candidates`、`GET /candidates/{code}/diagnosis`、`POST /candidates/funnel` 每次调用都整段 `run_funnel`（六类外部源采集），仅 60s `cache_response` 兜底。简报 live done 时前端 §2-③ 会再打一次该接口 → 与采集时 ③ 的 `_build_funnel_layers` 重复劳动（§8 P1/P6）。

 ---

 ## 4. 基因因子漏斗 LS-1/2/3（factors/limitup_screener_factor.py）

 与候选池漏斗**并行的另一套漏斗**，口径来自涨停基因选股器（GeneScreener 同源）：

 | 层 | 语义 | passed 携带 |
 |---|---|---|
 | LS-1 打分 | 基因总分 ≥ GENE_QUALIFY_THRESHOLD（现 50） | gene_score |
 | LS-2 战法 | limitup_strategy 8 大战法匹配 | best_strategy / confidence_value（合成胜率原料） |
 | LS-3 仓位 | PositionAdvisor 仓位建议 | suggested_pct / matched_strategy |

 L2 战法层在简报里挂 StrategyFilter 多选 chips 纯前端反筛（S031 R14）。
 阈值三件套：`GENE_QUALIFY_THRESHOLD=50` / `GENE_HIGH_THRESHOLD=60` / 手动覆盖 `POST /api/limitup/screener/params`（Settings 页）。

 ---

 ## 5. 战法胜率对比（WinRateComparePanel）

 - 左列真实回测：`GET /api/strategy/backtest?lookback_days=60` → 8 战法各自 win_rate / avg_return / sample_size / available_days（12h 后端缓存）。
 - 右列合成估算：LS-2 passed 的 confidence_value 代入 `min(c*0.8+0.2, 0.95)`（limitup_strategy.py:685 同式）按战法取均值，标注「估算」。
 - 现状：纯平表，无展开；当日命中各战法的标的（l2Passed 已携 best_strategy）未在面板内呈现。

 ---

 ## 6. 个股诊断抽屉（CandidateDetailPanel + diagnosis 管线）

 `GET /api/workflow/candidates/{code}/diagnosis?date=` → `funnel.diagnose()`：为单只股票重拉六类源（genes 全量 / board_ladder / activity / fund_flow / auction 全量 / catalyst）→ `build_indicator_set` → `build_diagnosis_card`。

 抽屉四块指标（IndicatorBlock 分组）：

 | 组 | 字段 | 现状 |
 |---|---|---|
 | 量价 | 换手率/量比/成交额/振幅 | activity 源正常 |
 | 情绪梯队 | 连板数/封板率/炸板率/晋级率 | **仅 consec_boards 有接线**（board_ladder lianban_stocks 按 code 匹配）；seal_rate/bomb_rate/advance_rate 在 build_indicator_set 中无赋值来源 → 恒 None（§8 P3） |
 | 资金流 | 主力净流入/5日累计/龙虎榜机构/北向 | 主力净流依赖 `push2his.eastmoney.com` fflow 接口——**本机网络对其连接被拒**（push2ex 正常），恒「资金流未取得」；北向 2024-08-19 后个股日级停更（结构性缺失）；新浪 MoneyFlow 接口实测可用（§8 P4） |
 | 风险标注 | risk_flags | 客观标注 |

 抽屉底部 = 工作流状态卡（§7）。**注意**：抽屉 `diagnosis(code)` 请求不带 date（仅状态卡用 date）→ 历史快照视角下抽屉展示的是最新 live 数据，与快照口径不一致（§8 P5）。

 ---

 ## 7. 工作流状态机（workflow_state_machine.py + routers/workflow.py）

 七态：`pending → candidate → watching → monitoring → holding → settled`，任意活跃态可 → `filtered`；`filtered/settled → candidate` 重入。

 - 盘前采集后自动落库 candidate/filtered（漏斗 passed→candidate，filtered_out→filtered）。
 - 手动流转仅抽屉状态卡一处 UI（`WorkflowStateCard`，渲染 `allowed_targets` 按钮；holding/settled 带表单）。
 - settled 流转即结算（S034：价齐写 winrate.db；S038 可拉市价预填卖出价）。
 - **无「回退/取消」转移**：watching 不能回 candidate，只能向前或转 filtered（标签「已过滤」）（§8 P7）。

 ---

 ## 8. 问题清单（用户 6 项观察 → 根因）

 | # | 观察 | 根因（已验证） | 位置 |
 |---|---|---|---|
 | P1 | R1/R2/R3 卡片重复，工作流与简报都涉及 | candidate_funnel 同时注册为 factor（段②渲染一遍）+ CandidateFunnelEmbed 段③再渲一遍；同一数据两份卡片 | PreMarketBriefing.tsx 段②/③ |
 | P2 | 表格中间大量空白 | FunnelLayerCard passed 行 `flex-1` 把短名与右侧得分拉开；卡片宽时中段留白 | FunnelLayerCard.tsx |
 | P3 | 为什么没有情绪梯队参数 | 双重缺失：a) 简报「市场情绪」段恒不渲染——`_fetch_market_emotion` 调 `market.get_overview(date)`（签名无参 → TypeError 被吞）且读 `sentiment_index/phase` 顶层键（实际在 `sentiment` 子对象里），快照实测 `market_emotion={}`；b) 梯队参数（连板梯队/最高连板/炸板率/封板率/晋级率/涨跌停家数，`market._emotion(date)` 已有全量聚合）从未接入简报；c) 抽屉情绪梯队组 seal/bomb/advance_rate 无接线 | routers/workflow.py:162、market.py、diagnosis.py |
 | P4 | 无资金流 | 主力净流唯一源 push2his.eastmoney.com 在本机网络被拒连（curl 实测 000；镜像主机同）；北向结构性停更；龙虎榜仅上榜才有 → 抽屉资金流组基本全「未取得」。新浪 MoneyFlow 实测可用（netamount/r0_net） | data/sources/eastmoney.py:272、fund_flow.py |
 | P5 | 展开个股详情，数据不准 | 抽屉 diagnosis 不带 date（历史视角串数据）；且 diagnosis 为 live 重拉，与快照漏斗数值可能不一致（取数时点不同） | CandidateDetail.tsx useEffect |
 | P6 | 漏斗性能/冗余 | live done 时前端另发 GET funnel/layers → run_funnel 整段重跑（采集时已建过 funnel_layers）；诊断卡每次全源重拉仅 60s 缓存 | candidates.py:66、PreMarketBriefing.tsx |
 | P7 | 工作流状态只有选中，没有取消 | 状态机无前向回退边（watching→candidate 不存在），唯一退出是 filtered（语义「已过滤」≠「取消」）；UI 无撤销入口 | workflow_state_machine.py:24 |
 | P8 | 战法胜率对比无展开、无当日命中标的 | WinRateComparePanel 纯平表；l2Passed（含 best_strategy）已传入但未用于行展开 | WinRateComparePanel.tsx |

 ---

 ## 9. 已决策事项（本轮 grill 前用户已拍板）

 - R1/R2/R3 在工作流与简报的重复显示 → **合并显示，避免数据冗余和性能问题**（方向已定，合并方式待逐项确认）。
