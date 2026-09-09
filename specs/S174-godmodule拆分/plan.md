# Plan: S174 — 3 god-module 拆分

> 关联 spec：`spec.md`（同目录）
> 状态：实现中
> 日期：2026-09-09

## 1. 总体策略

三个 god-module（`scheduled_tasks.py` 3076 行 / `first_board_filter.py` 1702 行 / `strategy_funnel_registry.py` 940 行）按 spec §5.4 渐进式拆分：先最大最复杂的 `scheduled_tasks`（验证 re-export + monkeypatch 迁移模式），再 `first_board_filter`，最后 `strategy_funnel_registry`。

每步拆完跑 pytest 验证，绿了再进下一步。

## 2. 核心模式

### 2.1 Re-export 兼容层（shim）

旧文件变 thin shim，`from <新包> import *` 展开全部公共名 + 手动 re-export 不被 `*` 捕获的模块级名（`_DB_PATH` / `_manager` 等）。调用方零改。

```python
# scheduled_tasks.py shim (~60 行)
from scheduler.models import *
from scheduler.db import *
from scheduler.cron import *
from scheduler.cron_runner import *
from scheduler.executors import TaskExecutor
# ... 全部 re-export
```

### 2.2 Executor 方法转独立函数（scheduled_tasks 专有）

26 个 `_execute_*` 从 `TaskExecutor` bound method → 8 域文件模块级函数 `(payload)->Dict`。`TaskExecutor` 变薄 dispatch：

```python
# scheduler/executors/__init__.py
from .data_ops import daily_data_refresh, market_data_sync, ...
class TaskExecutor:
    def __init__(self):
        self._executors = {
            "daily_data_refresh": daily_data_refresh,
            ...
        }
```

spec §4.5 明确：class 方法 patch（`TaskExecutor._execute_*`）不用改——`scheduled_tasks.TaskExecutor` 与 `scheduler.executors.TaskExecutor` 是同一个类对象（re-export 的是引用）。

### 2.3 Monkeypatch 路径迁移

- `conftest.py` `st._DB_PATH` → `scheduler.db._DB_PATH`（模块级 global，`_get_connection` 读自身模块 global，shim 传不过去）
- `st._ensure_tables()` → `from scheduler.db import _ensure_tables`
- 测试 monkeypatch `strategies.first_board_filter.extract_chip_structure` → `strategies.first_board.data_extract.extract_chip_structure`（模块级名 patch 须改指新模块）
- class 方法 patch（`TaskExecutor._execute_daily_backtest_run`）不用改

## 3. 拆分方案

### 3.1 scheduled_tasks.py → backend/scheduler/ 包（17 文件）

7 core + executors/__init__ + 8 executor 域 + shim：

| 文件 | 职责 | 预估行数 |
|---|---|---|
| `scheduler/__init__.py` | 包入口，re-export | ~20 |
| `scheduler/models.py` | `ScheduledTask` / `TaskRun` dataclass | ~45 |
| `scheduler/db.py` | `_DB_PATH` / `_get_connection` / `_ensure_tables` / `ScheduledTaskManager` / `_manager` / `_TASK_TIMEOUTS` / `_task_timeout` / `_REAPER_STALE_SECONDS` / `_SEAL_COLLECT_SUBPROCESS_TIMEOUT` | ~330 |
| `scheduler/snapshots.py` | `_save_snapshot` / `get_backtest_snapshots` | ~70 |
| `scheduler/notifications.py` | 通知内容构建链 + `generate_daily_summary` | ~400 |
| `scheduler/cron.py` | `_cron_token_match` / `_cron_field_match` / `cron_match` / `_CRON_FIELD_BOUNDS` | ~75 |
| `scheduler/seed.py` | `_ensure_seed_tasks` | ~430 |
| `scheduler/cron_runner.py` | `CronScheduler` / `_scheduler` / `get_scheduler` / `start_scheduler` / `stop_scheduler` / `_TICK_INTERVAL` | ~110 |
| `scheduler/executors/__init__.py` | `TaskExecutor` 薄分发 | ~100 |
| `scheduler/executors/data_ops.py` | daily_data_refresh / market_data_sync / cleanup_old_runs / kline_refresh / monthly_vacuum | ~160 |
| `scheduler/executors/limitup.py` | limitup_precompute / sti_post_market / zt_history_snapshot / st_play_radar / derived_precompute | ~264 |
| `scheduler/executors/first_board.py` | first_board_filter / first_board_t1_review / first_board_quote_probe | ~152 |
| `scheduler/executors/premarket.py` | premarket_auction_notify / premarket_open_notify / premarket_t1_review | ~97 |
| `scheduler/executors/backtest.py` | daily_backtest_run / s066_validation_checkpoint / evaluation_backtest / forward_test_daily / forward_test_t1_settle | ~304 |
| `scheduler/executors/intraday.py` | seal_intraday_collect / intraday_microstructure_snapshot / intraday_auction_dense / baostock_5min_freeze | ~229 |
| `scheduler/executors/ai_portfolio.py` | daily_ai_summary / portfolio_refresh / candidate_funnel_precompute / daily_review_notify | ~140 |
| `scheduler/executors/kg.py` | daily_kg_audit / daily_kg_sync | ~83 |
| `scheduled_tasks.py`（shim） | re-export + 4 个模块级 compat 包装 | ~60 |

### 3.2 first_board_filter.py → backend/strategies/first_board/ 包（6 子模块 + shim）

