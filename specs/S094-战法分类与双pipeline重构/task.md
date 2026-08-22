# S094 原子任务清单（task）

> 状态图例：`[ ]` 待做 / `[x]` 完成。feature 分支 `feature/S094-战法分类与双pipeline重构`。
> 测试基线：后端 2215 passed（1 pre-existing S066 归档债）+ 前端 428 passed。
> 阶段与 spec §10 / plan.md 同步（ora-6 B4 重排）。

## S0 前置硬门：gene_scores 错位修复（S095，spec 已立项 `specs/S095-gene_scores写路径修复与日期守卫/`）
- [ ] T0a `_fetch_zt_pool` 对历史日请求加 code 集合校验（返回池实际日期 != 请求日期 → 拒绝写入，返空降级）
- [ ] T0b 历史行重算已完成（fix-18：08-13~08-21 code 集合 5/5 全等）——**写路径修复前 S2/S4 不可合并**
- [ ] G0 commit 门：写路径校验测试绿

## S1 统一 K线契约 + 因子层 + 权重源（R1-R5）
- [ ] T1 `strategies/pattern_scan.py`：`_compute_ma(bars,n)` SMA n=5/10/20，bars<20 返 None
- [ ] T2 `strategies/pattern_scan.py`：扩 `compute_shadow_length_pct(bars)=(high/close-1)*100`（复用 activity.py L112 先例）+ `compute_ma5_slope(bars)=(ma5[-1]-ma5[-2])/ma5[-2]`（ma5 用 T1 的 _compute_ma 算）
- [ ] T3 `strategies/non_limitup_funnel.py` L242 传 `sector_bars`（板块全成分等权平均，停牌按日期对齐取交集），compute_relative_strength 真相对
- [ ] T4 `strategies/non_limitup_funnel.py` 删 L48 NON_LIMITUP_WEIGHTS 硬编码
- [ ] T5 `strategies/impl/indicator_based.py` PatternReversal 改读 PatternScan（shadow_length_pct/volume_breakout_ratio/ma5_slope）；5 因子→3 字段删减声明 + 放量口径变更（今量/前5日均量≥1.2）+ "突破昨日最高"作废
- [ ] T6 **R4 不委托**——`compute_volume_signal_score` L86-120 按战法分支逻辑迁入对应 Strategy.match()（dragon_head/plat_breakout/low_absorption/reverse_package 各自的量能阈值），match 返回时填 signals 的 confidence/signal_strength
- [ ] G1 commit 门：统一 K线+因子+权重+match 下沉测试绿

## S2 候选生产拆分 + sector_rank（R11/R14/R27）← ora-6 重排
- [ ] T7 `strategies/sector_cycle.py`+`strategies/market_scan.py`（新建）：`compute_sector_stock_rank(code, sector_stocks, bars_map)` 板块内 relative_strength 降序排名
- [ ] T8 R14 FLOW B 候选扩 {code,name,bars,sector,sector_rank,close}，**name 从 `code_industry` 表反查**（kline cache FIELDS 无 name）
- [ ] T9 `strategies/non_limitup_funnel.py` run_non_limitup_funnel 拆"产候选"（只产 PatternScan factors + sector_rank + close，删自打分）+ score_candidates market_scan 分支调 check_quality_standards（market_data 复用 _build_market_data L277-293）
- [ ] G2 commit 门：候选生产+sector_rank 测试绿

