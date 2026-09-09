# Spec: S174 — 3 god-module 拆分（scheduled_tasks / first_board_filter / strategy_funnel_registry）

> 状态：草案
> 作者：Claude（agent）  日期：2026-09-09
> 关联：memory `project-slim-audit-2026-09-09` P6 / `coding-style.md` 800 行上限 / S141 FirstBoardPipeline 节点化拆分（前序，已实现）

## 1. 问题 / 目标

三个核心模块严重超 800 行上限（`coding-style.md`），是维护炸弹：

| 模块 | 行数 | 超限倍数 | 痛点 |
|---|---|---|---|
| `backend/scheduled_tasks.py` | 3076 | 3.8x | TaskExecutor 26 个 `_execute_*` 方法 + cron 匹配 + DB 持久化 + 通知构建 + seed 任务全挤一个文件，改一个 executor 要在 3000 行里定位 |
| `backend/strategies/first_board_filter.py` | 1717 | 2.1x | 15 个评分函数 + 3 层剔除 + 数据抽取 + 持久化 + pipeline 入口全混一起 |
| `backend/strategies/strategy_funnel_registry.py` | 940 | 1.2x | 注册表 + 天气映射 + 权重 + 评分 + 聚合 + 质量门 6 职责挤一个文件 |

目标：按职责拆成子模块（每文件 <800 行），通过 re-export 兼容层保证调用方零改，现有测试全过。

## 2. 背景

- **project-slim-audit P6**（memory `project-slim-audit-2026-09-09`）：审计识别 3 个 god-module 须拆。
- **coding-style.md**：「200-400 行典型，800 最大」「many small files > few large files」「按 feature/domain 组织而非按 type」。
- **S141 FirstBoardPipeline 节点化拆分**（已实现）：已将 pipeline 执行逻辑拆为节点化步骤，但 `first_board_filter.py` 本身未拆——本 spec 补完。
- **已知约束**：
  - `scheduled_tasks._DB_PATH` 被 `conftest.py` monkeypatch（测试 DB 隔离），拆分后 patch 路径须同步更新。
  - 多个测试 monkeypatch 旧模块路径（如 `strategies.first_board_filter.extract_chip_structure`），re-export 兼容层保留属性名但 patch 须改指新模块路径。
  - `workflow_state_repo.py` 与 `scheduled_tasks.py` 共用 `market_data.db`（平行连接，非 import 依赖），拆分不影响。

## 3. 需求清单

- [ ] R1 `scheduled_tasks.py`（3076 行）拆为 `backend/scheduler/` 包，按职责分 7 核心文件 + 8 executor 文件（见 §5.1）
- [ ] R2 `first_board_filter.py`（1717 行）拆为 `backend/strategies/first_board/` 包，6 子模块（见 §5.2）
- [ ] R3 `strategy_funnel_registry.py`（940 行）拆为 `backend/strategies/funnel/` 包，5 子模块（见 §5.3）
- [ ] R4 三个旧文件变为 re-export 兼容层（thin shim），所有外部 `from <旧模块> import X` 零改可用
- [ ] R5 conftest.py monkeypatch 路径更新（`scheduled_tasks._DB_PATH` → 新模块路径）
- [ ] R6 测试 monkeypatch 路径更新（`strategies.first_board_filter.*` / `strategies.strategy_funnel_registry.*` → 新模块路径）
- [ ] R7 全量 `pytest -m "not live"` 绿（拆分不改行为，只改文件组织）
- [ ] R8 拆分后每文件 <800 行

## 4. 受影响文件

### 4.1 scheduled_tasks.py → backend/scheduler/ 包

