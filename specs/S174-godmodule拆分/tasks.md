# Tasks: S174 — 3 god-module 拆分

> 关联：`spec.md` / `plan.md`（同目录）

## Phase 1：scheduled_tasks.py 拆分（3076 行 → backend/scheduler/ 17 文件）

- [ ] T1.1 `cp backend/scheduled_tasks.py /tmp/scheduled_tasks.py.bak`（备份）
- [ ] T1.2 建 `backend/scheduler/__init__.py`（包入口）
- [ ] T1.3 建 `backend/scheduler/models.py`（`ScheduledTask` / `TaskRun` dataclass，L29-62）
- [ ] T1.4 建 `backend/scheduler/db.py`（`_DB_PATH` / `_get_connection` / `_ensure_tables` / `ScheduledTaskManager` / `_manager` / `_TASK_TIMEOUTS` / `_task_timeout` / `_REAPER_STALE_SECONDS` / `_SEAL_COLLECT_SUBPROCESS_TIMEOUT`，L20-25+63-372+469-495）
- [ ] T1.5 建 `backend/scheduler/snapshots.py`（`_save_snapshot` / `get_backtest_snapshots`，L373-466）
- [ ] T1.6 建 `backend/scheduler/notifications.py`（通知内容构建链 + `generate_daily_summary`，L2085-2428）
- [ ] T1.7 建 `backend/scheduler/cron.py`（`_cron_token_match` / `_cron_field_match` / `cron_match` / `_CRON_FIELD_BOUNDS`，L2461-2528）
- [ ] T1.8 建 `backend/scheduler/seed.py`（`_ensure_seed_tasks`，L2663-3072）
- [ ] T1.9 建 `backend/scheduler/cron_runner.py`（`CronScheduler` / `_scheduler` / `get_scheduler` / `start_scheduler` / `stop_scheduler` / `_TICK_INTERVAL`，L2537-2662+3074-3076）
- [ ] T1.10 建 `backend/scheduler/executors/__init__.py`（`TaskExecutor` 薄分发 + `execute` / `execute_async` / `_send_notification`，L496-657）
- [ ] T1.11 建 `backend/scheduler/executors/data_ops.py`（5 executor：daily_data_refresh / market_data_sync / cleanup_old_runs / kline_refresh / monthly_vacuum）
- [ ] T1.12 建 `backend/scheduler/executors/limitup.py`（5 executor：limitup_precompute / sti_post_market / zt_history_snapshot / st_play_radar / derived_precompute）
- [ ] T1.13 建 `backend/scheduler/executors/first_board.py`（3 executor：first_board_filter / first_board_t1_review / first_board_quote_probe）
- [ ] T1.14 建 `backend/scheduler/executors/premarket.py`（3 executor：premarket_auction_notify / premarket_open_notify / premarket_t1_review）
- [ ] T1.15 建 `backend/scheduler/executors/backtest.py`（5 executor：daily_backtest_run / s066_validation_checkpoint / evaluation_backtest / forward_test_daily / forward_test_t1_settle）
- [ ] T1.16 建 `backend/scheduler/executors/intraday.py`（4 executor：seal_intraday_collect / intraday_microstructure_snapshot / intraday_auction_dense / baostock_5min_freeze）
- [ ] T1.17 建 `backend/scheduler/executors/ai_portfolio.py`（4 executor：daily_ai_summary / portfolio_refresh / candidate_funnel_precompute / daily_review_notify）
- [ ] T1.18 建 `backend/scheduler/executors/kg.py`（2 executor：daily_kg_audit / daily_kg_sync）
- [ ] T1.19 `scheduled_tasks.py` → thin shim（re-export 全部公共名 + 4 个模块级 compat 包装）
- [ ] T1.20 改 `conftest.py`：`st._DB_PATH` → `scheduler.db._DB_PATH` / `st._ensure_tables()` → `from scheduler.db import _ensure_tables`
- [ ] T1.21 `py_compile` 全部新文件
- [ ] T1.22 `pytest -m "not live" --deselect tests/test_newsradar.py::test_fetch_global_intel_wm_import_fails --deselect "tests/test_s032_refresh_loop.py" --deselect "tests/test_s040_backfill_kline_cache.py"` 全绿
- [ ] T1.23 `git commit backend/scheduler/ backend/scheduled_tasks.py backend/conftest.py specs/S174-godmodule拆分/ -m "refactor(S174 P1): split scheduled_tasks.py (3076 lines) into scheduler/ package (17 files) with re-export shim"`

## Phase 2：first_board_filter.py 拆分（1702 行 → backend/strategies/first_board/ 6 子模块 + shim）

