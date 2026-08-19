# Spec: S084 — 选股池战法解耦（选股池 Tab + 战法 Tab 两级导航 + 因子补全）

> 状态：已实现（2026-08-19，见 `验收报告.md`）
> 作者：Claude  日期：2026-08-18
> 关联：`CLAUDE.md` §1.1、`specs/S002-打板工作流重构/`（P1 候选池漏斗）、`specs/S070-intraday采集管道/`（R7 派生）、`specs/S079-打板P2战法与仓位闸/`（仓位闸+龙虎榜）、`specs/S081-打板P2战法匹配/`（PRD 2 战法）、`specs/S083-工作流重构选股池分层/`（因子复用部分已 commit ada2b71，漏斗接入部分作废改耦合方向）
>
> **起因**：用户提出"第一步选股池是所有战法的基础，第二步才进入工作流"+"选股池要包含后面战法所需要的所有盘前因子，打造战法坚定基石"+"系统逻辑不要那么复杂，解耦"。当前 `pre_market_workflow.run()` 把选股池筛选+战法匹配+仓位建议串在一个函数里，战法因子散落在 `match_strategies` 各 elif 分支各自取数，与漏斗重复。S083 漏斗接入是耦合方向（漏斗塞进 pre_market_workflow），和用户"解耦"诉求相反，S083 漏斗接入部分作废，保留因子复用部分（ada2b71）。

---

## 1. 问题 / 目标

当前系统的耦合问题：
1. **选股池和战法耦合**：`pre_market_workflow.run()` 把"选股池筛选+战法匹配+仓位建议"串在一个函数里，选股池不独立
2. **战法因子散落**：`match_strategies` 各 elif 分支各自调 astock/kline/S070 取数，选股池没有一站式输出所有战法因子
3. **选股池因子缺口**：战法需要 6 类因子（GeneScore/涨停池原始dict/S070R7派生/前日成交额/K线派生/活跃度），选股池漏斗只采集了部分，战法还要自己补取
4. **前端导航按时间阶段**：Workflow.tsx 按"盘前/盘中/盘后"组织，不是按"选股池/战法"功能组织

**目标**（grill reframe 2026-08-19）：选股池独立产出 + 战法独立消费 + 前端两级 Tab 导航。**选股池只做 R1（全涨停 + 补全所有战法盘前因子），不做 R2/R3 过滤**——R2（活跃度）/R3（催化）下放战法层，每战法自定阈值（原 R1→R2→R3 漏斗筛选收回，因 R2/R3 是具体战法筛选逻辑，放选股池层会预筛掉其他战法的标的）。选股池输出 `DiagnosisCard`（含 `gene_score` + `pool_item` + `derived` + `indicators`），因子懒加载/异步预采集（**16:30 收盘后异步后台任务预采集 derived 等落库，不阻塞主流程**；战法调用时未补全则战法层 fallback 自补）。前端 Workflow.tsx "选股池"Tab + "战法"Tab 两级导航。**§44 从工程底线降级为参考性建议**（不强制 gate；设计方案经深度调研，不阻塞实现）。

---

## 2. 背景

### 2.1 选股池因子补全清单（explorer 全量数据源盘点 2026-08-18）

> 原则：不删任何因子。能取到的标数据源；暂时取不到的标"⚠️ 预警：暂时无法取得" + 替代方案。盘前可取 vs 盘中才能取分类标注。

#### A. 已有因子（选股池已采集，15 个，不补）

| 因子 | 数据源 | 盘前可取? |
|---|---|---|
| turnover_pct / vol_ratio / amount_yi / amplitude_pct | tencent_quote | ⚠️ 盘中实时值（盘前取昨日 K线复算） |
| main_net_inflow / main_net_5d | stock_fund_flow_120d | ✅ 盘前取昨日（T+1） |
| dragon_tiger_inst_net | dragon_tiger_board | ✅ 盘前取昨日（T+1） |
| dragon_tiger_hot_money_relay | fetch_dt_hot_money_relay | ✅ 盘前取昨日 |
| northbound | fetch_northbound | ⚠️ 2024-08-19 后停更返 None |
| seal_amount | 涨停四池 fund | ✅ 盘前取昨日池 |
| float_market_cap | tencent_quote float_mcap_yi | ✅ |
| auction_open_pct | auction_screener | ⚠️ 盘后分析工具（15:30 后） |
| max_high_pct / shadow_length_pct / ma_5_status / prev_turnover_pct | K线复算（S083 ada2b71） | ✅ 历史日K线 |

