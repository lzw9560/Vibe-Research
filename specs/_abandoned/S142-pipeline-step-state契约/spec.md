# Spec: S142 — pipeline 节点 step-state 契约

> 状态：草案（设计 spec，S141 实施的硬前置）
> 作者：lzw9560  日期：2026-09-02
> 关联：S140（脊柱试点，grill 第 2 层交互模型延后至此）/ S141（FirstBoardPipeline 节点拆分，依赖本契约定边界）
>
> 本文件命名为 `spec.md`，放在 `specs/S142-pipeline-step-state契约/` 子目录下。

## 1. 问题 / 目标

用户 goal #3「逐步确认 pipeline 节点步骤」无统一载体：pipeline 各节点（FirstBoardPipeline ①~⑦、SelectionPipeline ①~⑧）现只有零散 status 颜色（NODE_GREEN/AMBER/RED），无显式 `{status, input, output, rawShadow, durationMs}` 契约 → 无法逐节点确认状态/数据/耗时，调试靠 console。

本 spec 定义 **StepState 契约**：每个 pipeline 节点显式暴露一步的可观测状态，使「逐节点确认」成为一等公民（节点顶部 status 灯 + input→output 漏斗 + 展开 rawShadow + 可冻结）。

## 2. 背景

- grill 第 2 层交互模型（S140 §5.4 延后至此）：step-state 是「逐节点确认」的物理载体。
- S140 节点已有颜色语义（绿=通过/已运行、红=剔除、黄=待确认、灰=未运行、实线=已过滤、虚线=待运行），本契约把颜色升格为显式 status enum + 补 input/output/rawShadow/durationMs。
- `StateMachineDashboard` 的 7 态（pending→settled）是**标的生命周期**（Axis 2），与本契约的**节点步骤状态**（一步的执行态）是不同维度，不混淆。
- §44 honest stance：rawShadow 字段承载原始值诚实可见。

## 3. 需求清单

- [ ] R1 定义 `StepState` 类型：`{ status: "idle"|"loading"|"ok"|"error"|"skipped"; input?: number; output?: number; durationMs?: number; rawShadow?: unknown; honest?: boolean }`，放 `components/pipeline/StepState.ts`。
- [ ] R2 每个节点接收/派生 `stepState` prop（或内部计算），顶部渲染 status 灯 + `input→output` 漏斗（复用 `FunnelShrinkBar`）。
- [ ] R3 progressive disclosure：默认收起显摘要（灯 + 漏斗数字），展开显 rawShadow（原始值诚实可见）+ durationMs。
- [ ] R4 per-node debug：节点可「冻结」（冻结态不随上游刷新，方便停在某步反复看）。
- [ ] R5 与 §44 honest 对齐：rawShadow 诚实展示原始值（未 validated 标注「参考」）。

## 4. 受影响文件

| 文件 | 改动 |
|---|---|
| `frontend/src/components/pipeline/StepState.ts` | 新：类型 + 状态灯/漏斗 UI 子组件 |
| `frontend/src/components/pipeline/primitives.tsx` | 可能加 StepState 相关图元（status 灯） |
| 各 pipeline 节点（S141 落地时接入） | 接 `stepState` prop + 顶部渲染 |

## 5. 设计方案

- **status enum**：`idle`（未运行，虚线灰）/ `loading`（运行中，黄）/ `ok`（通过，绿）/ `error`（错，红）/ `skipped`（跳过/剔除，红虚线）。与现有 NODE_* 颜色 1:1 映射，不新造色。
- **input/output**：漏斗收敛数字（`FunnelShrinkBar` 复用），一眼看哪步在漏、漏多少。
- **rawShadow**：展开态显原始值（未加工的数据快照），§44 honest。
- **durationMs**：节点执行耗时（perf 可观测，非 perf 修复）。
- **freeze**：节点 local state `frozen`，true 时 useEffect 跳过上游 data 更新。
- **接入方式**：节点接 `stepState?: Partial<StepState>` prop；父编排器（如 FirstBoardPipeline index）从 data 派生各节点 stepState 切片传入。节点缺 stepState 时降级（只显 content，无灯）——向后兼容。

## 6. 验收标准

- [ ] A1 `StepState` 类型存在 + 导出，节点可接 `stepState` prop
- [ ] A2 节点顶部 status 灯 + input→output 漏斗可见（有 stepState 时）
- [ ] A3 节点可展开显 rawShadow + durationMs
- [ ] A4 节点可冻结（冻结态 data 不刷新）
- [ ] A5 缺 stepState 时节点降级正常渲染（向后兼容）
- [ ] A6 vitest（StepState UI + freeze 逻辑）绿

## 7. 合规与工程底线自查

- [x] 无新方向性输出：stepState 是客观状态/原始值展示，不触 §1.1。
- [x] 判断可复现：rawShadow 诚实展示原始值（不臆造），§44 honest。
- [x] 无私有数据/东财端点变更。

## 8. 测试计划

- vitest：StepState UI（各 status 灯渲染）+ freeze 逻辑（冻结态不刷新）+ progressive disclosure（展开 rawShadow）。
- 接入节点后（S141）：节点 stepState 切片单测。

## 9. 风险与回滚

- **过度设计风险**：stepState 字段别贪多（YAGNI），先 status/input/output/rawShadow/durationMs/freeze 五件，其余按需加。
- **向后兼容**：节点缺 stepState 须降级正常渲染（A5），否则破坏现有 pipeline。
- 回滚：StepState.ts 删除 + 节点回退 stepState prop。