- [ ] T2.1 `cp backend/strategies/first_board_filter.py /tmp/first_board_filter.py.bak`
- [ ] T2.2 建 `backend/strategies/first_board/__init__.py`
- [ ] T2.3 建 `backend/strategies/first_board/universe.py`（`fetch_zt_pool` / `filter_first_board` / `_market_phase` / `_to_float` / `_fbt_to_hhmm` / `PHASE_TO_CAP_TIER` / `EXCLUDE_THRESHOLDS` / `MARKET_PHASE_WEIGHTS` + 模块级缓存）
- [ ] T2.4 建 `backend/strategies/first_board/data_extract.py`（`extract_chip_structure` / `_get_kline_cache` / `extract_sector`）
- [ ] T2.5 建 `backend/strategies/first_board/exclusions.py`（`exclude_layer1/2/3` / `_sector_zt_count` / `_market_drop_pct`）
- [ ] T2.6 建 `backend/strategies/first_board/scoring.py`（15 个 `score_dim*` / `_SCORE_DIMS` / `score_candidate` / `rank_candidates`）
- [ ] T2.7 建 `backend/strategies/first_board/pipeline.py`（`run_first_board_filter` / `attach_first_board_analysis`）
- [ ] T2.8 建 `backend/strategies/first_board/persistence.py`（`save_scores` / `load_scores` / `list_score_dates` / `ROOT` / `_SCORES_DIR` / `_SCORES_DIR_LEGACY`）
- [ ] T2.9 `first_board_filter.py` → thin shim
- [ ] T2.10 改 test monkeypatch 路径：`strategies.first_board_filter.*` → `strategies.first_board.<module>.*`（test_s075 / test_forward_test / test_s081 / test_s148）
- [ ] T2.11 `py_compile` + `pytest` 全绿
- [ ] T2.12 `git commit ... -m "refactor(S174 P2): split first_board_filter.py (1702 lines) into first_board/ package (6 modules) with re-export shim"`

## Phase 3：strategy_funnel_registry.py 拆分（940 行 → backend/strategies/funnel/ 5 子模块 + shim）

- [ ] T3.1 `cp backend/strategies/strategy_funnel_registry.py /tmp/strategy_funnel_registry.py.bak`
- [ ] T3.2 建 `backend/strategies/funnel/__init__.py`
- [ ] T3.3 建 `backend/strategies/funnel/weather.py`（`WEATHER_RECOMMENDATION` / `WEATHER_STRATEGY_MAP` / `FALLBACK_STRATEGIES` / `get_weather_recommendation` / `get_strategies_for_weather`）
- [ ] T3.4 建 `backend/strategies/funnel/registry.py`（`STRATEGY_REGISTRY` / `STRATEGY_FUNNEL_REGISTRY` / `StrategyFunnelConfig` / `get_strategy_config` / `_load_weights` / `_get_weight_set` / `_DATA_DIR` / `_WEIGHTS_PATH` / `_WEIGHTS_CACHE`）
- [ ] T3.5 建 `backend/strategies/funnel/scoring.py`（`compute_strategy_score` / `_cand_to_gene` / `_build_market_scan_factors`）
- [ ] T3.6 建 `backend/strategies/funnel/aggregation.py`（`_aggregate_strategy_funnels` / `score_candidates`）
- [ ] T3.7 建 `backend/strategies/funnel/quality.py`（`check_quality_standards` / `passes_hard_standards`）
- [ ] T3.8 `strategy_funnel_registry.py` → thin shim
- [ ] T3.9 改 test monkeypatch 路径：`strategies.strategy_funnel_registry.score_candidates` → `strategies.funnel.aggregation.score_candidates`（test_forward_test 3 处）
- [ ] T3.10 `py_compile` + `pytest` 全绿
- [ ] T3.11 `git commit ... -m "refactor(S174 P3): split strategy_funnel_registry.py (940 lines) into funnel/ package (5 modules) with re-export shim"`

## Phase 4：验收

- [ ] T4.1 `wc -l backend/scheduler/**/*.py backend/strategies/first_board/*.py backend/strategies/funnel/*.py`（全 <800）
- [ ] T4.2 `pytest -m "not live" --deselect ...` 全绿
- [ ] T4.3 REPL import 验证：`import scheduled_tasks; from strategies.first_board_filter import run_first_board_filter; from strategies.strategy_funnel_registry import score_candidates; print('OK')`
- [ ] T4.4 `grep -rn 'strategies.first_board_filter\.' backend/tests/`（旧路径已清零或仅剩 shim）
- [ ] T4.5 `grep -rn 'strategies.strategy_funnel_registry\.' backend/tests/`（同上）
- [ ] T4.6 `grep -rn 'scheduled_tasks._DB_PATH' backend/conftest.py`（已迁移）
