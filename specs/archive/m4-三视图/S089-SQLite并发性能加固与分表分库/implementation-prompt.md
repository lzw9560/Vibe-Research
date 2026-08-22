# Implementation Prompt: S089 — SQLite 并发性能加固与分表分库

> 本文件为给新 session 的冷启动提示词。读完 spec.md + plan.md + tasks.md 后执行。

## 背景

Vibe-Research 后端 9 个 SQLite DB 共 ~12MB，经 grill 五轮 + 数据摸底确认：容量远未触瓶颈（3年推算 50MB），但并发（8/9 DB 未启用 WAL）和性能（seal_intraday_snapshots 永久保留后 3年 ~10.8M 行）存在防御性风险。

## 你的任务

按 `plan.md` 五阶段（A→B→C→D→E）顺序执行 `tasks.md` 逐条任务。

### 关键约束

1. **spec 逻辑冲突已审查**：
   - S037（已实现）路径常量体系——`config/__init__.py` 的 `PRIVATE_DATA_DIR` + 语义库文件名常量。S089 分库文件 `seal_intraday_YYYY.db` 放同目录，复用 `PRIVATE_DATA_DIR`，新增 `seal_intraday_db_path(year)` 函数，**不改动 S037 既有常量**。
   - S070（草案，R7 未实现）——从 `seal_intraday_snapshots` 派生战法因子的查询需走 S089 路由层 `resolve_partition(date)`。S070 spec 已标注此依赖。

2. **分表 DDL 必须含 low_price + limit_pct 字段**（S070 R6 已落地这两个字段，分表迁移时新表结构必须兼容）。

3. **查询模式已确认 100% 带 date**——所有 `seal_intraday_snapshots` 查询都带 `WHERE date=?` 或 `WHERE code=? AND date=?`，无跨月范围扫描。路由层 `resolve_partition(date_str) -> (db_path, table_name)` 是安全的。

4. **迁移脚本必须 dry-run + 行数对比**——旧库 16,647 行，迁移后新分表总行数必须一致。旧库保留 `.bak`。

5. **既有测试不能 break**：
   - `test_s055_seal_intraday_collector.py` — seal_intraday 采集器
   - `test_s070_seal_intraday_executor.py` — S070 executor
   - `test_intraday_features.py` — intraday 特征
   - `test_s047_weight_recalc.py` — gene_scores 权重重算

### 执行顺序

1. **阶段 A**（WAL 加固）：新建 `db_health.py` + `enable_wal_all_dbs.py` + 高频 DB 连接复用。验收：9 DB WAL 全开，busy_timeout=5000。
2. **阶段 B**（路由层）：新建 `db_partition_router.py`（resolve/ensure/get_latest）+ config 常量 + 单测。验收：路由函数正确返回。
3. **阶段 C**（collector 改造 + 迁移）：`save_snapshots` 分桶写入 + 查询函数路由 + prune 改 archive + 迁移脚本。验收：行数一致，既有测试全绿。
4. **阶段 D**（消费方适配 + VACUUM）：grep 确保无硬编码表名 + 月度 VACUUM executor。验收：grep 干净，VACUUM 不报错。
5. **阶段 E**（离线索引兜底 + 压测）：覆盖索引预案 + 并发压测。验收：压测无锁错误。

### 验证命令

```bash
cd /Users/lizhiwei/project/code/stock/Vibe-Research/backend
.venv/bin/python -m pytest tests/test_s055_seal_intraday_collector.py tests/test_s070_seal_intraday_executor.py tests/test_intraday_features.py tests/test_s047_weight_recalc.py tests/test_s089_partition_router.py tests/test_s089_concurrency.py -v
```

### 关键文件路径

- spec: `specs/S089-SQLite并发性能加固与分表分库/spec.md`
- plan: `specs/S089-SQLite并发性能加固与分表分库/plan.md`
- tasks: `specs/S089-SQLite并发性能加固与分表分库/tasks.md`
- 旧库: `.vibe-research/seal_intraday.db`（迁移后 → `.bak`）
- 新库: `.vibe-research/seal_intraday_YYYY.db`（按年分库）
- collector: `backend/risk/seal_intraday_collector.py`
- config: `backend/config/__init__.py`

### 分支策略

large 级别，走 `feature/S089-sqlite-hardening` 分支（off develop），合并用 `git merge --squash`，一 spec 一 commit `feat(S089): ...`。
