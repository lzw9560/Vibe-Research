# S061 任务拆分（原子任务 + 依赖 + 验收）

> develop 直提，勤 commit。Phase 1 范围：系统信号自动入册 + 手动录入 + 自动对账；AI 研判解析为后续。

## R1 数据层

| # | 任务 | 依赖 | 验收 |
|---|------|------|------|
| R1.1 | SQLite 表 `prediction_ledger`（id/source/signal_ref/subject/prediction_type/baseline/expected/horizon/stated_at/due_date/actual/status/attribution），库遵 S037 惯例 | — | migration 幂等测试 |
| R1.2 | 模型 + 状态机（pending → hit/miss/expired/voided） | R1.1 | 状态转移单测 |

## R2 预测入册

| # | 任务 | 依赖 | 验收 |
|---|------|------|------|
| R2.1 | 系统信号自动入册：漏斗 final 候选 + 战法命中 → 「次日溢价>0」预测（source=funnel_candidate/strategy_hit，复用 win_rate 归因口径） | R1.2 | 入册单测（去重：同日同股同来源一条） |
| R2.2 | 手动录入端点 `POST /api/prediction`（subject/expected/horizon 用户填） | R1.2 | 端点测试 + 字段校验 |

## R3 自动验证

| # | 任务 | 依赖 | 验收 |
|---|------|------|------|
| R3.1 | 对账函数：到期日取实际收益（复用 backtest_lite 次日收益口径）→ hit/miss；K 线缺失 → voided 诚实标注 | R1.2 | 单测（命中/未中/缺数据） |
| R3.2 | 定时调度：每日盘后扫到期预测（幂等） | R3.1 | 幂等测试 |

## R4 统计 + 呈现

| # | 任务 | 依赖 | 验收 |
|---|------|------|------|
| R4.1 | 命中率统计：按 source/战法/周期分桶（n/命中率/平均收益），样本<10 标注不足 | R3.1 | 统计单测 |
| R4.2 | 与 win_rate_tracker 联动：对账结果写归因（signal_source/signal_ref 已有列） | R3.1 | 联动测试 |
| R4.3 | 端点 `GET /api/prediction/ledger`（账本 + 统计） | R4.1 | 端点测试 |
| R4.4 | 前端预测账本（挂胜率页或独立 Tab）+ 三问页「中了多少」引用命中率 | R4.3 | vitest + tsc + 走查 |

## 执行序

R1.1 → R1.2 →（R2.1 ∥ R2.2）→ R3.1 → R3.2 → R4.1/R4.2 → R4.3 → R4.4。
