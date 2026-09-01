# S140 任务拆分 (tasks.md)

> 状态：草案  日期：2026-09-02
> 关联：[./spec.md](./spec.md) / [./plan.md](./plan.md)
> 约定：每 task 独立绿门（`tsc --noEmit` + 相关 vitest/e2e），逐步确认。文件路径相对 `frontend/`。

## 前置（跟踪，不属本 spec）

- [ ] **T0** IntradayMonitor date-prop bug 单独修：`src/pages/workflow/IntradayMonitor.tsx:108` 传 `date={triplet.today}`（`:74` 已有 triplet）+ 加「rail 收非空 date + 计数>0」测。活 bug（7 态全零），盯盘复制前必修。

## Phase 1：地基 + 最小切

- [x] **T1.1** 建 `src/components/pipeline/primitives.tsx`（`export const NODE` / `export function ArrowDown` / `export function FunnelShrinkBar`）。✓ 已建（2026-09-02）。
- [ ] **T1.2** R4 · FBP 迁移：`src/pages/workflow/components/FirstBoardPipeline.tsx` 删本地 `NODE`/`ArrowDown`/`FunnelShrinkBar`，加 `import { NODE, ArrowDown, FunnelShrinkBar } from "@/components/pipeline/primitives"`；**保** `NODE_DASHED`/`GREEN`/`AMBER`/`RED` 本地。
  - 验：`npx tsc --noEmit` 0 error；FBP 相关 vitest 绿。
  - 门 A1：FBP 内不再定义 `NODE`/`ArrowDown`/`FunnelShrinkBar`。
- [ ] **T1.3** R4 · SP 迁移：`src/components/pipeline/SelectionPipeline.tsx` 删本地 `NODE`(:45)/`ArrowDown`(:163)/`FunnelShrinkBar`(:256)，加 import。
  - 验：tsc 0 error；SP vitest 绿。
- [ ] **T1.4** R4 · NonLimitup 迁移：`src/components/pipeline/NonLimitupPlaceholder.tsx` 删本地 `ArrowDown`(:191)，加 `import { ArrowDown }`；**保** 本地 `NODE`(:201，异串命名碰撞，不引)。
  - 验：tsc 0 error；vitest 绿。
  - 门 A1：`grep -rn "function ArrowDown\|function FunnelShrinkBar" frontend/src` 仅命中 `primitives.tsx`；`const NODE ` 命中 `primitives.tsx` + `NonLimitupPlaceholder.tsx`（后者保留）。
- [ ] **T2** R2 三视图正名：`src/pages/Workflow.tsx` `TABS` label → `复盘`/`盯盘`/`选股`（键名 `review|today|forward` 不变）；`src/pages/__tests__/Workflow.test.tsx` 全站 `getTabButton("当日")`→`("盯盘")`、`("前瞻")`→`("选股")`（~10 处：178/179/188/203/211/212/223/232/242/384）。
  - 验：`npx vitest run` 全绿（含更新后 Workflow.test）；门 A3。
- [ ] **T3** R3 双入口重定向：`src/router.tsx` `/workflow/pre-market` → `lazyEl` 改 bare `<Navigate to="/workflow?view=today" replace />`；`/workflow/post-market` → `?view=review`。**不透传 `?date=`**。
  - 验：e2e `/workflow/pre-market` → URL 含 `?view=today` 且 `?date=` 不存在；门 A4（`urlDate=undefined` → triplet 自动日期 = 旧路由行为）。

## Phase 2：语境视图 + rail

- [ ] **T4** R5 SelectionStageView 提取：新建 `src/pages/workflow/SelectionStageView.tsx` 承接 `ForwardTabSection`（`Workflow.tsx:348`）+ 其专用 helpers（`PreSharedRegion`/`PostSharedRegion`/`RiskAsymmetryCard`/`CrossValidationSummary`）；`Workflow.tsx` forward 分支改渲染 `<SelectionStageView F={triplet.F} forward={triplet.forward} urlDate={urlDate} today={triplet.today} />`（补传 `today`）。
  - 验：tsc + vitest；门 A5（与原 ForwardTabSection 视觉/数据 1:1）+ A2（`Workflow.tsx` <350 行）。
- [ ] **T5** R6 CandidateStateRail：新建 `src/components/workflow/CandidateStateRail.tsx`（包 `StateMachineDashboard` 逻辑，接 `date` prop）；`SelectionStageView` 挂 `<CandidateStateRail date={today} />`。
  - 验：vitest 断言 rail 收非空 date + 计数>0（防 IntradayMonitor 全零覆辙）；门 A6。
- [ ] **T6** R8 注记 + §8 打点：跑 `npm run dev`，开 `/workflow`，DevTools Network 数请求 + 抓各请求耗时；结果记入 spec §8。若存在爆炸 → 标单开 spec。
- [ ] **T7** 终验门：`cd frontend && npx vitest run` 全绿 + `npx tsc --noEmit` 0 error + e2e（三 tab + 重定向链路）全绿；逐条核对 A1-A9；更新 spec 顶部状态为「已实现(YYYY-MM-DD)」。

## 不在本 spec（已拆出 / 跟踪）

- R7 FirstBoardPipeline 节点拆分 → **S141**（待脊柱试点 + step-state 契约定后）。
- IntradayMonitor 挂 rail → 盯盘复制 spec。
