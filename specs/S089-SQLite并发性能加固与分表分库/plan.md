# Plan: S089 — SQLite 并发性能加固与 seal_intraday 分表分库

> 关联：`spec.md`（需求与设计）。本文件为技术方案 + 阶段拆分。

## 阶段总览

| 阶段 | 目标 | 依赖 | 预估 |
|---|---|---|---|
| A | WAL + busy_timeout + 连接复用加固 | 无 | 小 |
| B | 路由层 + 分表分库基础设施 | A | 中 |
| C | seal_intraday_collector 改造 + 历史迁移 | B | 中 |
| D | 消费方适配 + 月度 VACUUM | C | 小 |
| E | 离线索引兜底 + 验收 | D | 小 |

---

## 阶段 A：WAL + busy_timeout + 连接复用加固

### A1: db_health.py 连接初始化工具
新建 `backend/db_health.py`，提供统一的连接初始化函数：

```python
import sqlite3
from config import PRIVATE_DATA_DIR

def get_healthy_conn(db_path: str, check_same_thread: bool = True) -> sqlite3.Connection:
    """统一连接初始化：WAL + busy_timeout + 外键。
    
    所有 DB 访问点逐步替换为此函数，保证新建 DB 也启用 WAL。
    """
    conn = sqlite3.connect(db_path, check_same_thread=check_same_thread)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA busy_timeout=5000")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn
```

### A2: 现有 DB 一次性 WAL 启用脚本
新建 `backend/tools/enable_wal_all_dbs.py`，对 8 个未启用 WAL 的 DB 执行：
```python
for db in ["seal_intraday.db", "gene_scores.db", "funnel_cache.db", 
           "winrate.db", "zt_history.db", "sti_timeline.db", 
           "verification_card.db", "kline_history.db"]:
    conn = sqlite3.connect(os.path.join(PRIVATE_DATA_DIR, db))
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA busy_timeout=5000")
    conn.close()
```

### A3: 高频写入 DB 连接复用
`seal_intraday_collector.py` 的 `_get_conn()` 改为模块级单连接 + `check_same_thread=False`，配合已有 `_DB_LOCK` 串行化写入。`gene_scores` 同理。

### A 验收
- 9 个 DB `PRAGMA journal_mode` 全返回 `wal`
- `busy_timeout` 全返回 `5000`
- 既有测试全绿（`pytest backend/tests/ -m "not live"`）

---

## 阶段 B：路由层 + 分表分库基础设施

### B1: db_partition_router.py
新建 `backend/db_partition_router.py`：

```python
from config import PRIVATE_DATA_DIR
import os

def resolve_partition(date_str: str) -> tuple[str, str]:
    """date → (db_path, table_name)。
    '2026-08-20' → ('.vibe-research/seal_intraday_2026.db', 'seal_intraday_snapshots_202608')
    """
    year = date_str[:4]
    month = date_str[:7].replace("-", "")
    db_path = os.path.join(PRIVATE_DATA_DIR, f"seal_intraday_{year}.db")
    table_name = f"seal_intraday_snapshots_{month}"
    return db_path, table_name

def ensure_partition(date_str: str) -> tuple[str, str]:
    """resolve + 建表建索引（幂等）。"""
    db_path, table = resolve_partition(date_str)
    # 建表 DDL + 3 索引（幂等 CREATE IF NOT EXISTS）
    return db_path, table

def get_latest_partition() -> tuple[str, str]:
    """路由到当年最新月表（SELECT MAX(date) 用）。"""
    # 遍历当年库的所有月表，取最大的 YYYYMM
```

### B2: 分表 DDL 模板
`ensure_partition` 内建表 + 3 索引（与原表一致，含 low_price/limit_pct 字段，兼容 S070 R6）。

### B3: config 常量
`config/__init__.py` 新增 `SEAL_INTRADAY_DIR`（= `PRIVATE_DATA_DIR`，分库文件放同目录）+ `seal_intraday_db_path(year)` 函数。

### B 验收
- `resolve_partition('2026-08-20')` 返回正确路径+表名
- `ensure_partition('2026-08-20')` 幂等建表+索引
- `get_latest_partition()` 返回最新月表

---

## 阶段 C：seal_intraday_collector 改造 + 历史迁移

### C1: save_snapshots 改造
`save_snapshots(rows)` 按 row.date 路由到对应分表，跨月批量分桶写入：

```python
def save_snapshots(rows):
    # 按 date 分桶
    buckets = defaultdict(list)
    for r in rows:
        db_path, table = resolve_partition(r["date"])
        buckets[(db_path, table)].append(r)
    for (db_path, table), batch in buckets.items():
        ensure_partition(batch[0]["date"])
        conn = get_healthy_conn(db_path, check_same_thread=False)
        with _DB_LOCK:
            conn.executemany(f"INSERT INTO {table} ...", batch)
            conn.commit()
        conn.close()
```

### C2: 查询函数改造
- `get_snapshots_by_code(code, date)` → `resolve_partition(date)` 后查分表
- `get_latest_snapshots(date)` → 同理
- `SELECT DISTINCT code FROM ... WHERE date=?` → 路由到分表

### C3: prune 废弃 + 归档
`prune_old_snapshots` 改为 `archive_old_partitions()`：不删除，只标记冷热（当年=热，历史年=冷）。scheduled_tasks 调用点同步改。

### C4: 历史数据迁移脚本
新建 `backend/tools/migrate_seal_intraday_partition.py`：
1. 读旧 `seal_intraday.db` 的 `seal_intraday_snapshots` 全量
2. 按 date 路由到对应分表写入
3. 行数对比验证
4. 旧库重命名 `.bak`

### C5: SELECT MAX(date) 路由
`strategies/impl/db_based.py` 和 `intraday_features.py` 的 `SELECT MAX(date)` 改为 `get_latest_partition()` 路由。

### C 验收
- 迁移后行数 = 16,647
- 既有 `test_s055_seal_intraday_collector.py` 全绿
- `test_s070_seal_intraday_executor.py` 全绿
- 前端 sparkline 正常

---

## 阶段 D：消费方适配 + 月度 VACUUM

### D1: 消费方全适配
grep 所有 `seal_intraday_snapshots` 引用，确保全部走路由层：
- `strategies/impl/db_based.py:33` — `SELECT DISTINCT code` → 路由
- `strategies/intraday_features.py:259` — `WHERE date=? AND code=?` → 路由
- `scheduled_tasks.py:833` — prune 改为 archive

### D2: 月度 VACUUM executor
`scheduled_tasks.py` 新增 `monthly_vacuum` executor：当年库 `VACUUM` + `wal_checkpoint(TRUNCATE)`，月初触发。

### D 验收
- grep `seal_intraday_snapshots` 无硬编码表名引用（全走路由）
- `monthly_vacuum` 注册成功，手动触发不报错

---

## 阶段 E：离线索引兜底 + 验收

### E1: gene_scores 覆盖索引预案
`db_health.py` 加 `ensure_gene_scores_cover_index()`：行数 > 50,000 时创建覆盖索引。当前不触发。

### E2: 全量验收
- A1-A8 验收标准逐条过
- 并发压测：ThreadPool(20) 并发写+读，无 `database is locked`

### E 验收
- 覆盖索引函数存在但不触发（行数 < 50,000）
- 压测无锁错误
