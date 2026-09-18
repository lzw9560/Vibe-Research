# S140 实施计划 (plan.md)

> 状态：草案  日期：2026-09-02
> 关联：[./spec.md](./spec.md) / [./tasks.md](./tasks.md)
> 范围：脊柱试点（R1-R6 + R8 注记）。R7（FirstBoardPipeline 节点拆分）已拆出 S141，待脊柱试点 + step-state 契约定后。

## 执行策略

分 2 phase，**逐步确认**——每 task 独立绿门（tsc + 相关 vitest/e2e）、独立 commit、可独立 git revert。Phase 1 地基（用户不可见 / 最低风险，先绿）；Phase 2 语境视图 + rail（用户可见）。R8 不作 perf 修复，只注记 + §8 打点。

## Phase 1：地基 + 最小切

- **T1 R4 图元去重**（用户不可见，最低风险，先做）：建 `primitives.tsx` → 逐文件迁移 FBP→SP→NonLimitup（每步 tsc）。证明抽取模式跑通。
- **T2 R2 三视图正名**（用户可见 label）：`Workflow.tsx` TABS → 复盘/盯盘/选股 + 同步 `Workflow.test.tsx` 的 `getTabButton` 文本 ~10 处。
- **T3 R3 双入口重定向**：`router.tsx` bare `<Navigate>`（不透传 `?date=`）。

## Phase 2：语境视图 + rail

- **T4 R5 SelectionStageView 提取**：`ForwardTabSection` + 专用 helpers 迁出 → `SelectionStageView.tsx`；`Workflow.tsx` 补传 `today={triplet.today}`。
- **T5 R6 CandidateStateRail**：包 `StateMachineDashboard` 接 `date`，挂 `SelectionStageView`（`date=triplet.today`，非空 + 计数>0 防 IntradayMonitor 全零覆辙）。
- **T6 R8 注记 + §8 打点**：跑 `/workflow` 真实会话，DevTools Network 数请求 + 耗时，记入 spec；若爆炸标单开 spec。
- **T7 终验门**：全量 vitest + tsc + e2e 绿；逐条对 A1-A9。

## 前置 / 跨 spec 跟踪

- **T0（前置，不属本 spec）**：`IntradayMonitor.tsx:108` 传 `date={triplet.today}` + 测——活 bug（7 态全零），盯盘复制前必修。本 spec 期间该 bug 仍在（pre-existing），不引入也不修。

## 不在本 spec（已拆出）

- R7 FirstBoardPipeline 节点拆分 → **S141**（待脊柱试点 + step-state 契约定后，节点边界对齐 `{status,input,output,rawShadow}` 避返工）。
- IntradayMonitor 挂 rail → 盯盘复制 spec。

## 取舍 / 回滚

- 每 task 一个 commit，显式 `git add` 具体文件（禁 `git add -A`——并发编辑者可能打包他人改动）。
- 不 commit 到 main/master；develop 工作。
- 每 task 可独立 `git revert`，不阻塞前后 task。
- T1 先做、逐文件 tsc——若 FBP 迁移出问题，SP/NonLimitup 未动，影响隔离。
