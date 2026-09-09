# Tasks v2: S175 — 模拟盘自洽闭环（spec grill 后对齐 spec v2）

> spec v2（2 CRITICAL+7 HIGH 全修）后的可执行 checklist。v1 的 R6"+3行"/R3 无截断/R4 无 _latest_close/R9 无 equity sizing/R11 未 deferred/R14 real_cost_pct 全纠正。每条带依赖序+验收点，TDD。

## P0 — 最小可跑闭环（~200-210 行）

- [x] T1 **bars_provider 双源 + ETF bar 规范化**（已实现 v2 GREEN 9 tests）
  - [x] T1.1 test_bars_provider.py：A股 cache OHLC / ETF fetch_etf_hist mock / ETF 规范化补 open/high/low=close / 多 bar + 坏 bar 过滤 / unknown [] / 降级 / reload / 损坏 cache（9 tests pass）
  - [x] T1.2 engine/bars_provider.py：composite KlineCacheBarsProvider（A股→resolve_data_dir cache，ETF→fetch_etf_hist + 规范化 {open:close,high:close,low:close}）+ reload()
- [ ] T2 **accounting PathReturn exit_price（三分支）**（无依赖，SH7）
  - [ ] T2.1 写 test：path_return stop 分支 exit_price=entry*(1+stop/100)；take=entry*(1+take/100)；max_hold=bars[exit_idx].close；三分支均 != entry_price（RED）
  - [ ] T2.2 engine/accounting.py：PathReturn dataclass 加 `exit_price: float = 0.0`；stop（:148）/take（:156）/max_hold（:174）三分支构造均设 exit_price（:165 已算 max_hold，补 stop/take）。注：R6 覆写 S173 journal_recorder:24 只读约束（S175 架构演进）
  - [ ] T2.3 验收：test pass + 既有 path_return 测试不破
- [ ] T3 **journal_recorder settle_pending + 截断 max_hold + signal_id bypass + _latest_close + 3 fix**（依赖 T1+T2，SH2/SH5/SH7）
  - [ ] T3.1 写 test：(a) settle_pending 查 is_realized=0 'hold' → bars 增长后重算 → INSERT OR REPLACE **同 signal_id**（非新 UUID）更新 is_realized=1 + net_pnl 非 None + exit_price != entry_price；(b) **截断 max_hold exit**（exit_idx==len(bars)-1，bars 不足完整持仓期）留 hold 不标 realized；(c) _latest_close(target_date='2026-09-01') 只返 date<=target_date 的 close（非 reversed 最后，防前视）（RED）
  - [ ] T3.2 `JournalRecorder.settle_pending_breakout()`：query is_realized=0 is_dead_arm=0 arm='breakout' → Python filter exit_reason=='hold'（query_records 无 exit_reason 参数）→ per pos bars_provider 取 bars → 构造 Trades(entry_price=pos.entry_price, fill_status=FILL_ACCEPTED, 不走 Executor) → path_return(apply_cost=True) → **若 pr is not None 且非截断**（pr.exit_reason=='max_hold' 且 exit_idx==len(bars)-1 → 截断，留 hold）：**直接构造 `JournalRecord(signal_id=pos.signal_id, ...)` 绕过 .create()**（.create() :94 生新 UUID，无法 INSERT OR REPLACE 同 id；传 signal_id kwargs 会 TypeError）→ INSERT OR REPLACE（GREEN）
  - [ ] T3.3 `_latest_close(bars, target_date=None)` 加 target_date 参数：返 bars 中 date<=target_date 的最后一根 bar close（非 reversed 最后）；target_date=None 时不限（仅生产当日跑安全）。_process_floor（:274）+ update_floor_mtm（:317）传 target_date
  - [ ] T3.4 run_daily 默认 target_date 改 `prev_trading_date_str()`（:91 从 last_trading_date_str 改，C5 fix；不只 executor 传参）
  - [ ] T3.5 _process_floor :240 `etf_code="510300"` → `from strategies.index_replication_floor import ETF_CODE`（R5，C1）
  - [ ] T3.6 _process_breakout :193 `exit_price=position_notional/DEFAULT_SIZE` → `exit_price=pr.exit_price`（R6）
  - [ ] T3.7 run_daily 开头调 settle_pending_breakout()（在 _process_* 之前）
  - [ ] T3.8 验收：test_journal_recorder settle_pending（截断留 hold + signal_id bypass）+ _latest_close target_date 测试 pass + 既有 11 测试不破