#### B. 要补的因子 — 数据源可靠可取（17 个，标数据源 + 盘前/盘中）

| 因子 | 数据源 | 去向 | 盘前可取? | 说明 |
|---|---|---|---|---|
| **涨停池原始 dict（6 字段）** | | | | |
| lbc（连板数）| `em_zt_topic_pool` getYesterdayZTPool | pool_item | ✅ 盘前取昨日 | 走 em_get 限流 |
| zbc（炸板次数）| 同上 | pool_item | ✅ | |
| fbt（首封时间）| 同上 | pool_item | ✅ | |
| zdp（涨幅%）| 同上 | pool_item | ✅ | |
| zje（涨停价）| 同上 | pool_item | ✅ | |
| hybk（行业/概念）| 同上 | pool_item | ✅ | |
| **tencent_quote 扩展（8 字段）** | | | | |
| last_close（昨收）| tencent_quote vals[4] | IndicatorSet | ✅ | 不封 IP |
| open（开盘）| vals[5] | IndicatorSet | ⚠️ 盘中 | 盘前取昨日 K线 bar.open |
| change_amt（涨跌额）| vals[31] | IndicatorSet | ⚠️ 盘中 | 同上 |
| pe_ttm（市盈率）| vals[39] | IndicatorSet | ✅ | 静态估值 |
| mcap_yi（总市值）| vals[44] | IndicatorSet | ✅ | |
| pb（市净率）| vals[46] | IndicatorSet | ✅ | |
| limit_up（涨停价）| vals[47] | IndicatorSet | ✅ | |
| limit_down（跌停价）| vals[48] | IndicatorSet | ✅ | |
| **板块资金（3 字段）** | | | | |
| sector_net_inflow（板块净流入）| `market._sectors()` → akshare stock_fund_flow_industry | IndicatorSet | ⚠️ 盘中 | **替代方案**：盘前取昨日 _sectors() 返回值（akshare 盘前可取昨日） |
| sector_inflow（流入）| 同上 | IndicatorSet | ⚠️ 盘中 | 同上替代 |
| sector_outflow（流出）| 同上 | IndicatorSet | ⚠️ 盘中 | 同上替代 |
| **K线扩展（1 字段）** | | | | |
| prev_amount_yi（前日成交额）| activity.py 已取 K线 bars 前日 bar | IndicatorSet | ✅ | |
| **S070 R7 派生（3 字段）** | | | | |
| broken_duration_min | `compute_derived_features(get_snapshots_by_code)` | derived 子对象 | ⚠️ 盘中采集 | **预警：盘前 snapshots 未采集时 None**。替代方案：盘前用涨停池 zbc（炸板次数）+ fbt（首封时间）做近似代理，标"60s 粒度近似" |
| max_drop_pct | 同上 | derived 子对象 | ⚠️ 盘中 | 同上预警。替代方案：盘前用 K线前日 low/涨停价 算前日回撤近似 |
| last_lock_time | 同上 | derived 子对象 | ⚠️ 盘中 | 同上预警。替代方案：盘前用涨停池 fbt（首封时间）做近似代理 |
| **GeneScore（完整对象）** | | | | |
| total_score / zt_count_250d / factors（封板率/次日溢价率/红盘率/涨停频次/炸板后溢价）| `get_screener_result`（漏斗 R1 gene.py 已调但只存数字）| gene_score 子对象 | ✅ | gene.py 扩展存完整对象 |

#### C. 数据源已有但选股池没采集的因子 — 建议补进（explorer 盘点发现，标数据源 + 可靠性）

