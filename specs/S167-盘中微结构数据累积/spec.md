# S167 · 盘中微结构数据累积管道（"等 live"）

> 状态：进行中（2026-09-06）｜分级：medium（issue 层单轮 review，免 feature 分支）
> 关联：§44v2（S159）、S055 seal_intraday、S078 zt_history_store、S152 H2 harness、S160/S161 底座

## 1. 问题 / 目标

§44 reframe（S159）结论：edge 在盘中盘口博弈（60s 封单 / 竞价量 / 秒板 / 异动排名），
不在 T-1 选股。S152/S156 已证否"封板时间×开板次数"（lift=0.7843 劣于随机），
但用户选 **"等 live"** 路径——每日累积盘中微结构数据，积累 30-60 天后用 §44v2 框架复测。

**目标**：对"无历史、仅实时"的盘中微结构源建每日快照累积管道，存入
`.vibe-research/intraday_accumulation/`（date-keyed，不 prune，30-60 天累积）。

## 2. 数据源清查（研究结论）

| 源 | 信号 | 现状 | 本 spec 处理 |
|----|------|------|-------------|
| seal_intraday（S055） | 60s 封单额 trajectory + 首封时间 + 炸板 | **已累积**（每 60s 轮询 em_zt_topic_pool，09:25-15:05，partitioned SQLite） | 不重建，仅登记为"已有源" |
| hithink skyrocket/hot_stock/anomaly | 异动排名 trajectory | **实时无历史，未累积** | **新建周期快照**（10min） |
| tencent fetch_raw vol_ratio | 量比 trajectory（资金活跃度代理） | **实时点，未累积** | **新建周期快照**（10min，附 hithink 同周期） |
| baostock 5min（frequency="5"） | 秒板 / 封板时间派生 | 多年历史可回补（S152 已用）；当日 bar T+1 lag | **新建次日冻结**（09:00 冻结 prev_trading_date 涨停股 5min，bars 稳定） |
| 竞价量比 9:15-9:25 | 集合竞价量 / 量比 | **无源**：akshare/tencent/astock 均无；hithink 有 auction 快照端点但**未接线**（hithink_src 仅 5 端点） | **flag：needs new source integration**，不实现 |

## 3. 需求清单

### R1 数据存储 `data/intraday_accumulation_store.py`
- 复用 S078 `zt_history_store` 范式：`vr_paths.resolve_data_dir()` 子目录、inline `CREATE TABLE IF NOT EXISTS`、`threading.Lock`、幂等 UPSERT、缺字段填 None（不臆造）。
- DB：`.vibe-research/intraday_accumulation/intraday_microstructure.db`
- 三表：
  - `intraday_ranking_snapshots(date, ts, source, code, name, rank, heat, rank_change, rank_trend, extra_json, snapshot_at)` PK(date, ts, source, code)
  - `intraday_quote_snapshots(date, ts, code, name, price, change_pct, vol_ratio, turnover_pct, limit_up, limit_down, amount_wan, snapshot_at)` PK(date, ts, code)
  - `baostock_5min_freeze(date, code, name, bars_json, bar_count, captured_at)` PK(date, code)
- 读者：`load_rankings(start,end)` / `load_quotes(start,end)` / `load_5min_freeze(start,end)` / `list_accumulation_dates()`，供未来 §44v2 复用。

### R2 周期快照任务 `intraday_microstructure_snapshot`
- cron `*/10 9-15 * * 0-4`（交易日每 10 分钟，09:00-15:00 触发），executor 内 `vr_paths.is_intraday_time` 门控（09:25-11:30 / 13:01-15:05 外 no-op，防封 + 省请求）。
- 每快照：调 hithink `skyrocket()` + `hot_stock()` + `anomaly_list()`（走 circuit_breaker，失败记 data_status=degraded 不崩）；涨停池 codes 取 hithink `limit_up_pool(today)`（非 em_get，防封）；tencent `fetch_raw(union_codes)` 取 vol_ratio。
- 写 ranking_snapshots + quote_snapshots（date + ts keyed）。

### R3 baostock 5min 次日冻结任务 `baostock_5min_freeze`
- cron `0 9 * * 0-4`（交易日 09:00），冻结 **prev_trading_date** 涨停股当日 5min bars（T+1 lag：次日 09:00 bars 已稳定）。
- 涨停 codes 取 hithink `limit_up_pool(prev_date)`；baostock `query_history_k_data_plus(frequency="5")` 单次 login（复用 S152 `_ensure_bs_login` 范式）。
- 写 baostock_5min_freeze（INSERT OR REPLACE 幂等）。is_trading_day(today) 门控（节假日跳）。

### R4 接线 scheduled_tasks.py
- `_executors` 加 2 项；`_ensure_seed_tasks()` seed 2 任务（幂等 `if not in existing`）。
- `_TASK_TIMEOUTS`：`intraday_microstructure_snapshot`=120s（hithink 3 端点 + tencent 1 批，<60s 稳态）；`baostock_5min_freeze`=600s（~100 股 baostock fetch）。

## 4. 受影响文件

- 新增 `backend/data/intraday_accumulation_store.py`
- 新增 `backend/tests/test_s167_intraday_accumulation.py`
- 改 `backend/config/__init__.py`（加 `INTRADAY_ACCUMULATION_DIR`）
- 改 `backend/scheduled_tasks.py`（2 executors + seed + 2 timeouts）

## 5. 验收标准

- [ ] store 三表建表幂等；UPSERT 幂等（同 date/ts/code 重写不翻倍）；缺字段 None 不臆造。
- [ ] 周期快照任务非交易时段 no-op（is_intraday_time 门控，返 skipped）；交易时段写 ranking + quote 行。
- [ ] hithink 断（无 key / 熔断）→ data_status=degraded，不抛、不崩、不伪装空榜为数据。
- [ ] baostock 冻结任务写 prev_trading_date 涨停股 5min bars；非交易日跳。
- [ ] `pytest -m "not live" --deselect <flaky 集>` 全绿，无回归。
- [ ] 诚实框架：模块 docstring + 任务 description 标注"accumulation for future §44v2, prior LOW (S152/S156 refuted related), no edge claim yet, accumulate 30-60d then test"。

## 6. 合规自查（弱合规 · 工程底线）

- [不臆造] 缺数据填 None / data_status=degraded，不补默认值、不伪装空榜。✓
- [私有数据隔离] 全部写 `.vibe-research/intraday_accumulation/`（vr_paths.resolve_data_dir 子目录，gitignored）。✓
- [防封] 涨停池 codes 走 hithink（非 em_get）；hithink 走 circuit_breaker；tencent urllib 免费不限流。✓
- §44 verdict：本 spec **不出 edge 结论**，仅累积。prior LOW（S152 H2 lift=0.7843 / S156 秒板）已标注。✓
