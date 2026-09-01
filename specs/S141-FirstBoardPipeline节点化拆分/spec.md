# Spec: S141 — FirstBoardPipeline 节点化拆分

> 状态：草案（待 S140 脊柱试点落地 + step-state 契约定稿后实施）
> 作者：lzw9560  日期：2026-09-02
> 关联：S140（脊柱试点，本 spec 拆出其原 R7）/ S075（首板流）
>
> 本文件命名为 `spec.md`，放在 `specs/S141-FirstBoardPipeline节点化拆分/` 子目录下。

## 1. 问题 / 目标

S140 grill Round 2 共识：`FirstBoardPipeline.tsx`（1149 行）节点化拆分与脊柱模式证明**正交**（它证节点层分解，不证 stage→语境视图→rail），且是唯一高 render-break 风险项；捆进脊柱试点会翻倍文件数（9→21）+ 失败不可归因。故从 S140 拆出本 spec，独立实施。

目标：把 1149 行拆为 `index.tsx` 编排器(<150) + 节点文件(<200) + `tables`/`widgets`/`format`，图元引 S140 的 `primitives.tsx`；节点边界对齐 deferred 的 step-state 契约 `{status, input, output, rawShadow}` 避返工。

## 2. 背景

`FirstBoardPipeline.tsx` 现状（S140 §2 已验，F=事实）：
- 纯展示组件，**0 请求**（data 全 props，Props `:683-686`）。
- 7-8 节点 + `CandidateScoreTable`(~149) + 行片段 + 策略徽标 + 格式化器全挤一文件。
- 节点：`FilterPipelineNode`(~285) / `MarketEnvLamps` / `WatchbookManual` / `ConfirmNode` / `PositionNode` / `SellNode` / `SettlementNode` / `FeishuStatusBar`。
- R4（S140 已落地）已把 `NODE`/`ArrowDown`/`FunnelShrinkBar` 换成引 `primitives.tsx`（~3 行 import swap），本 spec 不重做。

## 3. 需求清单（待 step-state 契约定稿后细化）

- [ ] R1 拆 `FirstBoardPipeline.tsx` → `pages/workflow/components/FirstBoardPipeline/` 子树（`index` + `nodes/` + `tables/` + `widgets/` + `format`）
- [ ] R2 节点文件 <200 行、`index` <150 行
- [ ] R3 节点边界对齐 step-state 契约 `{status, input, output, rawShadow}`（grill 第 2 层交互模型，待 step-state spec 定稿）
- [ ] R4 原文件保 re-export 兼容外部 import（最小爆炸半径）
- [ ] R5 视觉/数据 1:1（纯结构重构，无语义变化）

## 4-9. （待实施时按 S140 模式补：受影响文件 / 设计方案 / 验收标准 / 合规自查 / 测试计划 / 风险与回滚）

## 前置依赖

- S140 脊柱试点已落地（2026-09-02 完成）✓
- step-state 契约 spec 定稿（未立）——节点文件边界须对齐此契约，避免先拆完再加契约返工。**这是本 spec 实施的硬前置。**
