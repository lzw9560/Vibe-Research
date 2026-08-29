# Spec: S089 — SQLite 并发性能加固与 seal_intraday 分表分库

> 状态：部分实现：WAL+busy_timeout 脚本已落地，分表分库 deferred（2026-08-22）
> 作者：lzw  日期：2026-08-20
> 关联：`../S037-gene-db-迁移/spec.md`（路径常量体系复用）、`../S070-intraday采集管道/spec.md`（R7 派生查询需走路由层）、`backend/risk/seal_intraday_collector.py`、`backend/config/__init__.py`

## 1. 问题 / 目标

随着系统运行，SQLite 在并发写入与数据增长维度存在防御性风险。经 grill 五轮 + 数据摸底确认：

- **容量已证伪**：当前 9 个 DB 共 ~12MB，3 年推算 ~50MB，远未触及 SQLite 瓶颈（官方支持 281TB）。
- **并发真实风险**：8/9 的 DB 未启用 WAL 模式（`delete` journal），单进程内 asyncio + ThreadPoolExecutor 软并发下，高频写入表 `seal_intraday_snapshots`（5,549 行/日）与其他 DB 读/写线程并发时可能 `database is locked`。
- **性能真实风险**：`seal_intraday_snapshots` 永久保留后 3 年 ~10.8M 行（~2.2GB），单表查询变慢；离线分析脚本 6 处全表扫描 `gene_scores`（当前 6,943 行，3 年 ~33,000 行，不急但需预留）。

**目标**：(1) 全量 WAL + busy_timeout 加固并发；(2) `seal_intraday_snapshots` 按年分库 + 按月分表，永久保留不删；(3) 离线分析索引兜底预案。

## 2. 背景

### 现状数据（exp-2 摸底，2026-08-20）

| 指标 | 数值 |
|---|---|
| 总数据量 | ~12 MB |
| 日均净新增 | ~5,900 行（94% 来自 seal_intraday_snapshots） |
| 最大单表 | `seal_intraday_snapshots` 16,647 行（4.1 MB） |
| WAL 覆盖 | 仅 1/9 DB（`market_data.db`） |
| JOIN 复杂度 | 0 处 |
| 全表扫描风险 | 6 处（均离线工具） |

### seal_intraday_snapshots 表结构

```sql
CREATE TABLE seal_intraday_snapshots (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ts TEXT NOT NULL, date TEXT NOT NULL, code TEXT NOT NULL, name TEXT,
    pool TEXT, price REAL, seal_amount REAL, open_count REAL,
    first_seal_time REAL, consec_boards REAL, sector TEXT,
    float_market_cap REAL, index_5min_change REAL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    low_price REAL, limit_pct REAL
);
-- 索引：idx_seal_intraday_date_code(date,code) / idx_seal_intraday_code_ts(code,ts) / idx_seal_intraday_ts(ts)
```

### 查询模式（11 处，100% 带 date 或 code+date）

- `WHERE code=? AND date=? ORDER BY ts` — 单股时序（sparkline）
- `WHERE date=?` — 当日全量
- `SELECT DISTINCT code FROM ... WHERE date=?` — 当日股票清单
- `SELECT MAX(date)` — 最新交易日
- `DELETE FROM ... WHERE date < ?` — 清理（永久保留后此条废弃）

**关键事实**：所有查询天然按日期分区，无跨月范围扫描。

### 并发模式（代码探明）

- 无 `multiprocessing`、无 `ProcessPoolExecutor` 跨进程写入
- `ThreadPoolExecutor`：newsradar(max_workers=40)、funnel(max_workers=2)、position_advisor(max_workers=5)、debate
- `asyncio.to_thread` 大量使用——同步 IO 丢线程池
- 所有 DB 读写都在同一 uvicorn 进程内（单进程软并发）

### spec 逻辑冲突审查

**S037（已实现）冲突**：路径常量统一到 `config/__init__.py` 的 `PRIVATE_DATA_DIR` + 语义库文件名常量（`GENE_SCORES_DB`/`STI_TIMELINE_DB`/`WINRATE_DB`）。S089 分库后 `seal_intraday` 文件名变化（`seal_intraday_YYYY.db`），需复用 `PRIVATE_DATA_DIR` 并新增分库命名规则，兼容 S037 常量体系。**处置：共存**——新增 `seal_intraday_db_path(year)` 函数返回分库全路径，不改动 S037 已有常量。

