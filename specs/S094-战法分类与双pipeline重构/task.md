# S094 原子任务清单（task）

> 状态图例：`[ ]` 待做 / `[x]` 完成 / `[~]` 过渡态（部分落地，余延后）。feature 分支 `feature/S094-战法分类与双pipeline重构`。
> 测试基线：后端 2215 passed（1 pre-existing S066 归档债）+ 前端 428 passed。
> 阶段与 spec §10 / plan.md 同步（ora-6 B4 重排）。

## S0 前置硬门：gene_scores 错位修复（S095）——✅ 已闭合
- [x] T0a 写路径守卫：`_assert_not_future_date` 未来日期硬闸门（`_compute_and_cache_async`/`precompute_daily_async`/`precompute_daily` 三入口，拒写不查东财）+ `_cross_check_zt_history` final 快照交叉校验（commit a6618df）
- [x] T0b 历史行重算：08-13~08-14（fix-20，ac22bac）+ 08-17~08-21（fix-18），七日全覆盖 7/7 code 集合严格相等，双备份在 .vibe-research/
- [x] G0 守卫测试绿（S095 5 测试 AC1-AC5 全绿 + 全量 2225 passed）

## S1 统一 K线契约 + 因子层 + 权重源（R1-R5）
- [x] T1 `strategies/pattern_scan.py`：`_compute_ma(bars,n)` SMA n=5/10/20，bars<20 返 None
- [x] T2 `strategies/pattern_scan.py`：扩 `compute_shadow_length_pct(bars)=(high/close-1)*100`（复用 activity.py L112 先例）+ `compute_ma5_slope(bars)=(ma5[-1]-ma5[-2])/ma5[-2]`（ma5 用 T1 的 _compute_ma 算）
- [x] T3 `strategies/non_limitup_funnel.py` L242 传 `sector_bars`（板块全成分等权平均，停牌按日期对齐取交集），compute_relative_strength 真相对
- [x] T4 `strategies/non_limitup_funnel.py` 删 L48 NON_LIMITUP_WEIGHTS 硬编码
- [x] T5 `strategies/impl/indicator_based.py` PatternReversal 改读 PatternScan（shadow_length_pct/volume_breakout_ratio/ma5_slope）；5 因子→3 字段删减声明 + 放量口径变更（今量/前5日均量≥1.2）+ "突破昨日最高"作废
- [x] T6 **R4 不委托**——`compute_volume_signal_score` L86-120 按战法分支逻辑迁入对应 Strategy.match()（dragon_head/plat_breakout/low_absorption/reverse_package 各自的量能阈值），match 返回时填 signals 的 confidence/signal_strength
- [x] G1 commit 门：统一 K线+因子+权重+match 下沉测试绿

## S2 候选生产拆分 + sector_rank（R11/R14/R27）← ora-6 重排
- [x] T7 `strategies/market_scan.py`（新建，§3.M 定稿归属：因子层+领涨子单一事实源）：`compute_sector_stock_rank` + 批量 `compute_sector_stock_rank_map` 板块内 relative_strength 降序排名（commit 773d100）
- [x] T8 R14 FLOW B 候选扩 {code,name,bars,sector,sector_rank,close}——`build_non_limitup_candidates` 从端点抽到 market_scan（name←code_industry 反查, sector_rank←板块内 T7 基于全成分非 per_sector 采样子集, close←bars[-1]）（commit ab82a68）
- [~] T9 **过渡态**：run_non_limitup_funnel 透传 {name,sector_rank,close} + local 板块间 rank 改名 sector_strength_rank 拆同名歧义（commit 78dc573）。**未完延 S3**：删 compute_non_limitup_score 自打分 + score_candidates market_scan 分支——耦合 S3 T11(funnel_type 必填)+T16(端点改 score_candidates market_scan)，届时一起切（opencode S1 同款过渡双机制，保端点不破）
- [x] G2 commit 门：候选生产+sector_rank 测试绿（全量 2254 passed；2 failed = S066 pre-existing + test_s032 flaky-timing[单跑 pass,非 S2 回归]）

