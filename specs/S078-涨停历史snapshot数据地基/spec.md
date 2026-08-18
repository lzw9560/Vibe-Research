# Spec: S078 — 涨停历史 snapshot 数据地基

> 状态：已实现 + live 验证 + 15 日 backfill（2026-08-18）；daily task cron `0 16` 累积中，3-6 月后供 B1 复验

## 实现进度（2026-08-18）

- ✅ `backend/data/zt_history_store.py`：`snapshot_zt_pool` + `load_zt_history` + `list_history_dates` + inline `CREATE TABLE IF NOT EXISTS`（避开 migration 接线坑）
- ✅ `backend/scheduled_tasks.py`：`zt_history_snapshot` 任务类型 + `_execute` + seed cron `0 16 * * 0-4`
- ✅ 离线单测 6/6（round-trip / 幂等 / 多日 / 空池 / 日期格式 / 归一辅助）
- ✅ live 验证：`snapshot_zt_pool(2026-08-14)` 写 63 行（52 首板 + 11 连板），读回一致
- ✅ backfill：近 em 服务窗口（~07-29→08-18，~3 周非整 1 月）15 交易日 / 1257 行已入 DB（head-start）
- ⏳ A7 多日累积：daily task 接力，3-6 月后 B1 改读 `load_zt_history` 复验首板流长窗 verdict

> 注：em_zt_topic_pool 实测 serve ~3 周（07-29→08-18），非 spec §2.1 估的 ~1 月。backfill 拿到 15 日；后续每日累积。
> 作者：lzw9560  日期：2026-08-18
> 关联：S077-B1（受数据地基阻塞）/ S075-首板流 / grill-decisions.md / §44
> 级别：medium（新调度任务 + 新 history DB；零风险只读采集）

## 1. 问题 / 目标

涨停池历史 >1 月**无可用源**：`em_zt_topic_pool`（~1 月）、`ths_limit_up_pool`（老日期返 0，连近期都坏）、`akshare.stock_zt_pool_em`（~1 月，同东财后端）均不长。S077-B1 因此被卡在 19 日 / 563 首板 verdict。**所有涨停类战法的 §44 长窗验证都被此阻塞**（不只首板流）。

本 spec 建**每日涨停池 snapshot 历史 DB**（不 prune，累积 indefinitely），3-6 月后供首板流 + 任何涨停类战法在真长窗复验。**零风险只读数据采集，不改战法/不真建仓。**

## 2. 背景

### 2.1 root cause（2026-08-18 debug 查清）

| 源 | 历史回看 | 测试 |
|---|---|---|
| `astock.em_zt_topic_pool` | ~1 月 | 07-09/06-15/03-16 全 0 |
| `astock.ths_limit_up_pool` | 坏（近期也 0） | 08-14 返 0 |
| `akshare.stock_zt_pool_em` | ~1 月 | 08-14 返 63，老日期全 0 |

kline cache（baostock）有 8 月 bars / 1121 codes / 全字段——**不缺 K 线，缺"每日哪些票涨停"的历史**。

### 2.2 现有采集不够

`seal_intraday_collect`（S055）盘中 60s snapshot 涨停池写 `n_snapshots`，但 `prune_old_snapshots(retention_days=30)` 只留 30 日 → 不是长窗历史。且它是 intraday tick 采集，非干净"终盘涨停池"。

### 2.3 S077-B1 verdict（数据受限）

19 日 / 563 首板：剔除层 lift 1.01-1.06 全 §44 未validated。lift~1.0 robust，但 1 月短窗非定论。须长窗（≥3-6 月）方能 §44 定论。**首板流 stance = raw-shadow**（剔除不进生产 filter，不真建仓，D7d 影子先行），待 S078 累积后复验。

## 3. 需求清单

- [ ] R1 每日盘后 snapshot `em_zt_topic_pool("getTopicZTPool", date, "fbt:asc")` → 涨停 history DB
- [ ] R2 DB schema：`zt_history` 表，字段 date(YYYY-MM-DD) + code + name + lbc + zbc + fbt + fund + zje + p + ltsz + fundamt + hybk + snapshot_at
- [ ] R3 **不 prune**（或 prune ≥2 年），累积 indefinitely（每年 ~50 涨停/日 × 250 日 ≈ 12500 行，SQLite 轻松）
- [ ] R4 复用 `em_get` 限流（不裸调，走 `astock.em_zt_topic_pool` 已包熔断+代理）
- [ ] R5 scheduled task：盘后 cron（如 `0 16 * * 0-4`，16:00 收盘后）
- [ ] R6 零风险只读采集（不改战法/不建仓/不影响现有涨停四池 24h 缓存）
- [ ] R7 实现时先查有无现成涨停 history 表（zt_pool / limitup_*）可复用，避免重复建