**S070（草案，R7 未实现）冲突**：S070 R7 从 `seal_intraday_snapshots` 派生战法因子（last_lock_time/broken_duration_min/max_drop_pct），查询 `WHERE date=? AND code=?`。S089 分表后这些查询需走路由层。**处置：共存**——S089 提供路由层 `resolve_table(date)` 返回 `(db_path, table_name)`，S070 R7 实现时调用此路由。S070 R6 的 `ALTER TABLE ADD COLUMN` 已落地，分表迁移时新表结构含 low_price/limit_pct 字段（已确认 schema 含此二列）。

## 3. 需求清单

### R1: WAL 模式全量启用
- [ ] R1.1 8 个未启用 WAL 的 DB 统一 `PRAGMA journal_mode=WAL`（seal_intraday/gene_scores/funnel_cache/winrate/zt_history/sti_timeline/verification_card/kline_history）
- [ ] R1.2 在连接初始化时设置（非一次性脚本），保证新建 DB 也启用
- [ ] R1.3 `market_data.db` 已有 WAL，不重复

### R2: busy_timeout 统一设置
- [ ] R2.1 所有连接 `PRAGMA busy_timeout=5000`（5 秒）
- [ ] R2.2 锁竞争时等待而非立即报 `database is locked`

### R3: 连接复用优化
- [ ] R3.1 高频写入 DB（`seal_intraday`、`gene_scores`）用单连接 + `check_same_thread=False`
- [ ] R3.2 连接复用需配合 `_DB_LOCK`（已有）保证写入串行化
- [ ] R3.3 避免每次 `connect` 的开销

### R4: seal_intraday_snapshots 按年分库 + 按月分表
- [ ] R4.1 分库命名：`seal_intraday_YYYY.db`（如 `seal_intraday_2026.db`）
- [ ] R4.2 分表命名：`seal_intraday_snapshots_YYYYMM`（如 `seal_intraday_snapshots_202608`）
- [ ] R4.3 路由层 `resolve_partition(date_str) -> (db_path, table_name)`：date → 年库 + 月表 一步映射
- [ ] R4.4 `save_snapshots` 改为按行 date 路由到对应分表写入
- [ ] R4.5 `get_snapshots_by_code` / `get_latest_snapshots` / `SELECT DISTINCT code` 全部走路由层
- [ ] R4.6 `SELECT MAX(date)` 路由到当年库（最新月表）
- [ ] R4.7 `prune_old_snapshots` 废弃删除逻辑，改为"归档冷库"标记（永久保留不删）

### R5: 历史数据迁移
- [ ] R5.1 现有 `seal_intraday.db` 的 16,647 行迁入 `seal_intraday_2026.db` 的对应月表
- [ ] R5.2 迁移脚本验证行数一致 + 索引重建
- [ ] R5.3 旧库保留 `.bak` 不删

### R6: 月度 VACUUM
- [ ] R6.1 热库（当年）月度 VACUUM（scheduled task 月初触发）
- [ ] R6.2 冷库（历史年）归档时 VACUUM 一次

### R7: 离线分析索引兜底（条件触发）
- [ ] R7.1 `gene_scores` 全表扫描查询预留覆盖索引方案（`CREATE INDEX idx_gene_scores_cover ON gene_scores(date, code, data_source, total_score)`）
- [ ] R7.2 仅在行数 > 50,000 时触发创建（当前 6,943，3 年 ~33,000，不急）

## 4. 受影响文件

| 文件 | 改动 |
|---|---|
| `backend/config/__init__.py` | 新增 `seal_intraday_db_path(year)` + `SEAL_INTRADAY_DIR` 常量 |
| `backend/db_partition_router.py`（新） | `resolve_partition(date)` 路由映射工具 |
| `backend/risk/seal_intraday_collector.py` | save/get/prune 全部改走路由层 + 连接复用 |
| `backend/strategies/impl/db_based.py` | `SELECT DISTINCT code` 路由层适配 |
| `backend/strategies/intraday_features.py` | `WHERE date=? AND code=?` 路由层适配 |
| `backend/scheduled_tasks.py` | prune 改为归档 + 月度 VACUUM executor |
| `backend/db_health.py`（新或扩） | WAL/busy_timeout 连接初始化统一工具 |
| `backend/tools/migrate_seal_intraday_partition.py`（新） | 一次性迁移脚本 |

## 5. 设计方案

### 5.1 路由层设计（R4 核心）

```python
# backend/db_partition_router.py
from config import PRIVATE_DATA_DIR
import os

def resolve_partition(date_str: str) -> tuple[str, str]:
    """date → (db_path, table_name)。
    
    '2026-08-20' → ('.vibe-research/seal_intraday_2026.db', 'seal_intraday_snapshots_202608')
    """
    year = date_str[:4]
    month = date_str[:7].replace("-", "")  # '202608'
    db_path = os.path.join(PRIVATE_DATA_DIR, f"seal_intraday_{year}.db")
    table_name = f"seal_intraday_snapshots_{month}"
    return db_path, table_name
```