## S3 StrategyContext + match 分流 + confidence + 接线（R6-R13/R26/R28）
- [x] T10 StrategyContext 加 market_scan_ctx（S1 加字段 strategy_base:60 + 2a-i score_candidates market_scan 分支构造填充）
- [x] T11 score_candidates 加 funnel_type 必填 + STRATEGIES_BY_FUNNEL_TYPE 分流（commit 7f7c026）
- [x] T12 既有调用传 funnel_type=limitup（workflow._collect L222 / scheduled_tasks L1605 / forward_test L491；pre_market_workflow 走 StrategyMatcher 不调 score_candidates，确认删）（commit 7f7c026）
- [x] T13 DragonHead.match 删无条件放行→读 market_scan_ctx.sector_rank≤3（commit f9df2c5；6 消费方无 market_scan_ctx→永不命中 R9 声明，test_s031/test_s086 更新）
- [x] T14 R10 3 战法 match 改 PatternScan（pattern_reversal S1 T5 + low_absorption/platform_breakout 2a-ii commit 2ec7b8d；reverse_package 保留 db_based）
- [x] T15 score_candidates 复用 dispatch_match confidence/signal_strength（commit 602a1b0；opencode S1 已留 sig_by_code+volume_signal，补 confidence/signal_strength）
- [x] T16 端点 /api/strategy/non-limitup-funnel 切 run_non_limitup_funnel(只产候选)→score_candidates(market_scan)（commit 83dd6dc）
- [x] T17 后端 wiring done（R26 gather + R28 briefing 透传；**backend half，frontend 分区消费=T23**）：`market_scan.gather_non_limitup_candidates(date)` 新建（抽自 routers/strategy.py 端点，懒 import 防循环）+ `workflow._collect` 调它产 `market_scan_scored` + 5 处 thread（`_cache.update`/`_save_snapshot`/GET done resp/GET snap resp，镜像 scored_candidates）。验证 py_compile+31 workflow tests+gather empty-path 3 tests。**数据依赖 T21-run**（全 A cache 未扩容前 market_scan_scored 恒空，诚实降级非臆造）。
- [x] G3 commit 门：分流+confidence+接线测试绿（全量 2264 passed，仅 S066 pre-existing）

## S4 5 根因修复（R16-R20）
- [x] T18 zt_real 端到端落库（f3500a0）：_emotion 加 zt_real 字段（latest 从 `_sentiment(resolved)` 拉，history None；critical 传 resolved 日期别裸调 _sentiment 防 P0-1/2 日期错配）+ sti_timeline 加 zt_real 列（新 20260823-001 **ALTER-only 不碰 v1 CREATE**，镜像 raw_break_rate 先例 + `limitup_sti/__init__` import-time 接线）+ **compute 从 sentiment_data 提 zt_real 落库**（非改 scheduled_tasks——它已 L678 调 _sentiment 传 compute，T18 是 wire compute 丢的 zt_real）+ `save_result` INSERT 加列(16→17) + `_market_emotion_from_ctx`/fallback readback（raw 不 /100）——保留 zt_count 不动。验证：fresh-DB PRAGMA zt_real+raw_break_rate 落地 + targeted 44 passed（s063/s049/weather_history/s060）。**前提修正**（5 触点核实）：原"_execute_sti_post_market 存 zt_real"不准（compute 丢 zt_real）；"schema 加列"是 ALTER-only 非 v1 CREATE。
- [x] T19 sector-rotation date 默认 done（backend f11866f：date=None→last_trading_date_str）+ 前端 ContextTab date=F **判为正确**（spec 的 triplet.today 反而错：历史复盘 F=过去日 D 时,板块轮动应显 D 日；triplet.today=今日会错位。date=F 是前瞻 Tab ContextTab 的正确选择,spec 此条指向不准）
- [x] T19a R17 no-op 核实（test_s094_t18_zt_real_readback 5 passed）：`_collect` 本来就在 L152 调 `_fetch_market_emotion` 重算 market_emotion，`refresh_pre_market` POST 本来就在 L668 起 `_collect`；T18 step 6 已让 `_market_emotion_from_ctx` 从 STI DB 读 zt_real（raw 不 /100）。R17 描述的"refresh 调 _collect 重算"是既有行为，T18 接通读路径后即满足——**无需额外生产代码**。验证：zt_real=42→out 42.0（raw 非 0.42）/ 历史行 NULL→None / 无行→default None / fallback 透传 emo.zt_real。
- [ ] ~~T20 `sector_divergence.py` R19 砍掉~~（ora-7 N5：前端已弃用，无消费方值得保留）
- [x] T21 kline cache 全 A 扩容 done（**代码+run 均 done**）：① perf 修 `routers/strategy.py:273` 每请求 json.loads → 复用 `first_board_filter._get_kline_cache` 模块级 memo（删未用 `import json`/`resolve_data_dir`）② 刷新脚本 `backend/tools/refresh_kline_cache.py` universe 从 `list(cache.keys())` 增量 → `load_industry_map()` 全 A；新股从 `FULL_START=2025-12-25` 全量拉。perf 选 memo 非 sqlite/parquet。验证 py_compile+import smoke+test_non_limitup_funnel 28 passed。**run done（19min,非 2-3h）:5222 股 / 145MB cache / 648652 new bars / newest=2026-08-21**——非涨停 funnel 从此有真 kline 数据,market_scan_scored 不再恒空。
- [ ] ~~T22 R21 合并到 T1~~（ora-6 非阻断 #3：与 R1 重复）
- [x] G4 commit 门：5 根因修复测试绿（T18/T19/T19a/T21 done + 全量 2269 passed 0回归）