| 因子 | 数据源 | 去向 | 盘前可取? | 实战价值 | 说明 |
|---|---|---|---|---|---|
| **市场宽度（5 字段，市场级非个股级）** | | | | | |
| breadth（冰点/偏弱/中性/偏强/普涨）| `market.get_short_term_emotion()` | FunnelResult.market_context | ✅ | 高 | 仓位闸硬熔断参考 |
| break_rate（炸板率）| 同上 | market_context | ✅ | 高 | 退潮信号 |
| seal_rate（封板率）| 同上 | market_context | ✅ | 高 | 板不牢信号 |
| promotion_rate（晋级率）| 同上 | market_context | ✅ | 高 | 接力意愿 |
| max_boards / ladder tiers（连板高度梯队）| 同上 | market_context | ✅ | 高 | 情绪天花板 |
| **龙虎榜席位明细（已实现 S079，未进选股池）** | | | | | |
| buy_one_ratio（买一占比）| `seat_engine.compute_consensus_signal` | DiagnosisCard.seat_detail | ✅ | 高 | 独食独大判定 |
| day_trip_ratio（一日游占比）| `hot_money_seats.SeatRiskFactor` | seat_detail | ✅ | 高 | 次日砸盘风险 |
| institution_ratio（机构占比）| 同上 | seat_detail | ✅ | 中 | 机构合力 |
| risk_label（高/中/低风险）| 同上 | seat_detail | ✅ | 高 | 综合风控标记 |
| **公告催化类型 + 概念联动（2 字段）** | | | | | |
| announcement_type（预增/重组/回购/其他）| `catalyst.py classify_announcement` | IndicatorSet | ✅ | 中 | 次日溢价参考 |
| concept_count（同概念涨停家数）| `catalyst.py concepts` 列表长度 | IndicatorSet | ✅ | 高 | 板块联动判定 |
| **同花顺涨停原因（5 字段）** | | | | | |
| reason（涨停原因题材）| `ths_limit_up_pool` | pool_item 扩展 | ✅ | 中 | 题材判定 |
| board_type（板型：换手/一字/T字）| 同上 | pool_item 扩展 | ✅ | 高 | 打板战法区分 |
| ths_seal_rate（同花顺封板率）| 同上 | pool_item 扩展 | ✅ | 中 | 交叉验证 |
| first_time（首次涨停时间）| 同上 | pool_item 扩展 | ✅ | 中 | 与 fbt 交叉验证 |
| is_again（回封标记）| 同上 | pool_item 扩展 | ✅ | 中 | 烂板回封战法 |
| **封单变化率（派生）** | | | | | |
| seal_delta（封单额变化率）| `seal_intraday_snapshots` 表已有 seal_amount 时序 | IndicatorSet | ⚠️ 盘中 | 高 | **预警：盘前 snapshots 未采集时 None**。替代：盘前用涨停池 fund（封单额静态值） |
| **N日涨幅（派生，3 字段）** | | | | | |
| change_5d / change_10d / change_20d | K线 bars 已取（activity.py）| IndicatorSet | ✅ | 中 | 短期趋势判断 |
| **换手率分位（派生）** | | | | | |
| turnover_percentile_250d | K线 250日 bars 已取 | IndicatorSet | ✅ | 中 | 放量异常判定 |
| **板块资金连续流入天数（派生）** | | | | | |
| sector_inflow_days | fund_flow main_net_5d 已有 5日累计 | IndicatorSet | ✅ | 中 | 主线确立判定 |

#### D. ⚠️ 预警：暂时无法取得，积极寻找可靠源