| 新文件 | 职责 | 预估行数 | 源行范围 |
|---|---|---|---|
| `scheduler/models.py` | `ScheduledTask` / `TaskRun` dataclass | ~45 | 29-62 |
| `scheduler/db.py` | `_DB_PATH` / `_get_connection` / `_ensure_tables` / `ScheduledTaskManager` / `_manager` | ~330 | 20-25, 63-372 |
| `scheduler/snapshots.py` | `_save_snapshot` / `get_backtest_snapshots` | ~70 | 373-490 |
| `scheduler/notifications.py` | 通知内容构建 + kill switch + T1 收益计算 + `generate_daily_summary` | ~400 | 2085-2410 |
| `scheduler/cron.py` | `_cron_token_match` / `_cron_field_match` / `cron_match` | ~75 | 2465-2539 |
| `scheduler/seed.py` | `_ensure_seed_tasks`（26 个 seed 任务定义）+ `_task_timeout` | ~430 | 491-495, 2663-3076 |
| `scheduler/cron_runner.py` | `CronScheduler` 类 / `get_scheduler` / `start_scheduler` / `stop_scheduler` | ~110 | 2540-2662 |
| `scheduler/executors/__init__.py` | `TaskExecutor` 薄分发类（dispatch dict + execute / execute_async / _send_notification） | ~100 | 496-637 |
| `scheduler/executors/data_ops.py` | daily_data_refresh / market_data_sync / cleanup_old_runs / kline_refresh / monthly_vacuum | ~160 | 658-676, 810-836, 1890-2001 |
| `scheduler/executors/limitup.py` | limitup_precompute / sti_post_market / zt_history_snapshot / st_play_radar / derived_precompute | ~264 | 677-795, 1552-1588, 1782-1889 |
| `scheduler/executors/first_board.py` | first_board_filter / first_board_t1_review / first_board_quote_probe | ~152 | 1157-1182, 1426-1551 |
| `scheduler/executors/premarket.py` | premarket_auction_notify / premarket_open_notify / premarket_t1_review | ~97 | 1060-1156 |
| `scheduler/executors/backtest.py` | daily_backtest_run / s066_validation_checkpoint / evaluation_backtest / forward_test_daily / forward_test_t1_settle | ~304 | 860-920, 1183-1425 |
| `scheduler/executors/intraday.py` | seal_intraday_collect / intraday_microstructure_snapshot / intraday_auction_dense / baostock_5min_freeze | ~229 | 921-956, 1589-1781 |
| `scheduler/executors/ai_portfolio.py` | daily_ai_summary / portfolio_refresh / candidate_funnel_precompute / daily_review_notify | ~140 | 796-809, 837-859, 957-1059 |
| `scheduler/executors/kg.py` | daily_kg_audit / daily_kg_sync | ~83 | 2002-2084 |
| `scheduled_tasks.py`（shim） | re-export 全部公共名 + 模块级 compat 包装（4 个 `_(ctx, payload)` 包装） | ~60 | — |

### 4.2 first_board_filter.py → backend/strategies/first_board/ 包

| 新文件 | 职责 | 预估行数 | 源行范围 |
|---|---|---|---|
| `first_board/universe.py` | `fetch_zt_pool` / `filter_first_board` / `_market_phase` / `_to_float` / `_fbt_to_hhmm` / `PHASE_TO_CAP_TIER` | ~280 | 1-283 |
| `first_board/data_extract.py` | `extract_chip_structure` / `_get_kline_cache` / `extract_sector` | ~140 | 284-424 |
| `first_board/exclusions.py` | `exclude_layer1/2/3` / `_sector_zt_count` / `_market_drop_pct` | ~220 | 425-645 |
| `first_board/scoring.py` | 15 个 `score_dim*` 函数 + `_SCORE_DIMS` 列表 | ~692 | 646-1338 |
| `first_board/pipeline.py` | `score_candidate` / `rank_candidates` / `run_first_board_filter` / `attach_first_board_analysis` | ~340 | 1339-1476, 1573-1717 |
| `first_board/persistence.py` | `save_scores` / `load_scores` / `list_score_dates` / `ROOT` / `_SCORES_DIR` / `_SCORES_DIR_LEGACY` | ~100 | 1477-1572 |
| `first_board_filter.py`（shim） | re-export 全部公共名 | ~40 | — |

### 4.3 strategy_funnel_registry.py → backend/strategies/funnel/ 包

| 新文件 | 职责 | 预估行数 | 源行范围 |
|---|---|---|---|
| `funnel/weather.py` | `WEATHER_RECOMMENDATION` / `WEATHER_STRATEGY_MAP` / `FALLBACK_STRATEGIES` / `get_weather_recommendation` / `get_strategies_for_weather` | ~110 | 57-113 |
| `funnel/registry.py` | `STRATEGY_REGISTRY` / `STRATEGY_FUNNEL_REGISTRY` / `StrategyFunnelConfig` / `get_strategy_config` / `_DATA_DIR` / `_WEIGHTS_PATH` / `_WEIGHTS_CACHE` / `_load_weights` / `_get_weight_set` | ~280 | 38-375 |
| `funnel/scoring.py` | `compute_strategy_score` / `_cand_to_gene` / `_build_market_scan_factors` | ~100 | 381-508 |
| `funnel/aggregation.py` | `_aggregate_strategy_funnels` / `score_candidates` | ~200 | 509-757 |
| `funnel/quality.py` | `check_quality_standards` / `passes_hard_standards` | ~190 | 758-940 |
| `strategy_funnel_registry.py`（shim） | re-export 全部公共名 | ~30 | — |

