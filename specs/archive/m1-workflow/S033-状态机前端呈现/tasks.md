# Tasks: S033 — 状态机前端呈现

> 对应 `spec.md` + `plan.md`。A/B 两节，后端 3 改 + 前端 5 件。

## 任务清单

| ID | 任务 | 需求 | 依赖 | 验收 | 状态 |
|---|---|---|---|---|---|
| **A 节：后端** | | | | | |
| T1 | `workflow_state_repo._ensure_tables()` 末尾加 `_ensure_columns(conn)`——ALTER TABLE 幂等加 `entry_price REAL`/`exit_price REAL`/`strategy TEXT`；`_row_to_state()` 补三字段 | R1 | — | 三列存在；旧 99 行 NULL 不报错 | ✅ |
| T2 | `routers/workflow.py` `_TransitionRequest` 加 `entry_price`/`exit_price`/`strategy` 三可选字段；`workflow_state_repo.transition()` 扩参 + COALESCE UPDATE | R2 | T1 | 带 price 的 transition 写入；不带时保持已有值 | ✅ |
| T3 | `workflow_state_repo.get_state_with_targets(code, date)` + `routers/workflow.py` 加 `GET /api/workflow/state/{code}?date=`；路由顺序在 `/{code}/history` 之前 | R3 | T1 | 单股端点返 state+allowed_targets；无记录 404 | ✅ |
| T4 | 后端单测：`test_workflow_state_columns` / `test_transition_with_price` / `test_single_state_endpoint` | R1-R3 | T1-T3 | `pytest -m "not live"` 全过 | ✅ |
| **B 节：前端** | | | | | |
| T5 | `api/types.ts` 加 `WorkflowState`/`TransitionRequest`/`WorkflowStateHistoryItem` 类型；`api/workflow.ts` 加 4 函数（getWorkflowStates/getWorkflowState/transitionWorkflowState/getWorkflowStateHistory） | R4 | — | 类型 + 函数 tsc 过 | ✅ |
| T6 | `lib/query/workflow.ts` 加 4 hooks（useWorkflowStates/useWorkflowState/useTransitionWorkflowState/useWorkflowStateHistory） | R4 | T5 | hooks 编译 + invalidate 正确 | ✅ |
| T7 | `FunnelLayerCard.tsx` passed 列表行加状态色块徽标——用 `useWorkflowStates(date)` 全量取再前端 Map filter（不在 map callback 调 hook） | R5 | T6 | passed 每行有状态色块；颜色对应 DB status | ✅ |
| T8 | 新建 `components/workflow/WorkflowStateCard.tsx`——当前态徽标 + 流转历史 timeline + 流转按钮（只渲染 allowed_targets） | R6 | T6 | 状态卡渲染徽标+timeline+按钮 | ✅ |
| T9 | `CandidateDetail.tsx` `CandidateDetailPanel` 底部嵌入 `<WorkflowStateCard code date />` | R6 | T8 | 抽屉底部有状态卡 | ✅ |
| T10 | `TransitionButton` 组件：watching/monitoring 直接 POST；holding/settled 先弹表单 | R7 | T8 | 直接 POST 流转成功；holding/settled 弹表单 | ✅ |
| T11 | 新建 `components/workflow/TransitionForm.tsx`——entry_price/exit_price input + strategy 下拉选 8 大战法 + reason input；字段可选填 | R7 | T10 | 弹窗表单提交成功；不填也能 POST | ✅ |
| T12 | `FunnelLayerCard.tsx` filtered_out 列表行加红淡徽标 (`bg-red-300`) | R8 | T7 | filtered_out 每行有红淡徽标 | ✅ |
| T13 | 前端单测：`WorkflowStateCard`（徽标+timeline+按钮）/ `TransitionForm`（表单提交+可选字段）/ `FunnelLayerCard` 徽标 | R5-R8 | T7-T12 | vitest 全过 | ✅ |
| T14 | tsc + vitest + `pytest -m "not live"` 全过 | A10/B9 | T4,T13 | 全绿 | ✅ |

## 依赖图

```
T1(扩表) ─ T2(TransitionRequest) ─ T3(单股端点) ─ T4(后端单测)
T5(API 类型+函数) ─ T6(hooks) ─ T7(列表徽标) ─ T12(filtered 徽标)
                         └─ T8(状态卡) ─ T9(抽屉嵌入)
                                   └─ T10(流转按钮) ─ T11(弹窗表单)
T4,T13 ─ T14(全量验证)
```

## 合规检查点

- 状态机流转是客观状态记录，不含买卖指令
- entry_price/exit_price/strategy 是用户自填操作记录，非系统推荐
- 状态徽标基于 workflow_state DB 实际数据，禁臆造
- 用户私有数据（买入价/卖出价）走 market_data.db（项目内），不进 git
- 不新增 em_get 调用

## 为 S034 铺路

本 spec 采集的 entry_price/exit_price/strategy 是 S034 SettlementEngine 接线的输入：
- holding 行的 entry_price + strategy → settle() 的 SettlementInput
- settled 行的 exit_price → settle() 的 exit_price
- S034 接线时 `_settle_recommendations` 读 holding 行调 settle() 写 winrate.db
