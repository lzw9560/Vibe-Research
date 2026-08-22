# Tasks: S012 — 工作流标灰

> 依赖 `../S011`（状态机接线后）。本次**不补功能**。

## 任务清单

| ID | 任务 | 依赖 | 验收 |
|---|---|---|---|
| T1 | `realtime_workflow.monitor_stock` → NotImplementedError | — | 抛错；签名保留 |
| T2 | `realtime_workflow.check_bomb_alerts` 红预警分支 → NotImplementedError | — | 抛错 |
| T3 | `realtime_workflow._signals` 保留空 list（不返 None） | — | 不误导为"无信号" |
| T4 | `post_market_workflow._settle_recommendations` → NotImplementedError | — | 抛错；签名保留 |
| T5 | `post_market._generate_llm_review`/`_generate_next_day_strategy` → NotImplementedError | — | 抛错 |
| T6 | `post_market._calculate_win_rate`/`_optimize_strategies` 保留，标依赖未实现 | — | 注释清晰 |
| T7 | `trading_workflow.run(stage)` try/except NotImplementedError → 返 `not_implemented` | T1-T5 | 不崩溃 |
| T8 | 删 `pre_market_workflow._build_strategy_match` 死代码 | — | run 不依赖 |
| T9 | `IntradayMonitor.tsx` 据 `not_implemented` 显示灰徽标+禁用 | T7 | 不展示空数据当结果 |
| T10 | `PostMarketReview.tsx` 同 T9 | T7 | 同上 |
| T11 | `<WorkflowStage>`（S014）内置 `notImplemented` 分支 | T9 | 渲染灰徽标 |
| T12 | 单测 `test_realtime_post_stubs`（抛错+编排不崩） | T7 | 全过 |
| T13 | 前端 vitest 快照（徽标渲染） | T9 | 快照过 |
| T14 | `pytest -m "not live"` + `npx vitest run` | T12,T13 | 全绿 |
| T15 | diff 审查：确认无新功能逻辑 | T1-T8 | A6 无新实现 |

## 依赖图
```
T1-T6(并行桩改) ─ T7 ─ T9,T10 ─ T11 ─ T13
T8(并行)
T7 ─ T12 ─ T14
T1-T8 ─ T15
```

## 合规检查点
- 桩不输出方向性判断
- 「未实现」徽标客观不误导
- T15 diff 确认无新功能（涉买卖时机的不补）
