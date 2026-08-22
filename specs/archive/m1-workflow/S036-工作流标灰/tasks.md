# 任务拆分 · S036 工作流标灰

> 级别：medium，直接 develop 提交。

## 阶段 A · 后端端点标灰（R1-R6）

| ID | 任务 | 依赖 | 改动文件 | 验收方式 | AC |
|---|---|---|---|---|---|
| A1 | `/workflow/realtime` + `/intraday` 改 early return `{"not_implemented": true, ...}`，不调 `run_intraday()` | — | `backend/routers/workflow.py` | curl -> not_implemented: true | A1 |
| A2 | `/workflow/post-market` 同上，不调 `run_post_market()` | A1 | `backend/routers/workflow.py` | curl -> not_implemented | A2 |
| A3 | `/workflow/signals` + `/workflow/alerts` 同上 | A1 | `backend/routers/workflow.py` | curl -> not_implemented | A3 |
| A4 | `POST /workflow/settle` 同上，message 含"请用状态机流转 settled（S034）" | A1 | `backend/routers/workflow.py` | curl POST -> not_implemented | A3 |
| A5 | `/workflow/refresh` 确认不受影响 | — | — | curl -> 正常返回 | A4 |
| A6 | `realtime_workflow.py` / `post_market_workflow.py` 桩方法加 `# stub: 未实现，见 S036` 注释 | — | 两文件 | grep 注释存在 | — |
| A7 | 单测：5 个端点断言 not_implemented + mock 确认桩零调用 | A1-A4 | `backend/tests/test_s036_not_implemented.py` | pytest 过 | A1-A3,A8 |

## 阶段 B · 前端 WorkflowStage 组件（R12）

| ID | 任务 | 依赖 | 改动文件 | 验收方式 | AC |
|---|---|---|---|---|---|
| B1 | `WorkflowStage.tsx` 加 `notImplemented` prop，true 渲染灰底横幅替代 children | — | `frontend/.../WorkflowStage.tsx` | tsc 过 | A7 |
| B2 | vitest：WorkflowStage notImplemented=true 渲染横幅 | B1 | `frontend/.../__tests__/` | vitest 过 | A7 |

## 阶段 C · 前端三页标灰（R8-R11）

| ID | 任务 | 依赖 | 改动文件 | 验收方式 | AC |
|---|---|---|---|---|---|
| C1 | `IntradayMonitor.tsx` 不调 `useIntradayData()`，渲染 `<WorkflowStage notImplemented>` | B1 | `frontend/.../IntradayMonitor.tsx` | tsc 过；网络面板无请求 | A5,A6 |
| C2 | `PostMarketReview.tsx` 不调 `usePostMarketReview()`，同上 | B1 | `frontend/.../PostMarketReview.tsx` | tsc 过 | A5,A6 |
| C3 | `BombAlertPanel.tsx` 不调 `useBombAlerts()`，同上 | B1 | `frontend/.../BombAlertPanel.tsx` | tsc 过 | A5,A6 |
| C4 | vitest：三页渲染未实现横幅 | C1-C3 | `frontend/.../__tests__/` | vitest 过 | A7 |
| C5 | 确认 `router.tsx` 路由 + `navigation.ts` nav item 保留不删 | — | — | grep 确认路由存在 | A5 |

## 阶段 D · 集成验收

| ID | 任务 | 依赖 | 改动文件 | 验收方式 | AC |
|---|---|---|---|---|---|
| D1 | `pytest -m "not live"` 全过 | A7 | — | 全绿 | A8 |
| D2 | `npx tsc --noEmit` + `npx vitest run` 全过 | C4 | — | 全绿 | A6,A7 |
| D3 | diff 审查无新功能逻辑（只标灰不补功能） | — | — | git diff 确认 | A9 |
