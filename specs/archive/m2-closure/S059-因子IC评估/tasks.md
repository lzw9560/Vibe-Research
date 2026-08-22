# S059 任务拆分（原子任务 + 依赖 + 验收）

> develop 直提；small-medium，续写 S043 模式。

| # | 任务 | 依赖 | 验收 |
|---|------|------|------|
| T1 | `_calc_factor_ic(scatter, factor_name)` 纯函数：Pearson IC + Spearman RankIC + 样本数 n；n<20 返 None；零新依赖（numpy 按 requirements 现状） | — | 单测：正/负/零相关合成样本 + 小样本 None + 常量序列 |
| T2 | `BacktestResult.factor_ic_analysis` 可选字段（不破坏现有字段） | T1 | 序列化回归测试 |
| T3 | `GET /api/backtest/factor-analysis` 响应并入 ic/rank_ic/n | T2 | 端点测试 |
| T4 | 前端因子分位 Tab 加 IC/RankIC/样本数列（缺值显「—」） | T3 | vitest + tsc |
| T5 | live 冒烟：premium_rate 跑一次回测，IC 与分位表方向一致性记录 | T3 | commit message 记录分析 |

## 执行序

T1 → T2 → T3 → T4（串行短链）；T5 最后。