| 因子 | 现状 | 替代方案 | 优先级 |
|---|---|---|---|
| 竞价金额（9:25 集合竞价成交额）| repo 无实时竞价数据源（auction_screener 是盘后分析非实时）| **积极寻找**：东财 push2ex 竞价接口 / akshare stock_zh_a_minute | 高（弱转强核心因子） |
| 五档买卖盘（买一/卖一挂单量比）| repo 无盘口数据源 | **积极寻找**：东财 push2 盘口接口 / Level-2（需付费） | 高（封板意愿判定） |
| 实时逐笔成交（红字大单/连续大单）| 需 Level-2 付费 | **暂无替代**：标记"需 Level-2 数据源" | 中 |
| 北向实时资金 | 2024-08-19 后停更 | **暂无替代**：保留字段标 None + "北向停更" | 低 |
| 筹码分布 | repo 无数据源 | **积极寻找**：akshare 筹码分布 API | 中 |

#### E. 盘前 vs 盘中边界（grill Q1=A 砍盘中 + Q2=B修正 derived 取昨日值）

**选股池只做盘前，不碰 T 日盘中实时数据。所有因子取 T-1 昨日值（昨日收盘后已落库的数据）。**

| 因子 | 盘前取 T-1 昨日值的方式 | T 日盘中实时值 |
|---|---|---|
| S070 R7 派生（broken_duration/max_drop/last_lock）| `get_snapshots_by_code(code, yesterday_date)` → `compute_derived_features` 取昨日 snapshots（已落库）| 不取（盘中由战法工作流自行取 T 日实时）|
| 封单变化率（seal_delta）| T-1 昨日 snapshots 时序算 | 不取 |
| 市场宽度（breadth/break_rate/seal_rate/promotion_rate/max_boards）| `market._emotion(yesterday_date)` 取昨日 | 不取 |
| 板块资金（sector_net_inflow/inflow/outflow）| `market._sectors()` 盘前取昨日值 | 不取（sector_flow date<今日 返 None）|
| tencent_quote 实时行情 | 盘前取昨日 K线复算（activity.py 已有路径）| 不取 T 日实时 |
| 当日涨停池 | 盘前取 `getYesterdayZTPool` 昨日池 | 不取 T 日当日池 |

**选股池边界**：纯盘前 T-1 数据 + 静态数据 + 历史K线派生。不碰 T 日盘中实时数据。盘中阶段由战法工作流自行取 T 日实时数据。

### 2.2 既有选股池 API（grill 核实，Q4=A 复用）

前端 `frontend/src/lib/candidates.ts` 已有独立选股池 API client：
- `runFunnel(stage, date)` → POST `/workflow/candidates/funnel`
- `getFunnelLayers(runId, date)` → GET `/workflow/funnel/layers`
- `getFunnelConfig()` / `updateFunnelConfig()` / `rerunLayer()` / `rerunLayerDownstream()`

后端 `candidate_funnel/funnel.py` 有 `run_funnel(stage, date, cfg, ctx)` + TTL 缓存（`_FUNNEL_CACHE`，默认 3600s）。

**选股池 API 已独立存在，只是前端 PreMarketBriefing 没用它（用了 `/api/workflow/pre-market` 透传的 `funnel_layers`）**。解耦 = 前端选股池 Tab 直接调既有 API。

### 2.3 与既有 spec 关系

- **S002（P1 已实现）**：漏斗 `run_funnel` 已实现 + 验收。本 spec 扩展其输出（DiagnosisCard 加 3 子对象），不改漏斗 R1→R2→R3 筛选逻辑
- **S070（已合并 develop）**：R7 派生 `compute_derived_features` 供选股池补 derived 子对象
- **S083（因子复用已 commit ada2b71）**：IndicatorSet 加 4 字段（max_high/shadow/ma_5/prev_turnover）+ match_strategies 加 indicators 参数已落地。本 spec 补 DiagnosisCard 3 子对象 + gene.py 存完整 GeneScore + 选股池补涨停池原始dict+S070派生+前日成交额
- **S083（漏斗接入 pre_market_workflow 部分）**：作废。S083 spec §3.1 R1（删 _build_candidate_pool 改调 run_funnel）作废 —— 解耦方向不改 pre_market_workflow 内部，选股池 Tab 独立调 API
- **S079/S081（已合并 develop）**：仓位闸+龙虎榜+战法匹配已落地，本 spec 不改后端战法/仓位/风控逻辑