### 4.4 调用方影响（re-export 兼容层保零改）

以下调用方**无需改代码**（re-export shim 保证 import 路径不变）：

| 调用方 | 导入的旧路径 | 兼容方式 |
|---|---|---|
| `routers/health.py` | `import scheduled_tasks as st` | shim re-export |
| `routers/backtest.py` | `import scheduled_tasks as _st` | shim re-export |
| `routers/strategy.py` | `from strategies.strategy_funnel_registry import score_candidates, ...` | shim re-export |
| `routers/workflow.py` | `from strategies.first_board_filter import fetch_zt_pool, ...` | shim re-export |
| `pre_market_workflow.py` | `from strategies.first_board_filter import fetch_zt_pool, _market_phase, ...` | shim re-export |
| `scheduled_tasks.py` → executors | `from strategies.first_board_filter import run_first_board_filter` | shim re-export |
| `strategies/strategy_base.py` | `from strategies.strategy_funnel_registry import STRATEGY_REGISTRY` | shim re-export |
| `strategies/non_limitup_funnel.py` | `from strategies.strategy_funnel_registry import ...` | shim re-export |
| `strategies/forward_test.py` | `from strategies.first_board_filter import fetch_zt_pool` | shim re-export |
| `strategies/first_board_settlement.py` | `from strategies.first_board_filter import load_scores` | shim re-export |
| `strategies/position_advisor.py` | `from strategies.first_board_filter import PHASE_TO_CAP_TIER` | shim re-export |
| `strategies/market_scan.py` | `from strategies.first_board_filter import _get_kline_cache` | shim re-export |
| `limitup_strategy.py` | `from strategies.strategy_funnel_registry import STRATEGY_REGISTRY` | shim re-export |

### 4.5 测试须改 monkeypatch 路径（re-export 兼容层的已知限制）

| 测试文件 | 旧 monkeypatch 路径 | 新 monkeypatch 路径 |
|---|---|---|
| `conftest.py:29` | `monkeypatch.setattr(st, "_DB_PATH", ...)` | `monkeypatch.setattr("scheduler.db._DB_PATH", ...)` |
| `conftest.py:32` | `st._ensure_tables()` | `from scheduler.db import _ensure_tables; _ensure_tables()` |
| `conftest.py:40` | `from scheduled_tasks import CronScheduler` | 保持（shim re-export）或改 `from scheduler.cron_runner import CronScheduler` |
| `test_s075_first_board_filter.py` (~8 处) | `strategies.first_board_filter.extract_chip_structure` | `strategies.first_board.data_extract.extract_chip_structure` |
| `test_s075_first_board_filter.py` (~4 处) | `strategies.first_board_filter._market_drop_pct` | `strategies.first_board.exclusions._market_drop_pct` |
| `test_s075_first_board_filter.py` (~2 处) | `strategies.first_board_filter.concept_blocks` | `strategies.first_board.universe.concept_blocks` |
| `test_s075_first_board_filter.py` (~1 处) | `strategies.first_board_filter.em_zt_topic_pool` | `strategies.first_board.universe.em_zt_topic_pool` |
| `test_forward_test.py:640,675` | `strategies.first_board_filter.fetch_zt_pool` | `strategies.first_board.universe.fetch_zt_pool` |
| `test_forward_test.py:610,647,681` | `strategies.strategy_funnel_registry.score_candidates` | `strategies.funnel.aggregation.score_candidates` |
| `test_s052_backfill.py` (~3 处) | `scheduled_tasks.TaskExecutor._execute_daily_backtest_run` | 保持（class 方法 patch 跨模块生效，TaskExecutor 是同一个类对象） |

