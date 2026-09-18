# Tasks: S173 — Trade Journal 闭环

> spec → plan → tasks（SDD §0 不跳）。可执行 checklist，每条带依赖序 + 验收点。

## Phase 1: trade_journal.py（ledger + 统计方法论层）

- [ ] T1.1 建 `backend/engine/trade_journal.py`：JournalRecord dataclass（frozen，spec §5.2 schema 全字段）+ TradeJournal 类（SQLite CRUD）。db_path 默认 `vr_paths.resolve_data_dir() / "trade_journal.db"`。
  - 验收：JournalRecord 字段 == spec §5.2 表 schema；db 存 `.vibe-research/`
- [ ] T1.2 迁移幂等：`_ensure_table()` v1 完整 CREATE（memory `migration-stubs-fresh-db-fix`：不做桩）+ 2 个 index（idx_tj_arm / idx_tj_entry_date）+ `__init__` 接线调 `_ensure_table()`。
  - 验收：fresh DB 建表幂等（跑 2 次不报错）
- [ ] T1.3 CRUD：insert(JournalRecord)→signal_id / update_unrealized(signal_id, pnl, price) / query_records(arm, is_realized, is_dead_arm, limit)。
  - 验收：insert→query 往返一致；update_unrealized 改 unrealized_pnl 不改其他字段
- [ ] T1.4 统计方法论层：`_wilson_ci(wins, total)` + `_daily_aggregate_sharpe(net_pnls, exit_dates)`（H2 日聚合年化）。
  - 验收：wilson_ci 空输入不崩；daily_aggregate_sharpe 先日聚合再 ×sqrt252
- [ ] T1.5 跨臂聚合 `aggregate_by_arm(arm)`：调 `day_clustered_t_test` + `compute_dsr` + `bonferroni_bh` + `compute_haircut` + wilson_ci + coverage_rate（H8 三指标）。is_dead_arm=1 不混入。underpowered gate（H1：n<30 或 days<60→status='underpowered' 不出 kill）。SQLite query 不读结果 cache（memory s088）。
  - 验收：mock records→aggregate 产出 winrate/Sharpe/净超额/coverage_rate/execution_winrate；dead_arm 不混
- [ ] T1.6 equity_curve(arm)：initial_capital + cumulative(realized + unrealized MTM)，遵循 risk_rules.equity_curve 绝对 CNY 回撤模式（C4/C6）。
  - 验收：含 unrealized 的 floor 臂 equity 可见（A10）

## Phase 2: drawdown_breaker.py

- [ ] T2.1 建 `backend/engine/drawdown_breaker.py`：DrawdownBreaker 类 + DrawdownResult dataclass。
  - 验收：DrawdownResult 字段含 status/is_bear_market/days_tracked
- [ ] T2.2 `compute_drawdown(arm)`：equity=initial_capital+cum(realized+unrealized)，drawdown_cny=peak-current，drawdown_pct=drawdown_cny/initial_capital（C4 绝对 CNY 非 (peak-current)/peak）。
  - 验收：mock equity 曲线→DD 算对，不 20x 膨胀
- [ ] T2.3 `size_multiplier(arm)`：per-arm DD>10%→0.5, >15%→0.0；floor 豁免 per-arm DD（C5 仅参与 portfolio aggregate）；underpowered gate（H4 days<60→1.0 underpowered）；熊市 regime（H6 CSI300<200日线→floor 豁免）。
  - 验收：floor per-arm DD 不触发（A4）；days<60→underpowered multiplier=1.0
- [ ] T2.4 `final_size(arm, arm_size, lift_multiplier)`：H5 三层乘积 arm_size × portfolio_multiplier × lift_multiplier。
  - 验收：三层乘积算对

## Phase 3: journal_recorder.py（orchestrator）

- [ ] T3.1 建 `backend/strategies/journal_recorder.py`：JournalRecorder 类。__init__ 接 TradeJournal + Executor。
  - 验收：可独立实例化（依赖注入可 mock）
- [ ] T3.2 `_process_breakout(target_date)`：import select_premarket_candidates→candidates→构造 Trades（C8 不带 signal_id/arm）→Executor.execute(T1OpenFill)→涨停买不到标 unbuyable→path_return(apply_cost=True)→PathReturn→net_pnl=return_pct/100×notional(CNY)→insert(is_realized=1)。
  - 验收：4 步顺序管线走通；Trades 不带 signal_id/arm（C8）；survivorship 过滤（A5）