## 4. 受影响文件

| 文件 | 改动 |
|---|---|
| `backend/data/zt_history_store.py`（新建） | `snapshot_zt_pool(date)` + `load_zt_history(start, end)` + DB schema |
| `backend/scheduled_tasks.py` | +`zt_history_snapshot` 任务类型 + `_execute` + seed cron `0 16 * * 0-4` |
| `.vibe-research/zt_history.db`（新建，私有，已 .gitignore） | 涨停历史 SQLite DB |
| （无战法/生产选股改动） | — |

## 5. 设计方案

### 5.1 采集（照抄 seal_intraday_collect 模式，但终盘 + no-prune）

- 盘后（16:00）调 `astock.em_zt_topic_pool("getTopicZTPool", date, "fbt:asc")` 取**当日终盘涨停池**（含连板，lbc 字段区分首板）。
- 全字段写入 `zt_history` 表（date + code + 全 raw 字段 + snapshot_at）。
- **不 prune**——长窗累积是目的。可选：每年 prune 一次 ≥2 年外的（防止无限增长，但 12500 行/年根本不大，可不 prune）。

### 5.2 复用点

- 调度框架：`scheduled_tasks.TaskExecutor._executors` + seed（照抄 `seal_intraday_collect` / `first_board_filter` 模式）。
- em_get 限流：`astock.em_zt_topic_pool` 已包（CLAUDE.md §1.2 防封底线）。
- DB：私有 `.vibe-research/zt_history.db`（`vr_paths.resolve_data_dir()`，不进 git）。

### 5.3 下游用法（S077-B1 复验）

累积 ≥3-6 月后，S077-B1 改读 `zt_history_store.load_zt_history(start, end)` 替代 `em_zt_topic_pool` 历史取数（后者 ~1 月限制）→ 真长窗 §44 复验首板流剔除。也可供未来连板流/炸板回交流等涨停类战法复验。

## 6. 验收标准

- [ ] A1 `zt_history_snapshot` 任务 seeded（cron `0 16 * * 0-4`）+ `_execute` 跑通写 DB
- [ ] A2 `zt_history` 表 schema 含 date+code+全字段；写入幂等（同 date+code 重复写不重复，或 upsert）
- [ ] A3 不 prune（或 ≥2 年）；DB 路径在 `.vibe-research/`（不入 git）
- [ ] A4 em_get 限流复用（不裸调 requests）
- [ ] A5 零生产影响（git diff 无战法/选股文件改动）
- [ ] A6 离线单测：合成 pool → DB 写入 + load round-trip + 幂等
- [ ] A7 多日累积（人工等数月）后 load_zt_history 返回长窗数据

## 7. 合规与工程底线自查

- [x] 研判/推荐/买卖时机：纯数据采集，无用户可见研判/推荐 → 合规无涉
- [x] 判断可复现：snapshot 原始涨停池字段，非研判；`financial_rigor.py` 不适用
- [x] 涨停四池/个股：只存历史涨停池（公开榜单客观事实），不呈现给用户作推荐
- [x] 用户私有数据：DB 在 `.vibe-research/`（已 .gitignore，不上传）
- [x] 东财端点走 em_get 限流：R4，复用 `astock.em_zt_topic_pool`

## 8. 测试计划

- **离线单测**（`pytest -m "not live"`）：合成涨停池 → `snapshot_zt_pool` 写 DB → `load_zt_history` round-trip + 幂等（同 date+code 重复写不复制）。
- **live**：盘后跑 `_execute_zt_history_snapshot`，验 DB 写入当日涨停池。
- 不进默认 `pytest -m "not live"`（em_get 联网，标 live 或 deselect）。

## 9. 风险与回滚

| 风险 | 处置 |
|---|---|
| 累积慢（3-6 月才 useful） | 预期；首板流 raw-shadow 等待；期间不阻塞别的 |
| em 端点变更/字段变 | 全字段存（含 raw），下游解析容错；字段变可后补 |
| DB 增长 | 12500 行/年极小，可不 prune；若要 prune ≥2 年 |
| 某日采集失败（em 限流/熔断） | catch 不抛，返 error status，次日继续（缺一日不影响长窗） |
| 回滚 | 删任务 + `zt_history_store.py` + DB，零战法影响 |
