# S059 原子任务清单

> 级别：small-medium（S043 同形：单函数 + 端点扩展 + Tab 加列）
> 基线：后端 1009 passed / 前端 40 files 296 tests（S054 验收后）。
> 依赖：无外部，复用 S043 scatter 数据 + S040 回填 90 天样本。

## S1 后端 IC 纯函数 + 结果字段

- [x] T1 `backtest_lite._calc_factor_ic(scatter, factor_key)`：
  - 返回 `{ic, rank_ic, n}`（Pearson + Spearman 秩相关）
  - 纯标准库实现（statistics + 手写秩变换，不引 scipy）
  - 样本<20 返 `None` 诚实标注（不补零）
  - 因子值/收益缺失逐对排除
  - 单测：正相关/负相关/零相关合成样本 + 小样本 None + 缺失排除 + 并列秩 + 空集 + 4 位小数
  - commit 门：纯函数单测绿 ✅ 13 passed

- [x] T2 `BacktestResult` 增 `factor_ic_analysis: dict[str, Any] | None = None`（不破坏现有字段，S043 同款）
  - `run_backtest_async` 内调用 `_calc_factor_ic(scatter, "factor_premium_rate")` 填入
  - commit 门：既有 backtest 测试不退化 ✅

## S2 端点扩展

- [x] T3 `routers/backtest.py` factor-analysis 响应并入 IC：
  - `GET /api/backtest/factor-analysis` 返回增 `ic_analysis: {ic, rank_ic, n}`（样本不足返 null）
  - 端点测试：响应含 ic/rank_ic/n 字段；样本不足场景返 null ✅ 2 passed

## S3 前端 Tab 加列

- [x] T4 前端因子分位 Tab 加 IC/RankIC/样本数列：
  - 定位 S043 前端组件（Backtest.tsx 因子分位 tab）
  - IC 卡：三格 IC/RankIC/样本对数 + 缺值「样本不足 20 对」+ 判读口径
  - vitest：IC 充足渲染 / 样本不足提示 ✅ 2 new + 4 既有 = 6 passed

## S4 全测与合规

- [x] T5 离线全测：`pytest -m "not live" --no-cov` 全绿（后端 1009+13=1022）；`tsc + vitest run` 全绿（40 files 298 tests）
- [x] T6 合规自查：IC 属历史统计特征，挂轻量风险提醒；样本不足返 None 不补零；无新外部数据源；纯函数可复现

## S5 归档

- [x] T7 spec.md 状态改已实现 + commit `docs(S059): 验收`
