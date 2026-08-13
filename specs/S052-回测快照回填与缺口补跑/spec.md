# Spec: S052 — 回测快照回填与缺口补跑

> 状态：已实现（2026-08-12，commits `9aaa2a5`→`b2b8ae7`→`ff1e6a2`）— D1-D6 全落地，T1-T10 全勾，pytest 全绿，:8900 冒烟通过（趋势图 60 个点，启动补跑幂等）。本 spec 事后补写（原只有 plan/task + HANDOFF），spec 正文从 plan.md 反推归纳。
> 作者：Claude  日期：2026-08-11（plan）/ 2026-08-12（实现）/ 2026-08-13（spec 补录）
> 关联：`../S041-回测定时任务与趋势看板/spec.md`（daily_backtest_run task_type + 趋势端点）、`../S040-历史数据回填90天/spec.md`（历史回填范式）

## 1. 问题 / 目标

回测页「战法胜率趋势」图只有 1 个点（2026-08-09 手动触发的快照），且以后会持续断档——每日回测快照任务（cron `0 17 * * 1-5`）生于 2026-08-09 17:01:29（比窗口晚 89 秒），从未被 cron 触发（last_run=None）。

目标：一次性回填最近 60 个交易日快照（趋势图 ~60 个点），并保证以后不再断档（启动缺口补跑兜底进程缺席）。

## 2. 背景

- `backtest_daily_snapshots` 表仅 1 天（lite + strategy 各一行，手动触发产物）
- `_execute_daily_backtest_run(payload)`（scheduled_tasks.py:696）写死 `datetime.now()` → snapshot_date=今天、窗口=今天-lookback..今天；无 as_of 参数
- gene_scores.db 有 150 个交易日数据（回填原料充足，只读 DB 不触发外部采集=R21 防封口径）
- 缓存坑：`strategies/strategy_backtest.py` 的 `_CACHE` 只以 lookback_days 为 key——加 as_of 后必须并进 key，否则回填拿错缓存

## 3. 需求清单

- [x] R1 as_of_date 参数化：`_execute_daily_backtest_run(payload)` 增可选 `as_of_date`，缺省=今天（行为不变）；`run_strategy_backtest(lookback, as_of=None)` 加 `date <= as_of` 截断；缓存 key 并入 as_of
- [x] R2 一次性回填入口：目标日 = gene_scores 已有日 ∩ 最近 60 交易日 − 已有快照日（幂等），逐日调 `_execute_daily_backtest_run({"lookback_days": 30, "as_of_date": d})`，单日失败不阻断
- [x] R3 执行回填 60 个交易日：完成后趋势端点 ~60 行
- [x] R4 启动缺口补跑：后端启动时查快照最大日 last_have，gene_scores 已有日中 (last_have, 昨天] 缺失日排队回填；无快照时不回溯超过 60 日
- [x] R5 幂等：重复回填不产生重复快照行（INSERT 前查或 OR IGNORE）
- [x] R6 point-in-time：信号只取 as_of 当日及之前的 gene_scores；入场≤as_of；出场 K 线在入场后 max_hold_days 内

## 4. 受影响文件

| 文件 | 改动 |
|---|---|
| `backend/scheduled_tasks.py` | R1：_execute_daily_backtest_run 加 as_of_date；R2：回填入口；R4：启动补跑 _compute_backfill_gap |
| `backend/strategies/strategy_backtest.py` | R1：run_strategy_backtest 加 as_of + _get_available_dates 截断 + 缓存 key 并入 as_of |
| `backend/backtest_lite.py` | R1：核实无"今天"硬编码（end=as_of 即截断） |

## 5. 设计方案

- **as_of 缺省与现状字节级一致**：cron 每晚 17:00 还在用缺省路径，改坏缺省行为=破坏生产任务。
- **回填零 em_get**：只读 gene_scores.db + 本地 mootdx K 线缓存；gene_scores 已有日当交易日历（与回填口径天然一致）。
- **快照口径与 cron 一致**：payload lookback_days=30（30 日滚动窗口统计），回填不改成 60。
- **启动补跑而非改 cron**：调度器激活（limitup_precompute 准时跑过），每日回测任务只是出生晚错过了窗口；改 cron 有风险，靠启动补跑兜底更稳。
- **缺口计算改历史回溯**：原设计只查 last_have 之后，实际改为 `_compute_historical_gap` 历史回溯（commit `b2b8ae7` fix）。

## 6. 验收标准

- [x] A1 as_of 路径产出 trades/snapshot 日期全 ≤ as_of；缺省路径与改动前一致
- [x] A2 连跑两次回填不产生重复快照行（幂等）
- [x] A3 `GET /api/backtest/trend?days=90` 返回 ~60 行；backtest_daily_snapshots 按日连续
- [x] A4 启动补跑：_compute_backfill_gap 返空时重启不重复写入
- [x] A5 pytest 全绿
- [x] A6 :8900 冒烟：趋势图 60 个点

## 7. 合规与工程底线自查（逐条确认）

- [x] 回填零 em_get（只读 gene_scores.db + 本地 mootdx K 线）——防封底线
- [x] 快照写盘 = market_data.db（私有数据 gitignored），不进 git
- [x] 测试一律临时库，绝不写用户真实库
- [x] as_of point-in-time：信号只取 as_of 当日及之前数据，无未来函数
- [x] 不涉及方向性判断/推荐

## 8. 测试计划

- 单测：as_of 截断（产出日期 ≤ as_of）+ 缺省行为不变 + 幂等（跑两次不重复）+ 缺口计算（跨周末/全空上限/无缺口不触发）
- 全量：`pytest -m "not live"`
- 冒烟：:8900 回测页趋势图点数 + 重启幂等验证

## 9. 风险与回滚

- as_of 缺省路径字节级不一致 → 破坏 cron 生产任务（已守：测试钉死缺省行为）
- 缓存 key 未并 as_of → 回填拿错缓存（已守：commit `9aaa2a5` 并入）
- 回填打爆 em_get → 封 IP（已守：零 em_get 口径）
- 回滚：删回填入口 + 启动补跑；as_of 参数缺省=今天不影响存量