---

## 3. 需求清单

> **grill reframe 2026-08-19**：选股池只做 R1（全涨停 + 补因子），不做 R2/R3 过滤（R2/R3 下放战法层）。原 R1→R2→R3 漏斗筛选收回——R2/R3 是具体战法筛选逻辑，放选股池层会预筛掉其他战法标的。

### 3.1 选股池 = 全涨停（R1）+ DiagnosisCard 3 子对象 + IndicatorSet 因子

- [ ] R1：选股池只取全涨停（R1 宽源），**不做 R2（活跃度）/R3（催化）过滤**
  - [ ] R1.1 `funnel.py _run_funnel_impl` 删 `_filter_r2`/`_filter_r3` 逻辑，final_candidates = R1 全涨停 + 自选
  - [ ] R1.2 `DiagnosisCard` 加 3 子对象：`gene_score`（gene.py 存 gene_obj 完整对象）+ `pool_item`（zt_pool_source，em_get-backed）+ `derived`（derived_source，懒加载/异步预采集）
  - [ ] R1.3 `IndicatorSet` 加 10 字段（last_close/open/change_amt/pe_ttm/mcap_yi/pb/sector_net_inflow/sector_inflow/sector_outflow/prev_amount_yi），按历史日路径分字段取数（B4：kline 复算 vs tencent_quote 当日）
- [ ] R2：R2（活跃度）/R3（催化）下放战法层
  - [ ] R2.1 `match_strategies` 每战法自定 R2/R3 阈值（first_plate 定 turnover/amount；weak_turn_strong 定 lbc/broken；pattern_reversal 定 zdp/max_high/shadow）
  - [ ] R2.2 选股池不替战法筛 R2/R3，战法从 card 读因子 + 自定阈值判定

### 3.2 16:30 异步预采集 + 战法 fallback

- [ ] R3：16:30 异步预采集（scheduled_tasks 新任务）
  - [ ] R3.1 `scheduled_tasks.py` 加任务类型：每日 16:30 启动，预采集 derived（`compute_derived_features(get_snapshots_by_code)`）落库（derived 缓存表/字段）
  - [ ] R3.2 不阻塞主流程——选股池 `run_funnel` 读预采集的 derived（不 per-code 实时算）；未预采集则 derived=None 降级
- [ ] R4：战法 fallback（card.derived=None 时战法层自补）
  - [ ] R4.1 `match_strategies` weak_turn_strong：card.derived=None 时战法层调 `get_snapshots_by_code` + `compute_derived_features` 自补（B2 fallback 保留，card=None 走原路径）
  - [ ] R4.2 card.derived 非空（异步预采集落库）→ 直接读，不重算

### 3.3 §44 降级（工程底线 → 参考性建议）

- [ ] R5：§44（lift bar）从工程底线降级为参考性建议
  - [ ] R5.1 `CLAUDE.md` §1.2：§44 从"必过 gate"改为"参考性建议"（设计方案经深度调研，不阻塞实现）
  - [ ] R5.2 §44 验证移到设计阶段（验证设计方案）+ 回溯模块（独立模块，引入 §44 作为回溯方案之一，长期积累数据后跑）

### 3.4 战法从 DiagnosisCard 读因子 + 自定 R2/R3 + fallback

- [ ] R6：`match_strategies` 加 `card` 参数（默认 None 向后兼容）
  - [ ] R6.1 既有 9 战法从 `card.gene_score` 读 + 自定 R2/R3 阈值
  - [ ] R6.2 PRD 弱转强接力从 `card.pool_item`/`card.derived`/`card.indicators` 读；card.derived=None 时 fallback 自补（R4）
  - [ ] R6.3 PRD 形态反包从 `card.pool_item.zdp`/`card.indicators` 读 + 自定 R3 阈值
  - [ ] R6.4 card=None 时走既有 fallback（pre_market_workflow 不传 card，行为不变）
- [ ] R7：`StrategyMatcher.match/match_batch` 加 card/cards_map 透传