## S5 前端 UI（R22-R25）
- [x] T23 双 pipeline R28 数据 wiring + R22 上下分区布局 done：briefing.market_scan_scored 串到 CandidateFunnelEmbed→SelectionPipeline→NonLimitupLane（candidates prop）+ NonLimitupLane 修 c.score→c.strategy_score（T26）。R22：SelectionPipeline fork 从 grid-cols-2 side-by-side 改 vertical + 非涨停叉包 CollapsibleFold(defaultOpen=false)（涨停叉主展开/非涨停折叠）。R23 卡片流转顺序已对。R25 仓位摘要截断 done（T25）。验证 tsc+vitest 60 passed。
- [x] T24 StrategyMatchMatrix 涨停/非涨停分区 done（R24）：读 `briefing.scored_candidates` + `market_scan_scored`，提取 `ScoredRegion` 子组件渲染两 region（涨停战法 / 非涨停战法 §44 未验证），共享 matrix/byStrategy 双视图 + AskAi context 合并两 pipeline。验证 tsc 无错 + vitest 127 passed。
- [x] T25 UI bug 修（**5/5 done**）：① 定稿失配（CandidateFunnelEmbed 传 final_candidates→SelectionPipeline FinalCandidatesNode，原恒空）② 仓位摘要截断（Workflow.tsx advisory 行 truncate+min-w-0）③ 验证对齐（VerificationCardBlock note 对齐 S060 spec）④ 代码2次（NonLimitupPlaceholder {c.name||c.code}+{c.code} 当 name 空 fallback 成 code=显两次→改 {c.name}；R25 标签说 SectorCyclePanel 不准,真 bug 在非涨停叉）⑤ P2判据（S096 落地：backend _format_p2_fired_rule 算 fired_rule 红期override+数据降级；p2_factors+p2_fired_rule 透传 briefing；P2RiskPanel 显完整链+big_loss 永久降级注）。验证 py_compile+46 backend+tsc+127 frontend。
- [x] T26 `NonLimitupPlaceholder.tsx` R13 对齐新 schema（c.score→c.strategy_score）+ NonLimitupFunnelResult type score→strategy_score（T23 一并落地）
- [x] G5 commit 门：UI 测试绿（vitest 428 passed + tsc clean + vite build ✓ 22.56s；R22+R24+T23+T26 零回归）

## S6 全量回归 + playwright
- [x] T27 pytest + vitest + tsc + vite build 全绿（G4 backend 2269 passed 0回归 + G5 frontend 428 passed + build ✓）
- [~] T28 e2e partial（s093-three-view PASSED——S094 前端改 R22/R24/T23 无回归；6 failed = 数据态(fresh 后端无 briefing collection→idle/no_snapshot 断言 fail)+ 预存 extreme_market detector unavailable(非 S094,extreme_market_detector 返 None)）。**full e2e 需**:briefing collection(POST /refresh 触发 _collect,重网络分钟级)+ extreme_market detector fix(预存,out of S094 scope)。新后端 PID 72884 在跑。G4+G5 是可靠 S094 回归门。
- [ ] T29 验收收拢（task 勾选 + spec 状态 + 归档）
- [ ] G6 验收门

## 依赖
S0(前置硬门) → S1(因子层) → S2(sector_rank 前置) → S3(分流+接线) → S4(根因，可并行) → S5(前端) → S6(回归)
