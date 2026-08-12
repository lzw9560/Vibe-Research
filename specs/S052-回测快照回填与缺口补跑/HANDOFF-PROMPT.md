# S052 实施交接提示词（交给新会话 Claude）

你接手 Vibe-Research 仓库（/Users/lizhiwei/project/code/stock/Vibe-Research）的 S052 实施（回测快照回填与缺口补跑：as_of_date 参数化 + 60 交易日回填 + 启动补跑）。全程用中文与用户沟通。

## 任务
按同目录 `plan.md` 的阶段顺序（S1→S5）与 `task.md` 的原子任务 T1–T10 执行，每完成一项勾选 task.md。plan.md 的 D1–D6 是用户 grill 后锁定的决策，勿翻案。

## 开工必读
1. `specs/S052-回测快照回填与缺口补跑/plan.md`——决策 + 现状事实（2026-08-11 核实）
2. 同目录 `task.md`——原子任务与 commit 门
3. 根目录 `AGENTS.md`——分级工作流与提交纪律

## 现状
- git 在 develop。开工先 `git status` + `git log --oneline -5`：有并行会话在跑（S050 行为闭环扩展）；绝不 revert 他人改动；S051（基因筛选体验批）可能与本 spec 并行实施，避开其文件（limitup screener/基因筛选前端）
- dev server :8900 在跑（backend=uvicorn **--reload**，frontend=vite），勿杀；后端改代码自动热加载，无需手动重启；注意 --reload 会重跑 lifespan 启动钩子（正好用来验证 T7 启动补跑）
- 快照表现状：backtest_daily_snapshots 仅 2026-08-09 一天（lite+strategy 各一行，手动触发产物）

## 关键代码事实（已核实，不必重复排查）
- `backend/scheduled_tasks.py:696 _execute_daily_backtest_run(payload)`：写死 `datetime.now()`；lite 走 `backtest_lite.run_backtest_async(start, today)`（asyncio.run 驱动），strategy 走 `run_strategy_backtest(lookback)`，落盘 `_save_snapshot(today, engine, result)`
- **缓存坑**：`strategies/strategy_backtest.py` 的 `_CACHE` 只以 lookback_days 为 key（12h TTL）——加 as_of 参数后必须把 as_of 并进 key，否则回填拿错缓存
- `_get_available_dates(lookback)` 取 gene_scores.db 已有日期（只跑 DB 已有日=R21 防封口径）；gene_scores.db 有 150 个交易日（.vibe-research/gene_scores.db，`SELECT DISTINCT date`）
- 任务表（backend/data/market_data.db scheduled_tasks）：id=3 每日回测快照，cron `0 17 * * 1-5`，payload `{"lookback_days": 30}`，enabled=1，last_run=None（生于 2026-08-09 17:01:29 错过窗口，从未被 cron 触发）。调度器本身激活（limitup_precompute 2026-08-10 15:30 准时跑过）——不改 cron
- 读侧：`scheduled_tasks.py:400 get_backtest_snapshots(days)` → `GET /api/backtest/trend?days=N`（routers/backtest.py）→ Backtest.tsx 趋势图
- 启动钩子挂点：`start_scheduler`（scheduled_tasks.py:922）在 main lifespan 启动——缺口补跑挂同侧
- 交易日工具：`backend/vr_paths.py` 有交易日判断（S023 C1）；简单做法直接用 gene_scores 已有日当交易日历（与回填口径天然一致）
- 测试样板：`backend/tests/test_backtest_trend.py`；造临时库参照 `test_migrate_dbs.py::_make_test_db` 模式
- 测试命令：`cd backend && ../.venv/bin/python -m pytest -m "not live" --no-cov`

## 硬约束
- AGENTS.md medium 流程门：develop 直提、勤 commit、最小功能提交（wip: 可）、绝不 revert 他人改动
- **回填零 em_get**：只读 gene_scores.db + 本地 mootdx K 线缓存；任何新增外部调用都是违规
- as_of 缺省路径必须与现状字节级一致（cron 每晚 17:00 还在用）
- 幂等：重复回填同一日期不得产生重复快照行（INSERT 前先查或 OR IGNORE）
- 私有数据：market_data.db gitignored；测试一律临时库，绝不写用户真实库
- 测试先行：阶段测试绿后才 commit（G1–G4 门）

## 范围外（勿扩张）
- 不改 cron 表达式/不改 daily 任务缺省行为；不动趋势图前端渲染（数据齐了图自然全）；不碰战法信号定义（S053 范畴）；不碰基因筛选前端（S051 范畴）

## 完成定义
- task.md T1–T10 全勾
- pytest 全绿
- `GET /api/backtest/trend?days=90` 返回 ~60 行；:8900 回测页趋势图 ~60 个点
- 重启/热加载后启动补跑不重复写入（幂等验证）
- 最终 commit `feat(S052): ...`

执行顺序 S1→S5，阶段门与风险见 plan.md。S3（T6 执行回填）在 S2 测试绿后立即触发——用户要求"现在就开始回填"。
