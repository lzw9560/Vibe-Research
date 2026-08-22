# Tasks: S089 — SQLite 并发性能加固与分表分库

> 关联：`spec.md`（需求）/ `plan.md`（技术方案）。本文件为逐条任务表。

## 阶段 A：WAL + busy_timeout + 连接复用加固

| # | 任务 | 文件 | 验收 | 状态 |
|---|---|---|---|---|
| A1 | 新建 `backend/db_health.py`，提供 `get_healthy_conn(db_path, check_same_thread)` 统一连接初始化（WAL + busy_timeout=5000 + foreign_keys + row_factory） | `backend/db_health.py`（新） | 函数存在，单测 `test_get_healthy_conn` 验证 3 个 PRAGMA 返回值 | ⬜ |
| A2 | 新建 `backend/tools/enable_wal_all_dbs.py`，对 8 个未启用 WAL 的 DB 一次性执行 `PRAGMA journal_mode=WAL` + `busy_timeout=5000` | `backend/tools/enable_wal_all_dbs.py`（新） | 脚本执行后 9 个 DB `PRAGMA journal_mode` 全返回 `wal` | ⬜ |
| A3 | `seal_intraday_collector.py` 的 `_get_conn()` 改为模块级单连接 + `check_same_thread=False`，配合 `_DB_LOCK` 串行化 | `backend/risk/seal_intraday_collector.py` | 既有 `test_s055` 全绿，连接复用无报错 | ⬜ |
| A4 | `gene_scores` 访问点（`limitup_screener/data.py`）同理改为单连接复用 | `backend/limitup_screener/data.py` | `test_s047_weight_recalc` 全绿 | ⬜ |
| A5 | 既有 DB 访问点逐步替换为 `get_healthy_conn`（可渐进，不阻断） | 多文件 | grep `sqlite3.connect` 减少，`get_healthy_conn` 增多 | ⬜ |

## 阶段 B：路由层 + 分表分库基础设施

| # | 任务 | 文件 | 验收 | 状态 |
|---|---|---|---|---|
| B1 | 新建 `backend/db_partition_router.py`，实现 `resolve_partition(date_str) -> (db_path, table_name)` | `backend/db_partition_router.py`（新） | `resolve_partition('2026-08-20')` 返回 `('.vibe-research/seal_intraday_2026.db', 'seal_intraday_snapshots_202608')` | ⬜ |
| B2 | 同文件加 `ensure_partition(date_str)`——resolve + 建表建索引（幂等 `CREATE IF NOT EXISTS`），DDL 含 low_price/limit_pct 字段（兼容 S070 R6） | 同上 | `ensure_partition('2026-08-20')` 幂等执行两次不报错，表+3索引存在 | ⬜ |
| B3 | 同文件加 `get_latest_partition() -> (db_path, table_name)`——路由到当年最新月表 | 同上 | 返回当前年最新月表 | ⬜ |
| B4 | `config/__init__.py` 新增 `SEAL_INTRADAY_DIR` 常量 + `seal_intraday_db_path(year)` 函数 | `backend/config/__init__.py` | 常量+函数存在，不破坏 S037 既有常量 | ⬜ |
| B5 | 新建 `backend/tests/test_s089_partition_router.py`——路由层单元测试（resolve/ensure/get_latest） | `backend/tests/test_s089_partition_router.py`（新） | pytest 全绿 | ⬜ |

## 阶段 C：seal_intraday_collector 改造 + 历史迁移

| # | 任务 | 文件 | 验收 | 状态 |
|---|---|---|---|---|
| C1 | `save_snapshots(rows)` 改造：按 row.date 分桶，`resolve_partition` 路由到对应分表，跨月批量分桶写入 | `backend/risk/seal_intraday_collector.py` | 写入后 `resolve_partition(date)` 查到数据；`test_s055` 全绿 | ⬜ |
| C2 | `get_snapshots_by_code(code, date)` 改造：`resolve_partition(date)` 路由查分表 | 同上 | 单股时序查询正常返回 | ⬜ |
| C3 | `get_latest_snapshots(date)` 改造：同理路由 | 同上 | 当日全量最新快照正常返回 | ⬜ |
| C4 | `prune_old_snapshots` 改为 `archive_old_partitions()`：不删除，只标记冷热 | 同上 + `backend/scheduled_tasks.py` | 函数存在，scheduled 调用点适配 | ⬜ |
| C5 | 新建 `backend/tools/migrate_seal_intraday_partition.py`：读旧库全量 → 按月路由写入分表 → 行数对比 → 旧库 `.bak` | `backend/tools/migrate_seal_intraday_partition.py`（新） | dry-run + 实跑后行数 = 16,647，旧库保留 `.bak` | ⬜ |
| C6 | `strategies/impl/db_based.py:33` 的 `SELECT DISTINCT code` + `SELECT MAX(date)` 路由适配 | `backend/strategies/impl/db_based.py` | 当日股票清单 + 最新交易日正常返回 | ⬜ |
| C7 | `strategies/intraday_features.py:259` 的 `WHERE date=? AND code=?` 路由适配 | `backend/strategies/intraday_features.py` | 既有 `test_intraday_features` 全绿 | ⬜ |

## 阶段 D：消费方适配 + 月度 VACUUM

| # | 任务 | 文件 | 验收 | 状态 |
|---|---|---|---|---|
| D1 | grep 全部 `seal_intraday_snapshots` 硬编码引用，确保全部走路由层 | 多文件 | grep 无硬编码表名引用（全走 `resolve_partition`） | ⬜ |
| D2 | `scheduled_tasks.py` 新增 `monthly_vacuum` executor：当年库 `VACUUM` + `wal_checkpoint(TRUNCATE)`，月初触发 | `backend/scheduled_tasks.py` | executor 注册成功，手动触发不报错 | ⬜ |
| D3 | `scheduled_tasks.py:833` 的 prune 调用改为 `archive_old_partitions` | `backend/scheduled_tasks.py` | 调用点适配，无报错 | ⬜ |

## 阶段 E：离线索引兜底 + 验收

| # | 任务 | 文件 | 验收 | 状态 |
|---|---|---|---|---|
| E1 | `db_health.py` 加 `ensure_gene_scores_cover_index()`：行数 > 50,000 时创建覆盖索引 `idx_gene_scores_cover(date, code, data_source, total_score)` | `backend/db_health.py` | 函数存在，当前不触发（行数 6,943 < 50,000） | ⬜ |
| E2 | 并发压测脚本：ThreadPool(20) 并发写+读 `seal_intraday`，验证无 `database is locked` | `backend/tests/test_s089_concurrency.py`（新） | 压测 100 次操作 0 错误 | ⬜ |
| E3 | A1-A8 验收标准逐条过 | — | 全绿 | ⬜ |
