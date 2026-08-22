# Tasks: S034 — SettlementEngine 接线

> 对应 `spec.md`。medium 级：直接 develop 提交，每任务一 commit。

## 任务清单

| ID | 任务 | 需求 | 依赖 | 验收 | 状态 |
|---|---|---|---|---|---|
| T1 | `workflow_state_repo`：`_ensure_columns` 加 `settled_at TEXT` 幂等扩列；`_row_to_state` 补字段；`mark_settled(code, trade_date, settled_at)`；`transition()` settled→candidate 重入清 settled_at=NULL | R1,R4 | — | 扩列+mark+清零单测 | ✅ |
| T2 | `backend/settlement_recorder.py` 新模块：`settlement_summary(entry,exit,trade_date,settled_at)` 纯函数 + `record_settlement(state)`（engine settle + gene_score 回查兜底 + `_get_tracker().add_record`）→ 摘要 dict | R2 | — | recorder 单测（tmp winrate db 注入） | ✅ |
| T3 | `routers/workflow.py` transition 接线：settled 成功且价齐且 settled_at 空 → record_settlement + mark_settled；响应 data 带 settlement（价缺 recorded:false+reason） | R3 | T1,T2 | 端点结算测试 | ✅ |
| T4 | 单股端点：settled_at 非空附 settlement 摘要（settlement_summary 重算） | R5 | T2 | 端点摘要测试 | ✅ |
| T5 | 前端 `WorkflowStateCard` settlement 收益摘要展示（pctColor 既有约定）+ vitest | R6 | T4 | 前端测试过 | ✅ |
| T6 | 全量验证：`pytest -m "not live"` + tsc + vitest 全过 | A7 | T1-T5 | 全绿 | ✅ |
| T7 | 冒烟 + 归档：:8901 用 603221 settled 行验证结算 → **清理冒烟 winrate 记录**；tasks ✅ + spec 状态→已实现 + README 索引 | A8 | T6 | 冒烟过 + 用户库无残留 | ✅ |

## 依赖图

```
T1(repo settled_at) ─┐
                     ├─ T3(transition 接线) ─ T4(单股摘要) ─ T5(前端展示) ─ T6(全量) ─ T7(冒烟+归档)
T2(recorder) ────────┘
```

## 合规检查点

- T2：gene_score 回查真实 DB，缺失兜底 0.0（不臆造）；sti_label/sector 空串如实
- T3/T7：测试与冒烟均不得污染用户真实 winrate.db（67 条）——注入 tmp db + 冒烟后清理
- 全程零新增外部数据调用