### 3.5 前端选股池 Tab + 战法 Tab（Q5=A 复用既有组件）

- [ ] R8：`Workflow.tsx` 两级 Tab（选股池 / 战法），tab 在最顶（PageHeader 上）
  - [ ] R8.1 选股池 Tab：调 `candidatesApi.runFunnel` + `FunnelLayers`（R1 全涨停 + 因子）+ `SelectionPipeline`（final_candidates 全因子 DiagnosisCard 详情）
  - [ ] R8.2 选股池 Tab 不调 `/api/workflow/pre-market`
  - [ ] R8.3 战法 Tab：保留既有 7 卡片网格，to 指向 `/workflow/pre-market?strategy=`
- [ ] R9：每层选股结果详情显示该层相关因子；终选（final_candidates）显示所有因子（DiagnosisCard 3 子对象 + IndicatorSet 全字段）

### 3.6 pre_market_workflow 保留不改（Q3=C 三入口并存）

- [ ] R10：`pre_market_workflow.run()` 保留原样不改（三入口并存）

---

## 4. 受影响文件

| 文件 | 改动 |
|---|---|
| `backend/candidate_funnel/funnel.py`（修改） | `_run_funnel_impl` **删 R2/R3 过滤**（`_filter_r2`/`_filter_r3` 调用），final_candidates = R1 全涨停 + 自选；yesterday_date + zt_pool_map + industry_map + per-code derived（懒加载/读预采集） |
| `backend/candidate_funnel/models.py`（已改） | DiagnosisCard 加 3 字段；IndicatorSet 加 10 字段（limit_up/limit_down 复用既有，实际 10 新增） |
| `backend/candidate_funnel/sources/gene.py`（已改） | genes dict 存 gene_obj 完整 GeneScore 对象 |
| `backend/candidate_funnel/sources/activity.py`（已改） | 两路径新字段（kline 复算 + tencent_quote 当日） |
| `backend/candidate_funnel/sources/fund_flow.py`（已改） | sectors 参数 + industry_map（zt pool hybk，em_get-backed，review HIGH 修复） |
| `backend/candidate_funnel/sources/zt_pool_source.py`（已新增） | 涨停池原始 dict source（first_board_filter.fetch_zt_pool，em_get） |
| `backend/candidate_funnel/sources/derived_source.py`（已新增） | S070 R7 派生 source（读预采集/实时算） |
| `backend/candidate_funnel/diagnosis.py`（已改） | build_diagnosis_card 塞 3 子对象 + build_indicator_set 透传 10 字段 |
| `backend/limitup_strategy.py`（修改） | match_strategies 加 card 参数（已改）+ **每战法自定 R2/R3 阈值**（新，R2/R3 从选股池下放）+ **derived=None 战法层 fallback 自补**（R4） |
| `backend/strategies/strategy_matcher.py`（已改） | match/match_batch 加 card/cards_map |
| `backend/scheduled_tasks.py`（修改） | **加 16:30 异步预采集任务类型**（derived 落库，不阻塞主流程，R3） |
| `backend/pre_market_workflow.py`（**不改**） | Q3=C 保留原样，三入口并存 |
| `backend/routers/workflow.py`（修改） | 选股池 API 透传 DiagnosisCard 含 3 子对象 |
| `frontend/src/pages/Workflow.tsx`（已改） | 两级 Tab（最顶）+ 选股池 Tab（FunnelLayers + SelectionPipeline 终选全因子） |
| `frontend/src/lib/candidates.ts`（已改） | DiagnosisCard 类型加 3 子对象 + IndicatorSet 10 字段 |
| `frontend/src/components/candidate/DiagnosisCard.tsx`（已改） | 展示 3 子对象 + 10 字段 |
| `frontend/src/components/ui/FunnelLayerCard.tsx`（已改） | 每行显示该层因子（passedFactors） |
| `frontend/src/components/pipeline/SelectionPipeline.tsx`（已改） | 终选可展开显示 final_candidates 全因子（FinalCandidatesNode） |
| `CLAUDE.md`（修改） | §1.2 §44 从工程底线降级为参考性建议（R5） |

