# Spec: S059 — 因子 IC 评估（backtest_lite 扩展）

> 状态：草案
> 作者：Codex（DSA 借鉴 grill 会话）  日期：2026-08-11
> 级别：**small-medium**（S043 同形：单函数 + 端点扩展 + Tab 加列）
> 流程门：develop 直提；commit message 记摘要
> 关联：`.scratch/dsa-board-borrowing/issues/01`（Q8 裁决）、S043（分位分析模式）、S040（90 天回填数据前提）、S047（基因权重校准可消费 IC）、DSA `factor_engine.py` compute_factor_ic（原型）

## 1. 问题 / 目标

S043 分位分析回答"因子哪个区间有效"，但没有"因子整体有没有预测力 + 方向"的指标。DSA FactorEngine 的 IC（Pearson + Rank 相关）是标准补件。Q8 裁决：落 `backtest_lite`，续写 S043 模式，不进 factors/registry（采集层非评估层）。

## 2. 背景

- `backtest_lite._calc_factor_percentile_analysis(scatter, factor_name)`（S043）：scatter 数据已含各因子值 + 次日收益，IC 计算零新增取数。
- IC 定义：因子值与次日收益的截面相关系数；RankIC 用秩相关，对异常值稳健。样本量沿用 S043 口径（S040 回填 90 天后充足）。

## 3. 需求清单

- [ ] R1 `backtest_lite._calc_factor_ic(scatter, factor_name)`：返回 `{ic, rank_ic, n}`（Pearson + Spearman 秩相关，纯标准库/现有依赖实现，样本<20 返 None 诚实标注）
- [ ] R2 `BacktestResult` 增 `factor_ic_analysis` 可选字段（不破坏现有字段，S043 同款做法）
- [ ] R3 端点 `GET /api/backtest/factor-analysis` 响应并入 IC（同端点扩展，避免新端点）
- [ ] R4 前端因子分位 Tab 加 IC/RankIC/样本数列

## 4. 受影响文件

| 文件 | 改动 |
|---|---|
| `backend/backtest_lite.py` | _calc_factor_ic + 结果字段 |
| `backend/routers/backtest.py` | factor-analysis 响应扩展 |
| `frontend/.../Backtest` 因子分位 Tab | IC 列 |

## 5. 设计方案

- 与 S043 同数据同端点同 Tab：一次回测同时出分位表 + IC，前端一屏互补。
- Spearman 用秩变换 + Pearson 实现（避免新依赖 scipy；numpy 若已在依赖内可用则用 numpy）——实施时按 requirements 现状选择，不新增第三方包。
- 备选不选：factors/registry（采集层语义不符，Q8 已否）；独立 factor_ic 模块（量级不配）。

## 6. 验收标准

- [ ] A1 pytest -m "not live" 全过：IC 纯函数单测（正相关/负相关/零相关合成样本 + 小样本 None）
- [ ] A2 端点测试：factor-analysis 响应含 ic/rank_ic/n 字段
- [ ] A3 tsc + vitest 过；Tab 渲染缺值显「—」
- [ ] A4 手动验证：对 premium_rate 跑一次 live 回测，IC 与分位表结论方向一致（不一致则在 commit message 记录分析）

## 7. 合规与工程底线自查

- [ ] IC 属历史统计特征呈现，挂轻量风险提醒
- [ ] 不臆造：样本不足返 None，不补零
- [ ] 无新外部数据源（复用回测快照）
- [ ] 判断可复现：IC 计算为纯函数，输入 scatter 可回放

## 8. 测试计划

离线：纯函数单测 + 端点测试 + 前端测试。联网：A4 手动回测冒烟。

## 9. 风险与回滚

- IC 误导（小样本高相关）：n<20 返 None + 前端同时展示样本数；回滚＝字段隐藏。
