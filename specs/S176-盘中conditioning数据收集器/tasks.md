# Tasks: S176 — 盘中 conditioning 数据收集器

> spec/plan 见同目录。TDD：先测试（RED）→ 实现（GREEN）→ 重构。每条带依赖序+验收点。

## P0 — 纯函数 + store（无外部依赖）

- [ ] T1 **OFI + bid_ask_pressure 纯函数**（无依赖）
  - [ ] T1.1 写 `tests/test_intraday_ofi.py`：compute_ofi(buy=[{vol:100},{vol:200},...], sell=[{vol:50},{vol:100},...]) = (300-150)/(300+150) = 0.333；bid_ask_pressure = Σbuy/Σsell = 300/150 = 2.0；sell=0 → pressure=999.0 cap + OFI 退化（RED）
  - [ ] T1.2 建 `engine/intraday_ofi.py`（~40 行）：`compute_ofi(buy_levels, sell_levels)` 归一化 ∈[-1,1] + `compute_ofi_abs`（绝对值）+ `compute_bid_ask_pressure(buy, sell)`（sell=0 cap 999.0）；纯函数无 IO（GREEN）
  - [ ] T1.3 验收：test pass + 纯函数无 IO
- [ ] T2 **intraday_accumulation_store extend ofi_snapshots**（无依赖）
  - [ ] T2.1 写 test：save_ofi(code, time, ofi, pressure, buy_vols, sell_vols, seal_amount, regime) → load_ofi(start, end) 返记录（RED）
  - [ ] T2.2 `data/intraday_accumulation_store.py` 加 `_SCHEMA_OFI`（CREATE TABLE intraday_ofi_snapshots: code/date/time/ofi/ofi_abs/bid_ask_pressure/buy_vols_json/sell_vols_json/seal_amount/regime）+ `save_ofi` + `load_ofi`（同 save_quote 范式）；_ensure_table execute _SCHEMA_OFI（GREEN）
  - [ ] T2.3 验收：test pass + 既有 store 表不破
- [ ] T3 **封单诚意 3 纯函数**（复用 compute_trajectory，无依赖）
  - [ ] T3.1 写 test：compute_seal_delta_ratio(snapshots) = net_delta/first；compute_seal_volatility = std/mean；compute_seal_drawdown = (peak-current)/peak（RED）
  - [ ] T3.2 `strategies/intraday_features.py` 加 3 纯函数（~40 行，复用 compute_trajectory seal_delta/max/min/slope + SealTrajectory）（GREEN）
  - [ ] T3.3 验收：test pass + 既有 compute_trajectory 不破

## P1 — 采集器（依赖 T1+T2）

- [ ] T4 **五档时序轮询采集器**（依赖 T1+T2）
  - [ ] T4.1 写 test：mock tencent._parse_gtimg 返五档 → collect_ofi(code) 算 OFI + pressure → save_ofi；tencent 返空/格式错 → 跳过该股不崩（数据质量门）（RED）
  - [ ] T4.2 建 `engine/intraday_ofi_collector.py`（~80 行）：`collect_ofi_for_codes(codes, store_path)` —— per code tencent._parse_gtimg → buy/sell levels → compute_ofi + pressure → save_ofi；缺失/异常跳过（GREEN）
  - [ ] T4.3 候选股池：从 first_board_filter 候选 dict（zt_pool 涨停）or premarket_candidates
  - [ ] T4.4 验收 A4：数据质量门（tencent 返空 → 跳过不崩，其他股正常写）

## P2 — scheduler executor（依赖 T4）

- [ ] T5 **ofi_collect executor + dispatch + cron**（依赖 T4）
  - [ ] T5.1 `scheduler/executors/intraday.py` 加 `ofi_collect(payload)`（仿 seal_intraday_collect）：取候选股池 → collect_ofi_for_codes → 返 {n_codes, n_collected, n_skipped}
  - [ ] T5.2 `scheduler/executors/__init__.py` _executors dispatch 加 ofi_collect + thin wrapper
  - [ ] T5.3 `scheduler/seed.py` 加 cron `* 9-14 * * 1-5` ofi_collect（盘中每分钟 9:00-14:59）
  - [ ] T5.4 验收：POST /api/scheduler/run task_type=ofi_collect 返 {n_codes, n_collected}

## P2 集成验收

- [ ] T6 **集成 + 不喂 trade_journal 隔离**（依赖 T1-T5）
  - [ ] T6.1 mock tencent 跑 ofi_collect → intraday_accumulation_store.ofi_snapshots 有记录（A2）
  - [ ] T6.2 不喂 trade_journal：ofi_collect 跑后 trade_journal.db 无新记录（A3，grep trade_journal in ofi_collect = 0）
  - [ ] T6.3 私有隔离：intraday_ofi 写 .vibe-research/（A6，不进 git）
  - [ ] T6.4 验收 A1：OFI 纯函数正确（0.333）
  - [ ] T6.5 验收 A5：封单诚意 3 纯函数单测过

## 全量验收（P0-P2 完成后）

- [ ] V1 `cd backend && .venv/bin/python -m pytest tests/test_intraday_ofi.py tests/test_intraday_features.py -v --no-cov` 全绿
- [ ] V2 `cd backend && .venv/bin/python -m pytest -m "not live" --deselect tests/test_newsradar.py::test_fetch_global_intel_wm_import_fails --no-cov` 全绿（无回归）
- [ ] V3 手动：盘中跑 ofi_collect → intraday_accumulation_store.ofi_snapshots 有记录 + trade_journal.db 无新记录
- [ ] V4 commit（pathspec 显式）+ 落 memory `s176-impl-done`

## Deferred（非 S176 范围）

- conditioning lift harness（regime 分层 §44v2 验证）——等 60 天 live 数据后另起 spec
- L2 逐笔撤单方向（免费不可得，需付费）
- intraday OFI 前端 dashboard（read-only API + UI，可选后续）