- [ ] T3.3 `_process_floor(target_date)`：import build_position_batches→ETF batches→构造 Trades→Executor.execute→exit_reason='hold'→MTM 分轨 unrealized_pnl→insert(is_realized=0)。
  - 验收：floor 走 MTM 不走 path_return（C3/C6）；exit_reason='hold'（A10）
- [ ] T3.4 `_process_gap(target_date)`：mock signal→gap_net_return→(net_ratio,cost_pct,gross_ratio)→net_pnl=net_ratio×notional→insert(is_realized=1, is_dead_arm=1)。
  - 验收：gap 走 gap_net_return 不走 path_return；is_dead_arm=1
- [ ] T3.5 `run_daily(target_date, arms)`：orchestrator 顺序调各臂（C1 非订阅）→返 {arm: {n_candidates, n_buyable, n_unbuyable, n_realized}}。
  - 验收：orchestrator 模式非订阅；4 臂可录到 trade_journal（A1）
- [ ] T3.6 `update_floor_mtm(target_date)`：每日盘后按 ETF close 重算 floor unrealized_pnl（C6）。
  - 验收：unrealized_pnl 随 close 更新
- [ ] T3.7 H7 gap-aware fill 文档化：fills_json 记 optimism_flag + raw exit_price（不改 accounting.py 接口）。
  - 验收：fills_json 含 optimism_flag 字段

## Phase 4: 前端

- [ ] T4.1 `frontend/src/lib/journal-contract.ts` 小改：加 ClosedLoopResponse / DrawdownStatusResponse 类型。
- [ ] T4.2 `frontend/src/lib/api.ts` 小改：加 journalClosedLoop() / journalDrawdownStatus()。
- [ ] T4.3 `frontend/src/lib/query/journal.ts` 小改：加 useClosedLoop() / useDrawdownStatus() hooks。
- [ ] T4.4 `frontend/src/components/journal/JournalLedger.tsx` 新建：持仓+unrealized MTM+归因+coverage_rate，error boundary 降级。
- [ ] T4.5 `frontend/src/pages/Journal.tsx` 小改：挂 JournalLedger section（新 tab "闭环"）。
  - 验收：挂现有 Journal.tsx 页内，渲染持仓+归因（A9）

## Phase 5: 后端路由

- [ ] T5.1 `backend/routers/journal.py` 小改：加 GET /api/journal/closed-loop + GET /api/journal/drawdown-status。不覆盖现有 16 端点。
  - 验收：新端点返聚合统计 + drawdown 状态

## Phase 6: 测试

- [ ] T6.1 `backend/tests/test_trade_journal.py`：CRUD + 迁移幂等 + is_dead_arm 不混聚合 + MTM unrealized 更新。
- [ ] T6.2 `backend/tests/test_aggregate_stats.py`：day_clustered_t_test + bonferroni_bh + compute_dsr + CI + underpowered gate（n<30 标 exploratory）。
- [ ] T6.3 `backend/tests/test_journal_recorder.py`：mock 4 臂 signal 生成器→全录到+survivorship+Trades 不带 signal_id（C8）+orchestrator 顺序管线。
- [ ] T6.4 `backend/tests/test_drawdown_breaker.py`：mock equity→DD 阈值+floor 豁免+underpowered+熊市+三层乘积。
- [ ] T6.5 全量 `pytest -m "not live" --deselect tests/test_newsradar.py::test_fetch_global_intel_wm_import_fails --deselect tests/test_s032*.py::test_s032_refresh_loop --deselect tests/test_s040*.py::test_s040_backfill` 全绿。

## Phase 7: 验收

- [ ] T7.1 逐条核对 spec §6 A1-A11 + C1-C8 + H1-H9。
- [ ] T7.2 `git status` 确认 trade_journal.db 未进 git（A6）。
- [ ] T7.3 grep 确认 accounting/executor/decision/risk_rules/win_rate_tracker/settlement_recorder/journal.py 接口未改（A7）。
- [ ] T7.4 commit 前 `git branch --show-current`（develop）+ 显式 `git add <文件>` + `git commit <pathspec> -m`。