> **为什么 class 方法 patch 不用改**：`scheduled_tasks.TaskExecutor` 与 `scheduler.executors.TaskExecutor` 是同一个类对象（re-export 的是引用，非拷贝），patch 类属性影响所有实例，不受模块路径影响。
>
> **为什么模块级名 patch 要改**：Python monkeypatch 设的是目标模块的属性绑定。旧路径 `strategies.first_board_filter.extract_chip_structure` patch 的是 shim 模块属性，但 `_get_connection` 读 `_DB_PATH` 时看的是 `scheduler.db` 模块自身的 global——shim 上的 patch 传不过去。同理 `score_candidates` 被外部调用方经 shim lazy import 时 patch 生效，但被新子模块内部直接 import 调用时 patch 不生效。

## 5. 设计方案

### 5.1 scheduled_tasks.py 拆分

**架构**：`backend/scheduler/` 为 Python 包，`scheduled_tasks.py` 变为 60 行 re-export shim。

**核心文件（7 个）**：

1. **`models.py`** — `ScheduledTask` / `TaskRun` 两个 dataclass，纯数据结构，零依赖。
2. **`db.py`** — `_DB_PATH` + `_get_connection` + `_ensure_tables` + `ScheduledTaskManager`（CRUD + run 管理 + stale reap）+ 模块级 `_manager` 单例。`_get_connection` 在调用时读 `_DB_PATH`（模块 global），conftest patch `scheduler.db._DB_PATH` 直接生效。
3. **`snapshots.py`** — `_save_snapshot` / `get_backtest_snapshots`，回测快照存取。依赖 `db._manager`。
4. **`notifications.py`** — 通知内容构建链：`_compute_dual_confirmation` → `_build_premarket_notification_content` / `_build_auction_notify_content` / `_build_open_notify_content` / `_build_t1_review_content` + 辅助（`_load_final_cards` / `_fetch_quotes` / `_send_notify` / `_fmt_pct` / `_check_premarket_kill_switch` / `_prepend_kill_switch_warning` / `_compute_t1_returns` / `_bar_close` / `_compute_strategy_map`）+ `generate_daily_summary`。
5. **`cron.py`** — cron 表达式匹配（`_cron_token_match` / `_cron_field_match` / `cron_match`），纯函数无状态。
6. **`seed.py`** — `_ensure_seed_tasks`（26 个 seed 任务定义）+ `_task_timeout`。依赖 `db._manager` + `models.ScheduledTask`。
7. **`cron_runner.py`** — `CronScheduler` 类（async ticker 循环 + `_should_run` 委托 `cron.cron_match` + `_reap_stale_runs` 委托 `db._manager.reap_stale_running`）+ `_scheduler` 单例 + `get_scheduler` / `start_scheduler` / `stop_scheduler`。依赖 `cron` + `executors.TaskExecutor` + `db._manager`。

**executor 包（`scheduler/executors/`）**：

8. **`executors/__init__.py`** — `TaskExecutor` 薄分发类：
   - `__init__`：dispatch dict 映射 task_type → executor 函数（不再绑定 `self._execute_*`，改为导入的模块级函数）
   - `execute` / `execute_async`：dispatch + run 记录 + 通知（逻辑不变，只改 dispatch 表指向函数而非 bound method）
   - `_send_notification`：通知发送（委托 `notifications._send_notify`）
   - `_thread_pool`：独占 `ThreadPoolExecutor`（S150 HIGH1 根治，保留）

9-16. **8 个 executor 域文件**（按业务域分组）：
   - `data_ops.py` — 数据刷新/同步/清理/kline 刷新/月度 VACUUM（5 个 executor）
   - `limitup.py` — 涨停预计算/STI 盘后/涨停历史快照/ST radar/derived 预计算（5 个）
   - `first_board.py` — 首板筛选/T+1 复盘/行情探查（3 个）
   - `premarket.py` — 竞价通知/开盘通知/T+1 复盘通知（3 个）
   - `backtest.py` — 日回测/§44 检查点/评价层回测/forward_test daily/T+1 settle（5 个）
   - `intraday.py` — 封单采集/微结构快照/竞价密集/5min 冻结（4 个）
   - `ai_portfolio.py` — AI 总结/持仓刷新/漏斗预计算/复盘通知（4 个）
   - `kg.py` — 知识图谱审查/数据同步（2 个）

   每个 executor 从模块级函数转为独立函数 `(payload: Dict[str, Any]) -> Dict[str, Any]`，签名不变。内部依赖通过 import 新子模块解决（不走 shim，直接 import 真实路径）。