- [ ] T4 **scheduler 接线**（依赖 T3）
  - [ ] T4.1 建 backend/scheduler/executors/journal.py：trade_journal_daily(payload) → JournalRecorder(bars_provider=KlineCacheBarsProvider()) → settle_pending_breakout() → run_daily(target_date=prev_trading_date_str(), arms=['floor','breakout']) → update_floor_mtm(target_date=prev_trading_date_str())
  - [ ] T4.2 scheduler/executors/__init__.py _executors dispatch 加 trade_journal_daily + thin wrapper（仿 data_ops/backtest 域文件范式，P6 后结构）
  - [ ] T4.3 scheduler/seed.py 加 cron `45 16 * * 0-4` trade_journal_daily（create_task 幂等）
  - [ ] T4.4 验收：POST /api/scheduler/run task_type=trade_journal_daily 返 {settled_pending, arms, floor_mtm} + trade_journal.db 有记录
- [ ] T5 **frontend §44-falsified 横幅 + 降 LEVEL_META + Disclaimer/footer 三处 posture 一致**（无后端依赖，SH4）
  - [ ] T5.1 Recommendation.tsx 顶部加 §44-falsified 警告横幅 **+ 降 LEVEL_META "高质量关注" 绿色为灰/改标"§44证否·基因分" + 每条推荐卡加 per-item §44-falsified 标**（非只加横幅留矛盾徽章）
  - [ ] T5.2 components/ui/Disclaimer.tsx（SC2 修路径）compact(:8)+full(:16) 删"不推荐个股/不预测涨跌/不给买卖时机/不构成投资建议"→保留"历史统计特征，市场有风险"轻量提醒
  - [ ] T5.3 components/layout/Layout.tsx（SC2 修路径）:161 footer "不荐股·不预测·无倾向"→"模拟盘跟踪·真盘你定"
  - [ ] T5.4 Recommendation.tsx:52 subtitle "基于基因得分的教育研究式关注清单（非交易建议）"→多臂措辞（"多臂模拟推荐·各臂标验证状态·真盘你定"）— 三处 posture 一致=谋士
  - [ ] T5.5 验收：`npx tsc --noEmit` 零错误 + 浏览器 Recommendation 显横幅+降徽章+改 subtitle + footer/Disclaimer 改
- [ ] T6 **P0 e2e 集成验收**（依赖 T1-T5，SH3）
  - [ ] T6.1 建 tests/test_s175_e2e.py：mock bars_provider（A股 mock bars + ETF 512890 mock bars **含 open/high/low/close 延伸到 T+2+max_hold**），连调 run_daily 3 次（target_date 递进 T-1/T/T+1）+ settle_pending_breakout，断言 DB 有 floor 512890（unrealized_pnl 非 None，_latest_close target_date 过滤无前视）+ breakout is_realized=1（net_pnl 非 None，exit_price != entry_price，截断 max_hold 留 hold）
  - [ ] T6.2 验收 A1：test_s175_e2e pass（离线 mock，不走 akshare）
  - [ ] T6.3 验收 A2：aggregate_by_arm('breakout') 非 empty（n_picks>0）+ floor aggregate 恒 empty by design（floor is_realized=0）+ floor MTM 非 None
  - [ ] T6.4 验收 A8：trade_journal.db 写 .vibe-research/，不进 git

## P1 — 多臂推荐 + PaperPortfolio（R9↔R10 接线）+ 诚实 UI

