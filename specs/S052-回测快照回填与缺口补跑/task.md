# S052 原子任务清单（task）

> 状态图例：`[ ]` 待做 / `[x]` 完成。每任务=最小可验证改动；按 stage 分组，stage 末 commit。
> 测试基线：`cd backend && ../.venv/bin/python -m pytest -m "not live" --no-cov`。
> 纪律：回填零 em_get（只读 gene_scores.db + 本地 mootdx K 线）；快照落 market_data.db（私有，不进 git）；
> 并行会话文件勿动；开工前 `git status`。

## S1 as_of_date 参数化（D1/D6）

- [x] T1 `backend/strategies/strategy_backtest.py`：`run_strategy_backtest(lookback, as_of=None)`——`_get_available_dates` 加 `date <= as_of` 截断；as_of=None 行为与现状字节级一致
  - 验证：单测——as_of='2026-08-05' 时产出 trades 日期全 ≤ 2026-08-05；缺省结果与改动前一致
- [x] T2 `backend/scheduled_tasks.py::_execute_daily_backtest_run`：payload 增可选 `as_of_date`（YYYY-MM-DD）；给了则 snapshot_date=as_of、lite 窗口终点=as_of、strategy 传 as_of；缺省=今天（行为不变）
  - 验证：单测——as_of 路径落快照日期正确；缺省路径与现状一致
- [x] T3 读码核实 `backtest_lite.run_backtest_async(start, end)` 无"今天"硬编码（end=as_of 即截断）；若发现硬编码，修复并加测试
- [x] G1 commit 门：T1-T3 测试绿

## S2 一次性回填入口（D1/D4/D5）

- [x] T4 回填入口（按项目现有范式二选一：scheduled_tasks 手动触发 payload `{"backfill_days": 60}` 或 POST /api/backtest/backfill?days=60）：
  - 目标日 = gene_scores 已有日 ∩ 最近 60 个交易日 − 已有快照日（幂等）
  - 后台线程串行逐日调 `_execute_daily_backtest_run({"lookback_days": 30, "as_of_date": d})`（D4：口径 30 与 cron 一致）
  - 单日失败记 warning 不阻断整批；全程零 em_get
- [x] T5 幂等 + 截断测试：连跑两次回填不产生重复快照行；任一回填日产出 snapshot_date ≤ as_of
- [x] G2 commit 门：回填入口测试绿

## S3 执行回填（D1：现在就开始）

- [x] T6 触发回填 60 个交易日（后端 uvicorn --reload 热加载，改完代码直接调入口即可，勿杀 dev server）
  - 验证：完成后 `GET /api/backtest/trend?days=90` 返回 ~60 行；backtest_daily_snapshots 按日连续
- [x] G3 冒烟门：趋势端点数据齐（此步非 commit，是运行验证）

## S4 启动缺口补跑（D2/D3）

- [x] T7 后端启动钩子（main lifespan，start_scheduler 同侧）：查 backtest_daily_snapshots 最大快照日 last_have；gene_scores 已有日中 (last_have, 昨天] 的缺失日排队回填；启动时已过 17:00 且今天已收盘则含今天；last_have 为空时回溯上限 60 日
  - 验证：缺口计算单测（mock 快照表 + gene_scores 日期序列：跨周末缺口 / 全空上限 / 无缺口不触发）
- [x] G4 commit 门：启动补跑测试绿

## S5 全量回归 + 冒烟

- [x] T8 pytest 全量绿（对比开工基线无回归）
- [ ] T9 dev server :8900 冒烟（用户走查）：回测页「战法胜率趋势」~60 个点；重启后端验证启动补跑无重复写入
- [ ] T10 task.md 勾选 + 收尾 commit（feat(S052): ...）