## S3 StrategyContext + match 分流 + confidence + 接线（R6-R13/R26/R28）
- [ ] T10 `strategies/strategy_base.py` StrategyContext 加 market_scan_ctx={pattern,sector_rank,rel_strength_vs_sector}
- [ ] T11 `strategies/strategy_funnel_registry.py` score_candidates 加 funnel_type **必填** + STRATEGIES_BY_FUNNEL_TYPE（7 limitup=first_plate/consecutive_relay/break_reseal/n_shape_counterattack/end_of_day_sneak/weak_turn_strong/storm_reversal；5 market_scan=dragon_head/low_absorption/reverse_package/platform_breakout/pattern_reversal）
- [ ] T12 R8 既有调用传 funnel_type：workflow.py _collect（limitup+market_scan 两次）+ scheduled_tasks.py L1605（limitup）+ **forward_test.py L491（limitup）**——**删 pre_market_workflow**（走 StrategyMatcher 不调 score_candidates）
- [ ] T13 `strategies/impl/gene_based.py` DragonHead.match 删无条件放行，读 market_scan_ctx.rel_strength_vs_sector+sector_rank（≤3 命中）——**dispatch_match 波及 6 个消费方**（pre_market_workflow/workflow/strategy_backtest/prediction_ingest/position_advisor_v2），无 market_scan_ctx → 永不命中（涨停股本不该命中非涨停战法，spec 显式声明行为变化面）
- [ ] T14 **R10 3 战法** match 改读 PatternScan（pattern_reversal=shadow_length_pct/volume_breakout_ratio/ma5_slope；low_absorption=ma5_proximity/ma_bullish；platform_breakout=consolidation_days/volume_breakout_ratio）——**reverse_package 不在 R10**（保留 db_based.py 炸板池）
- [ ] T15 `strategies/strategy_funnel_registry.py` score_candidates **复用 dispatch_match compute_confidence**（L511 不丢弃，从 signals 按 strategy_code 取 s.confidence/s.signal_strength）——不派生
- [ ] T16 R13 独立端点 /api/strategy/non-limitup-funnel 同步切"产候选 → score_candidates(market_scan)"，输出对齐 scored_candidates schema（name+confidence+signal_strength+strategy_score）
- [ ] T17 `routers/workflow.py` _collect：R26 调 gather_non_limitup_candidates(date) → score_candidates(market_scan) + R28 briefing 响应分区透传（limitup scored + market_scan scored）
- [ ] G3 commit 门：分流+confidence+接线测试绿

## S4 5 根因修复（R16-R20）
- [ ] T18 `market.py` _emotion 加 zt_real 字段（latest 日从 _sentiment 拉；历史日返 None）+ sti_timeline schema 加 zt_real 列（migration 先例 20260817-001）+ _execute_sti_post_market 存 zt_real + _market_emotion_from_ctx 读 zt_real（历史日读 DB）——保留 zt_count 供内部
- [ ] T19 `routers/strategy.py` sector-rotation 端点 date 必填改 date=None 默认 last_trading_date_str + 前端 ContextTab 传 triplet.today
- [ ] ~~T20 `sector_divergence.py` R19 砍掉~~（ora-7 N5：前端已弃用，无消费方值得保留）
- [ ] T21 `tools/refresh_kline_cache.py` R20 全 A 扩容——**复用 load_industry_map()（5540 条已在产）+ 预估 2-3h + cache ~150MB 需配套模块级 memo 或迁 sqlite/parquet**
- [ ] ~~T22 R21 合并到 T1~~（ora-6 非阻断 #3：与 R1 重复）
- [ ] G4 commit 门：5 根因修复测试绿

## S5 前端 UI（R22-R25）
- [ ] T23 `Workflow.tsx` 双 pipeline 分区+折叠+卡片流转+仓位摘要截断
- [ ] T24 `StrategyMatchMatrix.tsx` 涨停/非涨停分区
- [ ] T25 `SectorCyclePanel/P2RiskPanel/VerificationCardBlock/SelectionPipeline` UI bug 修（代码2次/P2判据/验证对齐/定稿失配）
- [ ] T26 `NonLimitupPlaceholder.tsx` R13 对齐新 schema（c.score→c.strategy_score）
- [ ] G5 commit 门：UI 测试绿

## S6 全量回归 + playwright
- [ ] T27 pytest + vitest + tsc + vite build 全绿
- [ ] T28 playwright e2e AC1-AC11
- [ ] T29 验收收拢（task 勾选 + spec 状态 + 归档）
- [ ] G6 验收门

## 依赖
S0(前置硬门) → S1(因子层) → S2(sector_rank 前置) → S3(分流+接线) → S4(根因，可并行) → S5(前端) → S6(回归)
