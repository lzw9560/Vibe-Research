# S052 回测快照回填与缺口补跑 · plan（含 grill 决策）

> 级别 medium（develop 直提，勤 commit；无 spec 独立文件，决策即本文）。
> 目标：回测页「战法胜率趋势」从 1 个点补到 ~60 个点，并保证以后不再断档。
> 实施方：新会话（HANDOFF-PROMPT）。本 plan 所有数字 2026-08-11 核实。

## grill 锁定的决策

| # | 决策 |
|---|---|
| D1 | 一次性回填最近 60 个**有 gene_scores 数据的交易日**（与 R21 防封口径一致：只跑 DB 已有日，不触发外部采集） |
| D2 | 启动缺口补跑：后端启动时查 backtest_daily_snapshots 最后一个有数据的交易日，把它之后缺失的交易日全部补上（不止补昨天） |
| D3 | 已核实调度器激活：limitup_precompute 2026-08-10 15:30 准时跑过；「每日回测快照」任务 enabled，生于 2026-08-09 17:01:29（比窗口晚 89 秒）从未被 cron 触发（last_run=None）。不改 cron，靠 D2 兜底进程缺席 |
| D4 | 快照口径与现有 cron 一致：payload lookback_days=30（快照=30 日滚动窗口统计）；回填不改成 60 |
| D5 | 双引擎都补（lite + strategy），与 _execute_daily_backtest_run 现行为一致 |
| D6 | point-in-time：信号只取 as_of 当日及之前的 gene_scores；入场≤as_of；出场 K 线在入场后 max_hold_days 内属合法持仓窗口。写断言测试钉死 |

## 现状事实（已核实）

- backtest_daily_snapshots 仅 1 天：2026-08-09（lite + strategy 各一行，手动触发产物）
- `_execute_daily_backtest_run(payload)`（scheduled_tasks.py:696）写死 `datetime.now()` → snapshot_date=今天、窗口=今天-lookback..今天；无 as_of 参数
- 任务表行：id=3, name=每日回测快照, cron `0 17 * * 1-5`, payload `{"lookback_days": 30}`, enabled=1
- 读侧：`get_backtest_snapshots(days)`（scheduled_tasks.py:400）→ GET /api/backtest/trend → Backtest.tsx 趋势图
- gene_scores.db 有 150 个交易日数据（回填原料充足）
- lite 引擎：`backtest_lite.run_backtest_async(start, end)`；strategy 引擎：`run_strategy_backtest(lookback)`（内部 `_get_available_dates(lookback)` 取 gene_scores 日期）

## 阶段划分（串行）

### S1 · as_of_date 参数化
- `_execute_daily_backtest_run(payload)` 增可选 `as_of_date`（YYYY-MM-DD）：缺省=今天（行为不变）；给了则 snapshot_date=as_of、窗口终点=as_of
- `run_strategy_backtest(lookback, as_of=None)`：`_get_available_dates` 加 `date <= as_of` 截断；as_of=None 行为不变
- `run_backtest_async(start, end)` 已按日期窗口跑，end=as_of 即可；核实其内部无"今天"硬编码
- 测试：as_of 截断（产出的 trades/snapshot 日期 ≤ as_of）+ 缺省行为不变
- **commit 点**：scheduled_tasks/strategy_backtest 相关测试绿

### S2 · 一次性回填入口
- 新增后台回填入口（二选一，实施时按现有范式择一）：任务 payload `{"backfill_days": 60}` 走 scheduled_tasks 手动触发，或 POST /api/backtest/backfill?days=60（后台线程）
- 回填日列表 = gene_scores 已有日 ∩ 最近 60 个交易日，去掉已有快照的日期（幂等）
- 逐日调 `_execute_daily_backtest_run({"lookback_days": 30, "as_of_date": d})`；单引擎失败不阻断（沿用现兜底），整批串行后台跑
- **commit 点**：回填入口 + 幂等测试绿（跑两次不重复）

### S3 · 执行回填（现在就开始）
- 触发回填 60 个交易日；完成后 GET /api/backtest/trend?days=90 应返 ~60+ 行
- 回填产物是私有数据（market_data.db），不进 git

### S4 · 启动缺口补跑
- 后端启动（main lifespan，start_scheduler 同侧）：查快照最大日期 last_have；gene_scores 已有日中 > last_have 且 ≤ 昨天的缺失日 → 后台排队回填（若启动时已过 17:00 且今天已收盘，含今天）
- 无快照记录时不回溯超过 60 日（防首次启动全量打爆）
- 测试：缺口计算单测（mock 快照表/gene_scores 日期）
- **commit 点**：启动补跑测试绿

### S5 · 回归 + 冒烟
- `pytest -m "not live"` 全绿 + dev server 冒烟：回测页趋势图 ~60 个点

## 边界与纪律

- 只读 gene_scores.db 与本地 mootdx K 线，回填过程**零 em_get**（防封底线）
- 快照写盘 = market_data.db backtest_daily_snapshots 表，私有数据不进 git
- 不动 cron 表达式、不动 daily 任务既有行为（as_of 缺省必须与现状字节级一致）
- 并行会话文件勿动；开工前 `git status` 核对
