# 任务拆分 · S043 次日溢价率单因子分位分析

> 对应：`spec.md`（需求）、`plan.md`（技术方案）
> 依赖：S040 先合并。级别：small，直接 develop 提交。
>
> 进度（2026-08-09）：阶段 A（A1/A2/A3）+ 阶段 B（B1/B2/B3）已完成，见 develop `0a867eb`；测试 `tests/test_s043_factor_percentile.py` 9/9 通过。阶段 C+D 推迟至 S040（90 天数据）合并后。

---

## 阶段 A · 泛化分位函数（R1/R2）

| ID | 任务 | 依赖 | 改动文件 | 验收方式 | AC |
|---|---|---|---|---|---|
| A1 | 抽 `_calc_factor_percentile_analysis(scatter, factor_key, buckets)` 通用函数 | — | `backend/backtest_lite.py` | 单测传不同 factor_key + buckets -> 正确分桶 | A1 |
| A2 | 现有 `_calc_percentile_analysis` 改为调泛化版的特例 | A1 | `backend/backtest_lite.py` | 现有测试不破 | A3 |
| A3 | 定义 `_PREMIUM_BUCKETS` 四档 | A1 | `backend/backtest_lite.py` | 常量存在 | A1 |

## 阶段 B · scatter + BacktestResult 扩展（R2/R3）

| ID | 任务 | 依赖 | 改动文件 | 验收方式 | AC |
|---|---|---|---|---|---|
| B1 | `generate_scatter_data` point 加 `factor_premium_rate` 字段 | — | `backend/backtest_lite.py` | 散点数据含因子值 | A1 |
| B2 | `BacktestResult` 加 `factor_percentile_analysis` 可选字段 | A1 | `backend/backtest_lite.py` | dataclass 不报错 | A3 |
| B3 | `run_backtest_async` 内调泛化版填 `factor_percentile_analysis` | A1,B2 | `backend/backtest_lite.py` | result 含新字段 | A3 |

## 阶段 C · API + 前端（R4/R5）

| ID | 任务 | 依赖 | 改动文件 | 验收方式 | AC |
|---|---|---|---|---|---|
| C1 | `GET /api/backtest/factor-analysis` 端点 | B1,A3 | `backend/routers/backtest.py` | curl -> 返回四档分位 | A1,A2 |
| C2 | 单测：factor-analysis 端点 mock scatter | C1 | `backend/tests/test_factor_analysis.py` | pytest 过 | A1 |
| C3 | `api.ts` 新增 `factorAnalysis` 调用 | C1 | `frontend/src/lib/api.ts` | tsc 过 | A4 |
| C4 | `Backtest.tsx` 新增"因子分位" Tab + 表格 | C3 | `frontend/src/pages/Backtest.tsx` | tsc 过；mock 渲染四档表 | A4 |

## 阶段 D · 集成验收

| ID | 任务 | 依赖 | 改动文件 | 验收方式 | AC |
|---|---|---|---|---|---|
| D1 | pytest -m "not live" 全绿 | C2 | — | 全过 | A5 |
| D2 | `GET /api/backtest/result` 不受影响（新字段可选，不破坏现有） | B2 | — | curl result -> 现有字段不变 | A3 |
| D3 | 前端因子分位 Tab 渲染 | C4 | — | 肉眼确认 | A4 |