### 5.2 不选的备选方案

- **不引入新 DB（DuckDB/PostgreSQL）**：容量 12MB→50MB 远未触瓶颈，单进程软并发 SQLite WAL 足够，引入新 DB 带来迁移+双写+运维成本不划算。
- **不按日分表**：粒度太细，单日 ~14,455 行太碎，表数量爆炸（250 表/年）。按月 ~300K 行/表粒度合适。
- **不按月分库**：单月 ~60MB，按年分库 ~500MB 是 SQLite VACUUM/checkpoint 舒适区上限。
- **不跨进程**：当前无跨进程写入，WAL 足够。若未来引入独立 worker 进程，再评估。

### 5.3 分表 DDL 模板

每月表结构相同，索引相同：

```sql
CREATE TABLE seal_intraday_snapshots_YYYYMM (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ts TEXT NOT NULL, date TEXT NOT NULL, code TEXT NOT NULL, name TEXT,
    pool TEXT, price REAL, seal_amount REAL, open_count REAL,
    first_seal_time REAL, consec_boards REAL, sector TEXT,
    float_market_cap REAL, index_5min_change REAL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    low_price REAL, limit_pct REAL
);
CREATE INDEX idx_YYYYMM_date_code ON seal_intraday_snapshots_YYYYMM(date, code);
CREATE INDEX idx_YYYYMM_code_ts ON seal_intraday_snapshots_YYYYMM(code, ts);
CREATE INDEX idx_YYYYMM_ts ON seal_intraday_snapshots_YYYYMM(ts);
```

## 6. 验收标准

- [ ] A1 9 个 DB 全部 `PRAGMA journal_mode` 返回 `wal`
- [ ] A2 所有连接 `PRAGMA busy_timeout` 返回 `5000`
- [ ] A3 `seal_intraday_snapshots` 写入后按月分表，`resolve_partition('2026-08-20')` 返回正确路径+表名
- [ ] A4 迁移后行数一致：新分表总行数 = 旧表 16,647 行
- [ ] A5 前端 sparkline 查询单股时序正常返回（路由层透明）
- [ ] A6 `SELECT MAX(date)` 返回最新交易日（路由到当年最新月表）
- [ ] A7 月度 VACUUM scheduled task 注册成功，手动触发不报错
- [ ] A8 `database is locked` 在并发写入压测下不出现（模拟 ThreadPool 20 并发写）

## 7. 合规与工程底线自查（逐条确认）

- [x] 研判/推荐/买卖时机属系统能力；本 spec 纯存储层加固，不涉及用户可见输出
- [x] 判断可复现：行数迁移用 `sqlite3 COUNT(*)` 前后对比验证
- [x] 涨停四池/连板股榜个股属公开榜单客观事实；本 spec 不涉及数据呈现
- [x] 用户私有数据（持仓/研报/key）未进 git、未上传；`.vibe-research/` 已在 .gitignore
- [x] 新增东财端点走 `em_get()` 限流；本 spec 不新增外部端点
- [x] spec 逻辑冲突审查：S037 路径常量体系兼容（共存）、S070 R7 派生查询适配路由层（共存）

## 8. 测试计划

- `pytest backend/tests/test_s089_partition_router.py` — 路由层单元测试
- `pytest backend/tests/test_s055_seal_intraday_collector.py` — 既有测试不 break（路由层透明）
- `pytest backend/tests/test_s070_seal_intraday_executor.py` — S070 既有测试不 break
- 迁移脚本 dry-run：`python backend/tools/migrate_seal_intraday_partition.py --dry-run`
- 并发压测：ThreadPool(20) 并发写 + 读，验证无 `database is locked`
- 手动验收：前端 sparkline / 当日候选池 / MAX(date) 路由

## 9. 风险与回滚

| 风险 | 影响 | 回滚 |
|---|---|---|
| 分表后查询遗漏路由层 | 查询报 `no such table` | grep 所有 `seal_intraday_snapshots` 引用确保全适配 |
| 迁移脚本行数不一致 | 数据丢失 | 旧库保留 `.bak`，迁移前后 COUNT 对比 |
| WAL 模式下 `.db-wal` 文件膨胀 | 磁盘占用 | 月度 VACUUM + `PRAGMA wal_checkpoint(TRUNCATE)` |
| 跨月查询路由失效 | 历史回看报错 | 查询模式已确认 100% 带 date，无跨月范围扫描 |
| S070 R7 实现时未走路由层 | 派生查询报错 | S070 spec 已标注依赖 S089 路由层；grill 阶段 code review 把关 |
