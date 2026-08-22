# S094 实施计划（plan）

> 配套 spec.md（Oracle 两轮审查吸收闭合 + §3.L/M 定稿收敛）。large 级。
> feature 分支 `feature/S094-战法分类与双pipeline重构`。
> 测试基线：后端 2215 passed（1 pre-existing S066 归档债）+ 前端 428 passed。

## 阶段（ora-6 B4 重排：消除 S2 依赖 S3 倒置 + R26-R28 归属）

### S0 前置硬门：gene_scores 错位修复（S094-P0，独立 spec/分支）
- 写路径根因修复：_fetch_zt_pool 对历史日请求加 code 集合校验（返回池实际日期 != 请求日期 → 拒绝写入）
- 历史行重算已完成（fix-18：08-13~08-21 code 集合 5/5 全等，备份 .vibe-research/gene_scores.db.bak-recompute-offset-2026-08-23）
- **S2/S4 合并前必须完成写路径修复**

### S1 统一 K线契约 + 因子层 + 权重源（R1-R5）
- pattern_scan.py：R1 `_compute_ma(bars,n)` SMA n=5/10/20，bars<20 返 None；**R5 扩 compute_shadow_length_pct(bars)=(high/close-1)*100 + compute_ma5_slope(bars)=(ma5[-1]-ma5[-2])/ma5[-2]**（复用 activity.py L112 先例）
- pattern_scan.py / non_limitup_funnel.py：R2 `sector_bars` 等权平均（板块全成分有 bar 者参与，停牌按日期对齐取交集），run_non_limitup_funnel L242 传 sector_bars
- non_limitup_funnel.py：R3 删 L48 NON_LIMITUP_WEIGHTS 硬编码；**R4 不委托 compute_strategy_score——per-strategy volume_signal 下沉 match 层**（compute_volume_signal_score L86-120 按战法分支迁入对应 Strategy.match()，填 signals 的 confidence/signal_strength）；候选 factors 仍用单一一份 PatternScan factors dict（中文键 {相对强度,均线多头,量能信号,板块强度} 0-100，复用既有 4 个映射函数 L60-137）
- pattern_scan.py：R5 PatternScan 升 market_scan 唯一因子源；indicator_based PatternReversal 改读 PatternScan（不读 ctx.indicators）；5 因子→3 字段删减（未封涨停删=涨停判定在 match 层 pool_item.lbc/zbc；最高≥7% 删=与上影≥4% 重叠）+ 放量口径变更（今量/昨量→今量/前5日均量，阈值 1.2 沿用保守值，实现后回测调参）；"突破昨日最高"作废

### S2 候选生产拆分 + sector_rank（R11/R14/R27）← ora-6 重排：sector_rank 前置
- sector_cycle.py / market_scan.py（新建）：R11 `compute_sector_stock_rank(code, sector_stocks, bars_map)` 板块内 relative_strength 降序排名
- R14 FLOW B 候选扩 {code,name,bars,sector,sector_rank,close}，**name 从 code_industry 表反查**（kline cache FIELDS 无 name）
- non_limitup_funnel.py：R27 run_non_limitup_funnel 拆"产候选"（只产候选 PatternScan factors + sector_rank + close，删自打分）+ score_candidates market_scan 分支调 check_quality_standards（market_data 管道复用 _build_market_data non_limitup_funnel.py L277-293）