---

## 5. 设计方案

### 5.1 解耦架构（选股池 R1-only → 战法自定 R2/R3 + 异步预采集 + fallback）

```
[选股池 Tab]（前端 Workflow.tsx）
  调 runFunnel API → run_funnel() 产出 FunnelResult
  选股池只 R1（全涨停 + 补因子），不做 R2/R3 过滤
  FunnelResult.final_candidates: list[DiagnosisCard]
    DiagnosisCard 含：gene_score + pool_item + derived + indicators（全因子）
  展示：FunnelLayers（R1 全涨停 + 因子）+ SelectionPipeline（终选全因子详情）
  不调 /api/workflow/pre-market

[16:30 异步预采集]（scheduled_tasks 新任务）
  收盘后 16:30 启动，预采集 derived（compute_derived_features(get_snapshots_by_code)）落库
  不阻塞主流程；选股池读预采集的（不 per-code 实时算）；未预采集则 derived=None

[战法层]（match_strategies）
  从 card 读因子 + 每战法自定 R2/R3 阈值（R2 活跃度/R3 催化从选股池下放）
  card.derived=None（未预采集）→ 战法层 fallback 自补（get_snapshots_by_code + compute_derived_features）
  card=None → 走既有 fallback（pre_market_workflow 不传 card，行为不变）

[战法 Tab] + [盘前简报]（既有，不改，三入口并存）
```

### 5.2 R1→R2→R3 漏斗为何收回（grill reframe）

- R2（活跃度：换手/成交/北向）/R3（催化：竞价/公告/板块）是**具体战法筛选逻辑**，放选股池层会预筛掉其他战法标的（首板流纯资金板被 R3 催化过滤；weak_turn_strong 炸板股被 R1 涨停基因过滤；连板高度标的无当日催化被 R3 过滤）
- 选股池应是**所有涨停战法标的的 superset**（全涨停 + 因子），R2/R3 下放战法层（每战法自定阈值）—— 这才是真"解耦"（选股池独立产出，战法独立消费+自筛）

### 5.3 工程约束

- **不破坏既有 9 战法**：match_strategies card 默认 None，既有调用行为不变
- **不破坏 S079 后处理**：cap_by_market_phase + DragonTigerSeatFilter 不改
- **em_get 防封底线**：zt_pool_source 走 first_board_filter.fetch_zt_pool（em_get + 24h 缓存）；sectors 走 market.get_overview（5min 缓存）；individual_info 已改 industry_map（zt pool hybk，em_get-backed，review HIGH 修复）
- **不臆造**：3 子对象各自 None 降级；pe_ttm/pb/mcap_yi 历史日 None+missing（tencent_quote 仅当日）
- **异步不阻塞**：16:30 预采集落库，选股池读预采集（不 per-code 实时算 derived）
- **§44 降级**：参考性建议，不强制 gate（设计方案经深度调研；§44 移设计期 + 回溯模块）

---

## 6. 验收标准

- [ ] AC1：选股池只 R1（全涨停），不做 R2/R3 过滤（`_filter_r2`/`_filter_r3` 删除/下放战法）
- [ ] AC2：DiagnosisCard 含 3 子对象（gene_score/pool_item/derived）+ IndicatorSet 10 字段（已实现）
- [ ] AC3：R2/R3 下放战法——match_strategies 每战法自定活跃度/催化阈值
- [ ] AC4：16:30 异步预采集 derived 落库（scheduled_tasks 新任务），不阻塞主流程
- [ ] AC5：战法 fallback——card.derived=None 时战法层自补（get_snapshots_by_code + compute_derived_features）
- [ ] AC6：§44 降级——CLAUDE.md §1.2 改为参考性建议
- [ ] AC7：match_strategies card 参数（向后兼容），既有 9 战法 + PRD 2 战法回归通过
- [ ] AC8：前端两级 Tab（最顶）+ 选股池 Tab（FunnelLayers + SelectionPipeline 终选全因子）
- [ ] AC9：每层选股结果详情显示该层因子；终选显示所有因子（DiagnosisCard 3 子对象 + IndicatorSet 全字段）
- [ ] AC10：三入口并存（选股池 Tab + 战法 Tab + 盘前简报），pre_market_workflow 不改
- [ ] AC11：轻量风险提醒（CLAUDE.md §1.1 弱合规）