**re-export shim（`scheduled_tasks.py`）**：
```python
# 约 60 行：from scheduler import * 展开 + 4 个模块级 compat 包装
from scheduler.models import *
from scheduler.db import *
from scheduler.cron import *
# ... 全部 re-export
from scheduler.executors import TaskExecutor

# 模块级 compat 包装（旧 st._execute_xxx(ctx, payload) 调用方）
def _execute_s066_validation_checkpoint(ctx, payload):
    return TaskExecutor()._execute_s066_validation_checkpoint(payload)
# ...（4 个）
```

### 5.2 first_board_filter.py 拆分

**架构**：`backend/strategies/first_board/` 为 Python 包，`first_board_filter.py` 变为 40 行 shim。

| 子模块 | 导出 | 依赖 |
|---|---|---|
| `universe.py` | `fetch_zt_pool` / `filter_first_board` / `_market_phase` / `_to_float` / `_fbt_to_hhmm` / `PHASE_TO_CAP_TIER` | `astock.em_zt_topic_pool` / `astock.concept_blocks` / `market._emotion` |
| `data_extract.py` | `extract_chip_structure` / `_get_kline_cache` / `extract_sector` | `astock` / `vr_paths` |
| `exclusions.py` | `exclude_layer1/2/3` / `_sector_zt_count` / `_market_drop_pct` | `universe`（取涨停池）/ `data_extract`（取筹码） |
| `scoring.py` | 15 个 `score_dim*` / `_SCORE_DIMS` | `data_extract`（取筹码/K线）/ `universe`（取涨停池/行业） |
| `pipeline.py` | `score_candidate` / `rank_candidates` / `run_first_board_filter` / `attach_first_board_analysis` | `universe` + `exclusions` + `scoring` + `persistence` |
| `persistence.py` | `save_scores` / `load_scores` / `list_score_dates` / `ROOT` / `_SCORES_DIR` | `vr_paths` |

### 5.3 strategy_funnel_registry.py 拆分

**架构**：`backend/strategies/funnel/` 为 Python 包，`strategy_funnel_registry.py` 变为 30 行 shim。

| 子模块 | 导出 | 依赖 |
|---|---|---|
| `weather.py` | `WEATHER_RECOMMENDATION` / `WEATHER_STRATEGY_MAP` / `FALLBACK_STRATEGIES` / `get_weather_recommendation` / `get_strategies_for_weather` | 无外部依赖 |
| `registry.py` | `STRATEGY_REGISTRY` / `STRATEGY_FUNNEL_REGISTRY` / `StrategyFunnelConfig` / `get_strategy_config` / `_load_weights` / `_get_weight_set` / `_DATA_DIR` / `_WEIGHTS_PATH` / `_WEIGHTS_CACHE` | `strategy_base.*` / `impl.*` / `market_scan._build_market_data` |
| `scoring.py` | `compute_strategy_score` / `_cand_to_gene` / `_build_market_scan_factors` | `registry`（取权重/配置） |
| `aggregation.py` | `_aggregate_strategy_funnels` / `score_candidates` | `scoring` + `registry` + `market_scan` |
| `quality.py` | `check_quality_standards` / `passes_hard_standards` | `registry`（取配置） |

### 5.4 渐进式策略

1. **先拆 `scheduled_tasks.py`**（最大 3076 行 + 最多调用方），验证 re-export 模式 + monkeypatch 迁移模式。
2. **再拆 `first_board_filter.py`**（1717 行），复用已验证模式。
3. **最后拆 `strategy_funnel_registry.py`**（940 行，最小），模式成熟后快速完成。

每步拆完立即跑 `pytest -m "not live"` 验证，绿了再进下一步。

### 5.5 备选方案为何不选

| 备选 | 不选理由 |
|---|---|
| 直接迁移 import 路径（不做 shim） | 爆炸半径大——13+ 调用方文件要改，风险高收益低 |
| 按类型拆（all models / all utils / all executors 各一文件） | coding-style.md 明确反对「按 type 组织」，应按 domain 组织 |
| 不拆 scoring.py（692 行仍在 800 内） | 15 个评分函数属同一域，692 行可接受；若硬拆 dim1-5 / dim6-9 / extra 反而破坏内聚 |
| 用 `__getattr__` 动态委托代替显式 re-export | `__getattr__` 只对 missing 属性触发，已定义名不触发；且不解决 `_DB_PATH` 跨模块 patch 问题（根因是 `_get_connection` 读自身模块 global） |

