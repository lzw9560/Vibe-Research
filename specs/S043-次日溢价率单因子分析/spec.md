# Spec: S043 — 次日溢价率单因子分位分析

> 状态：已实现——R1-R5 全部完成（2026-08-10 R4 端点 + R5 前端因子分位 Tab + 端点测试）
> 作者：Codex  日期：2026-08-09（R4/R5：2026-08-10）
> 关联：`../S040-历史数据回填90天/spec.md`（90 天数据是前提）、`backend/backtest_lite.py`（分位分析模式）、`backend/limitup_screener/models.py`（`premium_rate` 因子）、`backend/limitup_screener/data.py`（`factor_premium_rate` DB 字段）、`backend/limitup_strategy.py`（`premium > 60` 条件触发）
>
> 级别：**small**（单函数改动 + 一个新端点）

## 1. 问题 / 目标

`backtest_lite` 的分位分析按 `total_score`（0-60/60-75/75-100）分桶，验证的是整体因子组合有效性。"次日溢价率"（`factor_premium_rate`）这个单因子在 `recommendation_engine` 和 `limitup_strategy` 里被用来加分和触发条件（premium > 60），但从未被独立验证过它的预测力——高溢价率组是否真的次日正收益概率更高？

**目标**：在 `backtest_lite` 加一个按 `factor_premium_rate` 分桶的分位分析函数，新增一个 API 端点返回单因子分位结果。

## 2. 背景

- `backtest_lite._calc_percentile_analysis`（`backend/backtest_lite.py:196`）：按 `gene_score` 三档分桶，输出 `count / avg_return / hit_rate`。
- `factor_premium_rate`：DB 字段，映射到 factors dict 的"次日溢价率"。计算方式 = Wilson 下界调整的连板率（`models.py:101`）。
- `limitup_strategy.py:286-293`：`premium = gene.factors.get("次日溢价率", 0)`，`premium > 60` 触发"高次日溢价"条件加分。
- `recommendation_engine.py:80`：次日溢价率 > 60 加分到 HIGH_QUALITY。
- S040 回填 90 天数据后，单因子分位分析才有足够样本量。

## 3. 需求清单

- [x] R1 新函数 `backtest_lite._calc_factor_percentile_analysis(scatter, factor_name)`: 按指定因子分桶（而非 gene_score），输出各桶 `count / avg_return / hit_rate`
- [x] R2 分桶方案：`factor_premium_rate` 四档（0-30 / 30-50 / 50-70 / 70-100），更细粒度看因子边际效应
- [x] R3 `BacktestResult` 新增 `factor_percentile_analysis` 字段（可选，不破坏现有字段）
- [x] R4 新 API `GET /api/backtest/factor-analysis?start=...&end=...&factor=premium_rate`: 返回单因子分位结果
- [x] R5 前端 Backtest 页面新增 Tab "因子分位"：展示单因子分位表

## 4. 受影响文件

| 文件 | 改动 |
|---|---|
| `backend/backtest_lite.py` | R1/R2/R3 新函数 + BacktestResult 字段 |
| `backend/routers/backtest.py` | R4 新端点 |
| `frontend/src/pages/Backtest.tsx` | R5 新 Tab |

## 5. 设计方案

### D1 泛化分位函数

现有 `_calc_percentile_analysis` 硬编码按 `gene_score` 分桶。抽一个泛化版 `_calc_factor_percentile_analysis(scatter, factor_name, buckets)`，支持任意因子 + 自定义桶边界。现有 `_calc_percentile_analysis` 改为调泛化版的特例（factor_name="gene_score"）。

### D2 scatter 数据需带因子值

当前 `generate_scatter_data` 的 point 只存 `gene_score / next_day_return / code / date / industry`。需要加 `factor_premium_rate` 字段——从 `g.factors.get("次日溢价率", 0)` 取值。

### D3 四档分桶

`factor_premium_rate` 范围 0-100（Wilson 下界 * 100）。四档：
- 0-30：低溢价率
- 30-50：中等
- 50-70：较高
- 70-100：高溢价率

看 hit_rate 和 avg_return 是否随溢价率递增——如果是，因子有预测力；如果平坦或倒挂，因子无效。

## 6. 验收标准

- [x] A1 `GET /api/backtest/factor-analysis?factor=premium_rate` 返回四档分位结果
- [x] A2 每档含 `count / avg_return / hit_rate`
- [x] A3 现有 `GET /api/backtest/result` 不受影响（`factor_percentile_analysis` 是新增字段）
- [x] A4 前端因子分位 Tab 渲染表格
- [x] A5 `pytest -m "not live"` 全过（916 passed；龙虎榜基线 3 例因本地 fallback 缓存被 live 运行覆写为空而挂，恢复基线数据后 6 passed，与 S043 无关）

## 7. 合规与工程底线自查

- [ ] 分析结果属客观历史统计特征，前端挂"历史统计特征，市场有风险"
- [ ] 只读 DB + mootdx K 线，不碰东财
- [ ] 无私有数据进 git

## 8. 测试计划

- pytest -m "not live"：确认泛化分位函数 + 新端点
- 前端打开因子分位 Tab：确认表格渲染

## 9. 风险与回滚

- **因子无效**：分析可能显示溢价率与次日收益无正相关——这是有用的发现（说明因子该降权或移除），不是 bug。
- **回滚**：删除新函数 + 新端点 + 新 Tab。泛化版函数改动不影响现有 `_calc_percentile_analysis` 的行为。