- [ ] T7 **recommendation_engine 多臂 + 读 equity sizing**（依赖 T6 数据，SH1）
  - [ ] T7.1 写 test：多臂 RecommendationEngine 返 floor actionable（**含 equity_derived_sizing 字段，读 PaperPortfolio.equity()**）+ breakout §44_falsified + gap dead_arm gate + limitup/trend mock_not_ready（RED）
  - [ ] T7.2 rework backend/recommendation_engine.py（**root 非 strategies/，SC2**）：gene-only→多臂。floor=build_position_batches + **仓位 sizing 读 PaperPortfolio.equity() × floor_allocation / N batches（R9↔R10 接线，非空转）**；breakout=§44_falsified·盘中 conditioning 未测；gap gate is_dead_arm=1；limitup/trend mock_not_ready。诚实承认 3/4 槽位是静态标签（GREEN）
  - [ ] T7.3 routers/recommendation.py 加 GET /api/recommendation/multi-arm
  - [ ] T7.4 验收 A4+A5：返 floor actionable + equity_derived_sizing + 其它 honest_label（breakout=§44_falsified 非 weak）
- [ ] T8 **PaperPortfolio（R9 消费）+ drawdown_breaker 接 executor**（依赖 T6，SH1；R11 overlay deferred）
  - [ ] T8.1 写 test：PaperPortfolio.equity() 返 initial+cum_realized+unrealized（委托 trade_journal.equity_curve + drawdown_breaker.full_status 不存独立 state）（RED）
  - [ ] T8.2 建 backend/engine/paper_portfolio.py（~80 行）：thin read-only wrapper，委托 trade_journal.equity_curve() + drawdown_breaker.full_status() + final_size()（GREEN）
  - [ ] T8.3 scheduler/executors/journal.py executor 末尾加 PaperPortfolio.equity() 落盘 + drawdown_breaker.compute_drawdown()（从 API 层移生产，1 行；**overlay stub/EWMA/MAB deferred**）
  - [ ] T8.4 验收 A5：executor 末尾 PaperPortfolio.equity() 返非 initial_capital（mock bars 非 0 MTM/PnL）；R9 读 equity sizing（A4 联动）
- [ ] T9 **JournalLedger honest 标签 + dormant 臂 stub + 推荐面板（删旧 gene 卡）**（依赖 T7+T8）
  - [ ] T9.1 lib/journal-contract.ts **新建 ArmAggregate 类型含 s44_verdict**（非"加字段"，类型不存在）+ FollowDecision 类型；lib/api.ts StockRecommendation type 更新（多臂无 gene_score）
  - [ ] T9.2 routers/journal.py closed-loop 端点返 dormant 臂 stub 条目（{arm, honest_label, zero_data:true}，非前端硬编码）+ 关联 s44_verifier Recorder arm→verdict
  - [ ] T9.3 JournalLedger.tsx ArmStatCard 加 verdict badge + dsr_method 标（lenient_single_estimate→"宽松估计"，N/A→"不适用"）+ mock 标识（解析 fills_json.mock）+ Sharpe n<60 标"未年化"（显 sharpe_n_days）+ underpowered 顶置 + **cap 标签**（"lift cap 未接 trade_journal sizing 路径"）+ **保留现有 coverage_rate/unbuyable/Wilson CI** + dormant 臂 stub 灰卡
  - [ ] T9.4 JournalLedger.tsx 顶部 PaperNotRealBanner（静态警告 + 动态跟单 gap 占位）
  - [ ] T9.5 Recommendation.tsx/Journal.tsx **删旧 /api/recommendation/today gene 卡 + LEVEL_META，替换为多臂面板**（非并存，SH4）+ floor 批次推荐面板（actionable：512890+批次序号+金额+日期+"可选实盘小仓位"）+ 其它臂 honest 状态卡
  - [ ] T9.6 验收 A3：JournalLedger 显 verdict/dsr/mock/横幅/cap/dormant stub + 保留 coverage/CI；Recommendation 删旧 gene 卡换多臂面板

## P2 — 跟单 flow（R14）+ 4 源 gap（R15-R17 永久 dormant）