---

## 7. 合规与工程底线自查

- [x] 研判/推荐/买卖时机属系统能力（CLAUDE.md §1.1）；挂轻量风险提醒
- [ ] 判断可复现：涉及数据的跑 `financial_rigor.py` 验算 —— **实现阶段验证**
- [x] 不接券商不下单（AC7 工程底线）
- [x] em_get 防封：涨停池原始 dict 从 astock.em_zt_topic_pool 取
- [x] 不臆造：3 子对象各自管理缺失，标 None + 原因
- [x] S002 参考价位隔离决议 + AC10 显式豁免（继承 S079 §2.3）

---

## 8. 测试计划

- **单元测试**（`pytest -m "not live"`）：
  - gene.py 扩展存完整 GeneScore：mock screener_result，验证 genes[code] 含 gene_obj
  - DiagnosisCard 3 子对象填充：mock funnel 构建，验证 card.gene_score/pool_item/derived 非 None
  - match_strategies 从 card 读因子：mock DiagnosisCard 含全部子对象，验证战法命中
  - 数据缺失降级：mock derived=None（snapshots 未采集），验证弱转强标"分时数据未就绪"
  - 既有 9 战法回归：传/不传 card 命中一致
- **前端**：选股池 Tab 调 runFunnel 展示漏斗 + 候选；战法 Tab 保留卡片网格
- **手动验收**：前后端跑起来，选股池 Tab 展示 R1→R2→R3 + 候选，战法 Tab 点击进战法特定筛选

---

## 9. 风险与回滚

| 风险 | 影响 | 缓解 |
|---|---|---|
| DiagnosisCard 加 3 子对象破坏序列化 | 前端类型/快照不兼容 | 3 字段默认 None，既有快照无字段降级 |
| match_strategies 改从 card 读破坏既有 9 战法 | 既有战法不命中 | 新参数默认 None 向后兼容；传 card 时从 card 读，不传时走原路径 |
| pre_market_workflow 解耦破坏盘前简报 | 盘前简报空/报错 | 灰度：选股池 Tab 独立先跑通，pre_market_workflow 保留编排层过渡 |
| S070 R7 派生盘前未采集 | derived=None 弱转强不命中 | 诚实标"分时数据未就绪"，盘中采集完后补 |

**回滚**：
1. DiagnosisCard 3 子对象默认 None，不影响既有序列化
2. match_strategies 新参数默认 None，删除即回退
3. 前端两级 Tab 独立于既有 PreMarketBriefing，回滚只删 Tab 不影响盘前简报

---

## 10. 待定项

- T1：pre_market_workflow 解耦后是否完全废弃（R9.4）—— 实阶段核实选股池 Tab + 战法 Tab 是否能完全替代盘前简报
- T2：价值选股池（S005 value_funnel）是否纳入选股池 Tab 作为第二个池子 —— 本 spec 只做短线选股池，价值池后续
- T3：战法-选股池映射（哪些战法用哪个池子）—— 本 spec 短线 11 战法共用短线池，映射=1:1，后续价值战法加入时需映射
- T4：**多源异构 A 股数据源子模块**（独立 backlog，不影响 S084 主线）—— 在 astock 基础上打造更强大的多源异构数据层，抽离成独立子模块。目标：统一封装东财/腾讯/同花顺/mootdx/akshare/新浪/百度等多源数据，自动回退 + 交叉验证 + 统一字段口径，消除当前散落在 astock.py / data/sources/ / candidate_funnel/sources/ 的重复取数。explorer 全量盘点（exp-1）已确认现有数据源全貌，可作为子模块设计基础。**后续独立 spec，不阻断 S084**