## 6. 验收标准

- [ ] A1 `scheduled_tasks.py` 拆完，`backend/scheduler/` 包 7 核心文件 + 8 executor 文件，每文件 <800 行
- [ ] A2 `first_board_filter.py` 拆完，`backend/strategies/first_board/` 包 6 子模块，每文件 <800 行
- [ ] A3 `strategy_funnel_registry.py` 拆完，`backend/strategies/funnel/` 包 5 子模块，每文件 <800 行
- [ ] A4 三个旧文件变为 re-export shim，外部调用方零改（grep 确认调用方文件无改动）
- [ ] A5 `pytest -m "not live"` 全绿（拆分不改行为）
- [ ] A6 conftest.py monkeypatch 路径已更新，测试 DB 隔离正常
- [ ] A7 测试 monkeypatch 路径已更新（§4.5 表全部迁移完）
- [ ] A8 `import scheduled_tasks` / `from strategies.first_board_filter import ...` / `from strategies.strategy_funnel_registry import ...` 在 Python REPL 可正常执行

## 7. 合规与工程底线自查（逐条确认）

- [x] 弱合规：本 spec 为纯代码重构（文件组织拆分），不涉及数据输出 / AI 提示词 / 交易信号——无需合规仪式
- [x] 判断可复现：不涉及财务数据验算，无 `financial_rigor.py` 需求
- [x] 涨停四池 / 连板股榜：不涉及个股呈现逻辑变更
- [x] 用户私有数据：`_DB_PATH` 指向 `backend/data/market_data.db`（项目内，非 `.vibe-research/`），拆分不改路径；`_DATA_DIR` / `_WEIGHTS_PATH` 仍读 `VR_DATA_DIR` env 变量，私有数据隔离不破
- [x] 东财端点：不涉及新增东财调用，executor 内部逻辑不变
- [x] 不臆造：模块拆分纯机械迁移，不改任何业务逻辑

## 8. 测试计划

1. **离线快测**：`cd backend && .venv/bin/python -m pytest -m "not live" --deselect tests/test_newsradar.py::test_fetch_global_intel_wm_import_fails --deselect tests/test_s032_refresh_loop.py --deselect tests/test_s040_backfill_kline_cache.py -x`（排除已知 flaky）
2. **REPL import 验证**：`python -c "import scheduled_tasks; from strategies.first_board_filter import run_first_board_filter; from strategies.strategy_funnel_registry import score_candidates; print('OK')"`
3. **行数验证**：`wc -l backend/scheduler/**/*.py backend/strategies/first_board/*.py backend/strategies/funnel/*.py`（全 <800）
4. **monkeypatch 路径 grep 验证**：`grep -rn 'strategies.first_board_filter\.' backend/tests/` / `grep -rn 'strategies.strategy_funnel_registry\.' backend/tests/` / `grep -rn 'scheduled_tasks._DB_PATH' backend/conftest.py`（确认旧路径已清零或仅剩 shim 自身）

## 9. 风险与回滚

### 9.1 主要风险

| 风险 | 等级 | 缓解 |
|---|---|---|
| monkeypatch 路径遗漏导致测试假阴（patch 不到目标） | HIGH | §4.5 表逐条对照，拆完每步跑 pytest 验证 |
| 循环 import（executor A import executor B 的函数） | MEDIUM | executor 之间不互相 import；共享依赖走 notifications / db 子模块 |
| `_manager` 单例跨模块行为变化 | MEDIUM | `_manager` 留在 `db.py` 模块级，其他模块 `from scheduler.db import _manager`——仍是同一个实例 |
| `seed.py` 430 行接近上限（单函数太长） | LOW | seed 是 26 个 `create_task` 调用的长列表，本质是数据而非逻辑；若审查认为过长可按域拆 `seed_data.py` / `seed_intraday.py` 等 |

### 9.2 回滚方式

- re-export 兼容层保证：回滚只需 `git revert` 拆分 commit，旧文件恢复原样，调用方零改零影响。
- 若部分拆分后发现问题：可只回滚有问题的模块（3 个模块独立拆分，互不依赖）。