- [ ] T10 **follow-order API（per-fill fees）+ gap 计算**（依赖 T7 signal_id，SH）
  - [ ] T10.1 写 test：POST follow-order {signal_id, fills:[{side,date,price,shares,fee?}]}（per-fill fees 匹配 S166 Fill.fee 非 real_cost_pct）→ 算 paper-vs-real gap；dormant 状态返 {status:'dormant', label:'激活条件当前不可达'}（RED）
  - [ ] T10.2 backend/journal.py add 入口（routers/journal.py:104 journal_add + journal.py _save/_load_raw）加 signal_id 关联（S166 手动账本扩展，C7 隔离 winrate.db）
  - [ ] T10.3 routers/journal.py 加 POST /api/journal/follow-order + GET /api/journal/gap（不改 18 现有端点）。4 源 gap（unbuyable/滑点/T+1/成本）结构建好，**诚实标激活条件当前不可达**（breakout falsified 不会 validated，floor 无 4 源问题，永久 dormant 除非 validated 盘中臂）（GREEN）
  - [ ] T10.4 验收 A6：A6a dormant（无 follow → gap 返 dormant 标签）；A6b active（POST follow 关联 breakout is_realized=1 → gap 返 4 源分解，依赖 A1）
- [ ] T11 **FollowDecisionModal + FollowOrderGap 组件**（依赖 T10 API）
  - [ ] T11.1 FollowDecisionModal（"你来定"+纸面≠真盘横幅+用户自报成交价表单 **+ 成本计算器引导**：输入佣金率/免五/印花→算 cost_pct，散户易错）不下单
  - [ ] T11.2 FollowOrderGap 组件（复用 JournalLedger 模式，每笔跟单显 4 源 gap + 总 gap；未跟单显"未跟单"；dormant 显"激活条件不可达"）
  - [ ] T11.3 推荐卡加"跟单（真盘你执行）"按钮 → FollowDecisionModal
  - [ ] T11.4 验收：跟单按钮 → modal → 自报成交价 → GET gap → FollowOrderGap 渲染 4 源分解

## 全量验收（P0-P2 完成后）

- [ ] V1 `cd backend && .venv/bin/python -m pytest tests/test_s175_e2e.py tests/test_journal_recorder.py tests/test_bars_provider.py tests/test_trade_journal.py tests/test_aggregate_stats.py tests/test_drawdown_breaker.py -v --no-cov` 全绿
- [ ] V2 `cd backend && .venv/bin/python -m pytest -m "not live" --deselect tests/test_newsradar.py::test_fetch_global_intel_wm_import_fails --no-cov` 全绿（newsradar/s040/s032 deselect，memory flaky）
- [ ] V3 `cd frontend && npx tsc --noEmit` 零错误
- [ ] V4 TestClient 验收端点：GET /api/recommendation/multi-arm + POST /api/journal/follow-order + GET /api/journal/gap + GET /api/journal/closed-loop + GET /api/journal/drawdown-status
- [ ] V5 test_s175_e2e mock 3 天 → trade_journal.db 有 floor+breakout 真记录 + JournalLedger 显 verdict/badge/横幅/cap + 推荐面板 + 跟单 flow
- [ ] V6 commit（pathspec 显式 `git commit <files>`，memory git-commit-no-pathspec-sweeps-staged）+ 落 memory `s175-impl-done`

## Deferred（spec grill + 用户未拉回）

- §44 R3 enforce 自动复验（C3，DIMENSION_LIFT_REGISTRY 静态，0 可毕业臂）
- **R11 portfolio overlay 接口骨架 + EWMA/MAB/SRTS impl**（spec grill：stub 无 consumer 无 impl=纯 YAGNI；drawdown_breaker 接 executor 1 行留 P1；overlay 全 deferred 待 ≥2 validated 臂 + 60d vol）
- conditioning harness 作数据收集器（写盘中 OFI 到独立 intraday store，非喂 trade_journal）
- ash-mcp B 臂（gh-proxy clone + smart-beta capped）
- /trade-desk cockpit + SplitLayout + nav 5→7（page-architecture-redesign 独立 spec）
- 多臂 signal 生成器（打板 conditioning / 趋势 7 维 / limitup hithink wire）