### S3 StrategyContext 扩展 + match 分流 + confidence + 接线（R6-R13/R26/R28）
- strategy_base.py：R6 StrategyContext L47 加可选 market_scan_ctx={pattern:PatternScan, sector_rank:int, rel_strength_vs_sector:float}
- strategy_funnel_registry.py：R7 score_candidates 加 funnel_type **必填**（无默认 None=全跑——与"不交叉"矛盾+crash）；STRATEGIES_BY_FUNNEL_TYPE 12 战法归组（7 limitup + 5 market_scan）
- R8 既有调用传 funnel_type：workflow.py _collect（涨停 limitup + 非涨停 market_scan 两次）+ scheduled_tasks.py L1605（limitup）+ **forward_test.py L491（limitup）**——删 pre_market_workflow（走 StrategyMatcher 不调 score_candidates）
- gene_based.py：R9 DragonHead.match L180 删无条件放行，读 market_scan_ctx.rel_strength_vs_sector+sector_rank（≤3 命中）——**dispatch_match 经共享波及 6 个消费方**（pre_market_workflow L174 / workflow.py L860 / strategy_backtest L145/L236 / prediction_ingest L99 / position_advisor_v2 L196），无 market_scan_ctx → dragon_head + 4 形态战法从"可能命中"变"永不命中"（涨停股本不该命中非涨停战法，方向对，spec 显式声明行为变化面）
- **R10 3 战法 match 改读 PatternScan**（pattern_reversal=shadow_length_pct/volume_breakout_ratio/ma5_slope；low_absorption=ma5_proximity/ma_bullish；platform_breakout=consolidation_days/volume_breakout_ratio）——reverse_package 不在 R10（保留 db_based.py 炸板池，§4 db_based.py 补列）
- strategy_funnel_registry.py：R12 score_candidates **复用 dispatch_match 产的 compute_confidence**（L511 不丢弃，从 signals 按 strategy_code 取 s.confidence/s.signal_strength）——不派生
- R13 独立端点 /api/strategy/non-limitup-funnel 同步切"产候选 → score_candidates(market_scan)"，输出对齐 scored_candidates schema（name+confidence+signal_strength+strategy_score）
- workflow.py _collect：R26 调 gather_non_limitup_candidates(date) → 喂 score_candidates(market_scan) + R28 briefing 响应分区透传（limitup scored + market_scan scored）

### S4 5 根因修复（R16-R20）
- market.py：R16 _emotion 加 zt_real 字段（latest 日从 _sentiment 拉 akshare legu "真实涨停"；历史日返 None）+ sti_timeline schema 加 zt_real 列（migration 先例 20260817-001_add_raw_break_rate.sql）+ _execute_sti_post_market 存 zt_real + _market_emotion_from_ctx 读 zt_real（历史日读 DB，不依赖 akshare 历史源）——保留 zt_count=len(zt) 供内部
- ~~R15 前端读 zt_count 方案删~~（ora-6 B2：market_emotion 无 zt_real 字段，zt_count 是东财池 len 非"真实涨停"）
- routers/strategy.py：R18 sector-rotation 端点 date 必填改 date=None 默认 last_trading_date_str + 前端 ContextTab 传 triplet.today（非 aggregate_sectors industry 缺——ora-6 实测 industry 54/54 满值）
- ~~R19 sector_divergence 砍掉~~（ora-7 N5：前端已弃用，无消费方值得保留；§4/§10/§7 同步删 R19 引用）
- tools/refresh_kline_cache.py：R20 全 A 扩容——**复用 load_industry_map()（5540 条已在产，非 baostock query_stock_basic 已式微）+ 预估 2-3h 实测为准 + cache ~150MB 需配套模块级 memo 或迁 sqlite/parquet**
- ~~R21 合并到 R1~~（ora-6 非阻断 #3：与 R1 完全重复）

### S5 前端 UI（R22-R25）
- Workflow.tsx：R22 双 pipeline 上下分区+折叠（region 级+卡片级分层）+ R23 卡片流转（①②③④/⑤⑥⑦）+ 仓位摘要内联 L357-426 截断修
- StrategyMatchMatrix.tsx：R24 涨停/非涨停分区（两实例或单组件内分区）
- SectorCyclePanel/P2RiskPanel/VerificationCardBlock/SelectionPipeline：R25 UI bug 修（代码2次/P2判据/验证对齐/定稿失配）
- NonLimitupPlaceholder.tsx：R13 对齐新 schema（c.score→c.strategy_score）

### S6 全量回归 + playwright
- pytest + vitest + tsc + vite build + playwright e2e AC1-AC11

## 依赖
S0(前置硬门) → S1(因子层) → S2(sector_rank 前置) → S3(分流+接线) → S4(根因，可并行) → S5(前端) → S6(回归)

## 纪律
- score_candidates funnel_type 必填（不默认全跑）
- R4 per-strategy volume_signal 下沉 match 层（不委托 compute_strategy_score，候选用单一 factors）
- R5 compute_shadow_length_pct/compute_ma5_slope 有签名定义（非"实现时定"）
- R10 reverse_package 不改读 PatternScan（保留 db_based.py 炸板池）
- confidence 复用 dispatch_match compute_confidence（不派生 strategy_score/100）
- zt_real 加字段保留 zt_count（不替换）
- market_scan.py 新模块 + non_limitup_funnel.py 瘦身入口
- 性能预算（top N=10 + 每板块 ≤50 + 候选 cap ≤30）