| 文件 | 职责 | 预估行数 |
|---|---|---|
| `first_board/__init__.py` | 包入口 re-export | ~20 |
| `first_board/universe.py` | `fetch_zt_pool` / `filter_first_board` / `_market_phase` / `_to_float` / `_fbt_to_hhmm` / `PHASE_TO_CAP_TIER` / `EXCLUDE_THRESHOLDS` / `MARKET_PHASE_WEIGHTS` + 模块级缓存 | ~280 |
| `first_board/data_extract.py` | `extract_chip_structure` / `_get_kline_cache` / `extract_sector` | ~140 |
| `first_board/exclusions.py` | `exclude_layer1/2/3` / `_sector_zt_count` / `_market_drop_pct` | ~220 |
| `first_board/scoring.py` | 15 个 `score_dim*` / `_SCORE_DIMS` / `score_candidate` / `rank_candidates` | ~692 |
| `first_board/pipeline.py` | `run_first_board_filter` / `attach_first_board_analysis` | ~340 |
| `first_board/persistence.py` | `save_scores` / `load_scores` / `list_score_dates` / `ROOT` / `_SCORES_DIR` / `_SCORES_DIR_LEGACY` | ~100 |
| `first_board_filter.py`（shim） | re-export | ~40 |

### 3.3 strategy_funnel_registry.py → backend/strategies/funnel/ 包（5 子模块 + shim）

| 文件 | 职责 | 预估行数 |
|---|---|---|
| `funnel/__init__.py` | 包入口 re-export | ~20 |
| `funnel/weather.py` | `WEATHER_RECOMMENDATION` / `WEATHER_STRATEGY_MAP` / `FALLBACK_STRATEGIES` / `get_weather_recommendation` / `get_strategies_for_weather` | ~110 |
| `funnel/registry.py` | `STRATEGY_REGISTRY` / `STRATEGY_FUNNEL_REGISTRY` / `StrategyFunnelConfig` / `get_strategy_config` / `_load_weights` / `_get_weight_set` / `_DATA_DIR` / `_WEIGHTS_PATH` / `_WEIGHTS_CACHE` | ~280 |
| `funnel/scoring.py` | `compute_strategy_score` / `_cand_to_gene` / `_build_market_scan_factors` | ~100 |
| `funnel/aggregation.py` | `_aggregate_strategy_funnels` / `score_candidates` | ~200 |
| `funnel/quality.py` | `check_quality_standards` / `passes_hard_standards` | ~190 |
| `strategy_funnel_registry.py`（shim） | re-export | ~30 |

## 4. 测试 monkeypatch 迁移清单

### 4.1 conftest.py
- `monkeypatch.setattr(st, "_DB_PATH", ...)` → `monkeypatch.setattr("scheduler.db._DB_PATH", ...)`
- `st._ensure_tables()` → `from scheduler.db import _ensure_tables; _ensure_tables()`

### 4.2 test_forward_test.py（6 处）
- `strategies.first_board_filter.fetch_zt_pool` → `strategies.first_board.universe.fetch_zt_pool`（3 处）
- `strategies.strategy_funnel_registry.score_candidates` → `strategies.funnel.aggregation.score_candidates`（3 处）

### 4.3 test_s075_first_board_filter.py（~12 处）
- `strategies.first_board_filter.extract_chip_structure` → `strategies.first_board.data_extract.extract_chip_structure`（6 处）
- `strategies.first_board_filter._market_drop_pct` → `strategies.first_board.exclusions._market_drop_pct`（3 处）
- `strategies.first_board_filter.concept_blocks` → `strategies.first_board.universe.concept_blocks`（2 处）
- `strategies.first_board_filter.em_zt_topic_pool` → `strategies.first_board.universe.em_zt_topic_pool`（2 处）
- `strategies.first_board_filter._emotion` → `strategies.first_board.universe._emotion`（3 处）
- `strategies.first_board_filter.score_candidate` → `strategies.first_board.scoring.score_candidate`（1 处）

### 4.4 test_s081_strategy_matcher_pool_item.py（1 处）
- `strategies.first_board_filter.fetch_zt_pool` → `strategies.first_board.universe.fetch_zt_pool`

### 4.5 test_s148_first_board_inject.py（7 处）
- `strategies.first_board_filter.fetch_zt_pool` / `rank_candidates` / `filter_first_board` / `load_scores` → 新模块路径

### 4.6 不改的（class 方法 patch 跨模块生效）
- `test_s052_backfill.py` `scheduled_tasks.TaskExecutor._execute_daily_backtest_run`（3 处）

## 5. 备选方案为何不选

见 spec §5.5。核心：选 re-export shim 不直接迁移 import（爆炸半径小，13+ 调用方零改）。

## 6. 风险与缓解

见 spec §9。核心风险：monkeypatch 路径遗漏（HIGH，逐条对照表 + 每步 pytest 验证）+ 循环 import（MEDIUM，executor 间不互 import，共享依赖走 db/notifications 子模块）。

## 7. 验证计划

1. 每步拆完 `py_compile` 全部新文件
2. 每步拆完 `pytest -m "not live" --deselect ...` 全绿
3. REPL `import scheduled_tasks` / `from strategies.first_board_filter import ...` / `from strategies.strategy_funnel_registry import ...` 可执行
4. `wc -l` 全部新文件 <800
5. `grep -rn` 旧 monkeypatch 路径在 tests/ 已清零
