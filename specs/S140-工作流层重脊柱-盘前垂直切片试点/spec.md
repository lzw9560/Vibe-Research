# Spec: S140 — 工作流层重脊柱·选股语境垂直切片试点

> 状态：已实现(2026-09-02)（T1-T7 落地；tsc PASS + 全量 vitest 437/437 绿；e2e A9-scoped s031/s093/s094/s099 全绿；s063 sentiment/weather 2 项 pre-existing 出 A9 范围）
> 作者：lzw9560  日期：2026-09-01  修订：2026-09-02
> 关联：S013（路由懒加载）/ S024（拓扑）/ S063（盘中监控）/ S064（盯盘教练）/ S075（首板流）/ S093（三视图迁出）/ S099（拓扑图替代垂直节点列表）/ S139（前序）/ **S141（FirstBoardPipeline 节点化拆分，本 spec 拆出，待脊柱试点 + step-state 契约定后实施）**
>
> 本文件命名为 `spec.md`，放在 `specs/S140-工作流层重脊柱-盘前垂直切片试点/` 子目录下。
> **v2 修订要点**：R7（FirstBoardPipeline 节点拆分）拆出独立 spec S141，本 spec 收为纯脊柱试点（R1-R6 + R8 注记）；§2 四条「F」声称按审计勘误；R8 降级为注记（大部分 query 已语境化）；R6 收窄到 SelectionStageView-only + A6 加强防假过门；R3 重定向不透传 ?date=。

## 1. 问题 / 目标

前端「太重 / 组件过于复杂 / 无法逐节点确认 pipeline」的根因不在节点层，而在**工作流层没有单一脊柱**：三根轴（时段 stage / 标的 7 态 / 功能节点）用重叠路由粘在一起，同一组件双入口（`PreMarketBriefing` 既是「当日」tab 又是 `/workflow/pre-market` 路由；`PostMarketReview` 同病），6 个 stage 有损压成 3 个时间命名 tab（复盘/当日/前瞻），而 CLAUDE.md §3 称作「打板工作流」本体的 7 态状态机在导航层失踪（埋在 `IntradayMonitor` 里一个子组件）。

（另：用户感知「请求多」，**未证实存在爆炸**——见 §2 实测、§8 打点。）

本 spec 做**选股语境垂直切片试点**：定 Axis 1（时段 stage）为唯一顶层脊柱，三视图正名为决策语境（复盘/盯盘/选股），杀双入口重定向，抽共享图元，把内联的 `ForwardTabSection` 组件化为 `SelectionStageView`，把 7 态状态机挖成常驻 rail（挂 SelectionStageView）。**R7（`FirstBoardPipeline` 1149 行节点拆分）经 grill Round 2 拆出独立 spec S141**，排在脊柱试点 + deferred 的 step-state 契约定后实施——避免把高 render-break 风险的节点拆分与低风险脊柱模式证明捆在一起致失败不可归因。跑通 + 测试绿后，同一模式复制到盘中/盘后（后续 spec）。

## 2. 背景

工作流层现状（**F=事实，均经审计 grep/读码验证，挂 file:line**）：

- **F** `Workflow.tsx`（536 行）3 tab：`review`(复盘) / `today`(当日) / `forward`(前瞻)，脊柱是 stage，经 `stageToDefaultTab`（`Workflow.tsx:47-55`）把 6 stage 压成 3 tab。
- **F** `Workflow.tsx` 顶层 query 实测：仅 `useDateTriplet`（`:136`）+ `usePreMarketDates`（`:178`）真·顶层；`usePreMarketBriefing`（`:350`）/ `useCrossValidationGroups`（`:352`）/ advisory `useQuery`（`:354`）均在 `ForwardTabSection`（`:348` 定义，仅 forward tab 活跃时渲染）内——**已语境化**。故无「请求爆炸」：顶层 2 + forward 语境 3 = 正常量级。
- **F** `ForwardTabSection` 内联 `Workflow.tsx:348`；`PreMarketBriefing.tsx:23` 注释「选股决策内容迁出至前瞻 Tab (ForwardTabSection)」；`PreMarketBriefing` 自注「当日 Tab 改盯盘执行台」。→ 三 tab 功能上已是决策语境：forward=选股、today=盯盘、review=复盘，仅命名按「哪天」误导。
- **F** 双入口：`/workflow/pre-market` 路由 → `PreMarketBriefing`（= today/盯盘 tab）；`/workflow/post-market` → `PostMarketReview`（= review/复盘 tab）。同一组件双入口，URL/返回键行为不一致。
- **F** `FirstBoardPipeline.tsx`（1149 行）= **纯展示组件，0 请求**（Props 接 `data`/`isLoading`，`FirstBoardPipeline.tsx:683-686`；文件内对 `useFirstBoardCandidates` 的唯一提及在 `:9` 注释）。实际请求在 `FirstBoardPage.tsx:26`（`useFirstBoardCandidates`）+ `:28`（`useFirstBoardDates`）。
- **F** 图元去重实测：`NODE` 真 2 份重复（`FirstBoardPipeline.tsx:23` + `SelectionPipeline.tsx:45`；`NonLimitupPlaceholder.tsx:201` 的 `NODE` 是不同 class 的命名碰撞，非真重复）；`ArrowDown` 真 3 份（`:30`/`:163`/`:191`）；`FunnelShrinkBar` 2 份（`:41`/`:256`，`NonLimitupPlaceholder` 无）；`NODE_DASHED`/`GREEN`/`AMBER`/`RED` 仅 `FirstBoardPipeline` 内（单源）。
- **F** `components/pipeline/` 已存在（`SelectionPipeline`/`PipelineTopology`/`NonLimitupPlaceholder`/`StrategySubPipelineView`）——共享图元家已就位。
- **F** `StateMachineDashboard`（7 态看板）现仅 `IntradayMonitor.tsx:108` 挂载，且**未传 date**——`useWorkflowStates`（`lib/query/workflow.ts:27`）`enabled: !!date`，date=undefined → query 不发 → **7 态全显 0（活 bug，Round 3 共识单独修，不属本 spec）**。
- **F** `WorkflowStage`（工作流页共享壳）实测被 **6 页**用：`IntradayMonitor`/`PostMarketReview`/`BombAlertPanel`/`PreMarketBriefing`/`IntradayCoach`/`FirstBoardPage`（`FirstBoardPage.tsx:14` import、`:74` 包 `<WorkflowStage title="首板流">`）。**`FirstBoardPage` 已对齐共享壳，无壳对齐工作**。

约束：本 spec 只做**选股（forward/盘前）语境**垂直切片 + 全局正名/重定向/图元地基；盘中/盘后视图组件化与复制留后续 spec；`FirstBoardPipeline` 节点拆分留 S141。三视图正名与双入口重定向虽全局，均最小改动（label 文本 + 2 条 bare Navigate 重定向），随地基一次做完。

## 3. 需求清单

- [ ] R1 定 Axis 1（时段 stage）为工作流层唯一顶层脊柱；`/workflow` 按 `dateTriplet.stage` 自动聚焦当前语境视图。
- [ ] R2 三视图正名为决策语境：复盘 / 盯盘 / 选股（`TabKey` 键名 `review|today|forward` 保留以最小化引用面，仅改可见 label + 同步更新 `Workflow.test.tsx` 的 `getTabButton("当日")→("盯盘")`、`("前瞻")→("选股")`）。
- [ ] R3 杀双入口：`/workflow/pre-market` → `/workflow?view=today`（盯盘）；`/workflow/post-market` → `/workflow?view=review`（复盘）。**bare `<Navigate>`，不透传 `?date=`**（旧路由本就忽略 `?date=`，透传反变行为——见 §5.2）。
- [ ] R4 抽共享图元 `components/pipeline/primitives.tsx`：提取**真重复**的 `NODE`/`ArrowDown`/`FunnelShrinkBar`；`SelectionPipeline` + `NonLimitupPlaceholder`（ArrowDown）+ `FirstBoardPipeline`（NODE/ArrowDown/FunnelShrinkBar，~3 行 import swap，**非节点拆分**）改为引用。`NODE_DASHED`/`GREEN`/`AMBER`/`RED` 仅 `FirstBoardPipeline` 单源，留在原处或随 S141 迁。
- [ ] R5 `ForwardTabSection`（内联 `Workflow.tsx:348`）提取为 `pages/workflow/SelectionStageView.tsx`；`Workflow.tsx` 降为薄编排器（读 triplet → 选语境视图 → 渲染视图）。
- [ ] R6 7 态状态机挖成常驻 rail `components/workflow/CandidateStateRail.tsx`（包 `StateMachineDashboard` 逻辑），**试点只挂 `SelectionStageView`**，date 从 `triplet.today` 接（**非空 date + 计数>0**，防假过门；状态机是当日生命周期，`forward` 未来日期后端无态会返空，与 IntradayMonitor 全零 bug 同类陷阱）。`IntradayMonitor` 挂 rail 推到「盯盘复制」spec。
- [ ] ~~R7 `FirstBoardPipeline` 节点化拆分~~ → **拆出 S141**，待本 spec + step-state 契约定后实施（grill Round 2 共识）。
- [ ] R8（**注记，非需求**）：query 归属语境为**结构正确性**（非 perf 修复）。实测大部分已语境化（`ForwardTabSection` 内），唯一真·顶层非-triplet query 是 `usePreMarketDates`（跨语境，须留顶层）。本 spec 不作 perf 治理；若 §8 打点证实爆炸，单开 spec。

## 4. 受影响文件

| 文件 | 改动 |
|---|---|
| `frontend/src/router.tsx` | R3：`/workflow/pre-market`、`/workflow/post-market` 改为 bare `<Navigate to="/workflow?view=...">`（不透传 `?date=`） |
| `frontend/src/pages/Workflow.tsx` | R2：`TABS` label → 复盘/盯盘/选股；R5：删内联 `ForwardTabSection`，改渲染 `SelectionStageView`；R8 注记：`triplet` 须留顶层（`useMarketClock` 依赖 `next_*_at`）；文件从 536 行降为薄编排器 <250 行 |
| `frontend/src/pages/workflow/SelectionStageView.tsx` | R5：新，承接 `ForwardTabSection` 内容 + 挂 `CandidateStateRail`（date 从 `triplet.today` 接；须加 `today` prop——现 `ForwardTabSection` 只收 `F`/`forward`/`urlDate`，`Workflow.tsx` 渲染处补传 `today={triplet.today}`） |
| `frontend/src/components/pipeline/primitives.tsx` | R4：新，`NODE`/`ArrowDown`/`FunnelShrinkBar` 单一来源 |
| `frontend/src/components/pipeline/SelectionPipeline.tsx` | R4：改引用 `primitives.tsx`，删本地 `NODE`/`ArrowDown`/`FunnelShrinkBar` |
| `frontend/src/components/pipeline/NonLimitupPlaceholder.tsx` | R4：`ArrowDown` 改引用 `primitives.tsx`（本地 `NODE` 是不同 class 的命名碰撞，保留不动） |
| `frontend/src/pages/workflow/components/FirstBoardPipeline.tsx` | R4：`NODE`/`ArrowDown`/`FunnelShrinkBar` 改引用 `primitives.tsx`（~3 行 import swap，**非节点拆分**；拆分归 S141） |
| `frontend/src/components/workflow/CandidateStateRail.tsx` | R6：新，常驻 rail，包 `StateMachineDashboard` 逻辑，接 `date` prop |
| `frontend/src/pages/__tests__/Workflow.test.tsx` | R2：`getTabButton("当日")`→`("盯盘")`、`("前瞻")`→`("选股")` 全站更新（~10 处） |
| 测试 | 新增 `SelectionStageView` / `CandidateStateRail`（含非空 date + 计数>0）vitest；`Workflow.test.tsx` / 现有相关测试须保持绿 |

## 5. 设计方案

### 5.1 脊柱与三轴归位

Axis 1（时段 stage）→ 顶层导航脊柱；Axis 2（标的 7 态）→ 跨时段常驻 rail（试点挂选股视图，复制期挂盯盘）；Axis 3（功能节点）→ 语境内子内容/深链（`/workflow/first-board` 等扁平路由本 spec 保留，留后续 spec 评估）。6 stage → 3 语境映射**不是 bug 是正确粒度**（盘前+盘后→选股，dateTriplet 给对日期；集合竞价+盘中→盯盘；数据采集+非交易→复盘），病只在按「哪天」命名，正名即可，不增第 4 视图（KISS）。

### 5.2 双入口重定向（不透传 ?date=）

`/workflow/pre-market` 现渲染 `PreMarketBriefing`（= today/盯盘），故 bare `<Navigate to="/workflow?view=today">`；`/workflow/post-market` → `?view=review`。**不透传 `?date=`**：审计证实 `PreMarketBriefing.tsx:47`/`PostMarketReview.tsx:58` 走独立路由时调 `useDateTriplet()` 无 urlDate，**`?date=` 在旧路由本就是 no-op**；而 `Workflow.tsx:132` 会读 `?date=` 并切手动日期 + 暂停定时器——透传 `?date=` 会**改变行为**，违背 §5.2「保现行为」。bare `<Navigate>` 丢掉 `?date=` → Workflow `urlDate=undefined` → triplet 自动日期 = 与旧路由一致，**真·保现行为**。重定向保前向兼容（收藏/外链/返回键）。

### 5.3 rail 提取（收窄到 SelectionStageView-only）

`CandidateStateRail` 包 `StateMachineDashboard` 逻辑，接 `date` prop。**试点只挂 `SelectionStageView`**，date 从 `triplet.today` 接（`useWorkflowStates` 按日分区 `["workflow","state",date]`；`forward` 是未来日期后端无态返空——与 IntradayMonitor 全零 bug 同类陷阱；`SelectionStageView` 须从 `Workflow` 收 `today` prop）。rail 数据真、计数>0。`IntradayMonitor` 挂 rail 推到「盯盘复制」spec（届时 `IntradayMonitor` 的 date-prop 全零 bug 已由前置单独修修好，rail 直接接上）。不在试点里碰 `IntradayMonitor`，保试点「纯模式证明」、不拖陈年 bug 修。

### 5.4 取舍

- **R7 拆出 S141**（grill Round 2）：`FirstBoardPipeline` 1149 行节点拆分是节点层卫生，**不证脊柱模式**（stage→语境视图→rail），且是唯一高 render-break 风险项（§9）；捆进试点会翻倍文件数（9→21）、失败不可归因。拆出后脊柱试点 ~9 文件、低风险、快速证明。S141 排在脊柱试点 + step-state 契约定后，节点文件边界对齐 `{status,input,output,rawShadow}` 避返工。唯一耦合（R4 在 `FirstBoardPipeline` 内换图元 import）~3 行，**不依赖**节点拆分，留本 spec。
- **step-state 契约延后**：逐节点 `{status,input,output,rawShadow}` 是 grill 第 2 层交互模型，依赖各节点数据边界先理清；本 spec 先做脊柱 + 图元 + rail，step-state + R7 留 S141 起的后续。
- **R8 非 perf 修复**：定调为结构正确性（query 归语境）。实测大部分已语境化；是否真有爆炸由 §8 打点定，若有单开 spec。
- **不并扁平路由**：`/workflow/first-board` 等暂留，不并入选股语境——并路由是更大 UX 变更，超试点「立范式」目标，留后续 spec（YAGNI）。
- **文件数增多 ≠ 变复杂**：536 行 → 薄编排器 <250 + 小视图文件，净可维护性上升。

### 5.5 实施分 phase（逐步确认）

- **Phase 1（地基 + 最小切）**：R4 抽 `primitives.tsx` + 三文件去重；R2 三视图正名（+ `Workflow.test.tsx` label 同步）；R3 双入口 bare Navigate 重定向。最低风险，先绿。
- **Phase 2（语境视图 + rail）**：R5 提 `SelectionStageView`；R6 提 `CandidateStateRail` 挂 `SelectionStageView`（非空 date + 计数>0）。
- ~~Phase 3（节点拆分）~~ → S141。

每 phase 独立 vitest + e2e 绿门，phase 间可单独回滚。

## 6. 验收标准

- [ ] A1 `grep -rn "const NODE \|function ArrowDown\|function FunnelShrinkBar" frontend/src` 仅命中 `components/pipeline/primitives.tsx`（真重复图元单一来源；`NODE_DASHED`/`GREEN`/`AMBER`/`RED` 单源于 `FirstBoardPipeline`，不在本 grep 范围）
- [ ] A2 `Workflow.tsx` 显著瘦身（536→<350 行；提取 `ForwardTabSection` 及其专用 helper 子组件迁至 `SelectionStageView.tsx`）
- [ ] A3 三 tab 可见 label 为 复盘/盯盘/选股；`stageToDefaultTab` 行为不变
- [ ] A4 `/workflow/pre-market` → bare Navigate 到 `/workflow?view=today`（`?date=` 不透传）；`/workflow/post-market` → `?view=review`；行为保现（`urlDate=undefined` → triplet 自动日期 = 旧路由）
- [ ] A5 `SelectionStageView` 渲染内容 = 原 `ForwardTabSection`（视觉/数据 1:1）
- [ ] A6 `CandidateStateRail` 在 `SelectionStageView` 可见 + **收到非空 date（F/forward）+ 计数>0**（防假过门）
- [ ] A7 `FirstBoardPage` 请求数不增（基线 2：`useFirstBoardCandidates`+`useFirstBoardDates`）；`FirstBoardPipeline` 本身 0 请求（纯展示），基线 0 不增
- [ ] A8 涉及数据的显示语义 1:1 不变（仅结构重构；人工核对 `SelectionStageView` 与原 `ForwardTabSection` 数据呈现一致）
- [ ] A9 `cd frontend && npx vitest run` 全绿（含更新后的 `Workflow.test.tsx`）；`npx tsc --noEmit` 0 error；e2e（`/workflow` 三 tab + 重定向链路）全绿

## 7. 合规与工程底线自查（逐条确认）

- [x] 研判/推荐/买卖时机：本 spec 为前端结构重构，**无新增方向性输出**；`CandidateStateRail` 呈现标的 7 态属客观状态记录（已有，非新增），不触 CLAUDE.md §1.1 风险提醒线。
- [x] 判断可复现：无新研究性判断、无新数据计算；A8 要求显示语义 1:1 不变，不引入臆造/心算风险。
- [x] 涨停四池/连板股榜：本 spec 不动 `FirstBoardPipeline` 的 zt_pool 呈现（R4 只换图元 import，R7 拆分在 S141），不触分层约束。
- [x] 用户私有数据：纯前端重构，不涉持仓/研报/key 落盘或上传。
- [x] 东财 `em_get`：无新增东财端点（前端不直连东财）。

> 弱合规下仅核查工程底线（不臆造 / 私有数据隔离 / 防封），本 spec 不触任何工程底线。

## 8. 测试计划

- 离线快测：`cd frontend && npx vitest run`；重点 `Workflow.test.tsx`（label 已更新）/ `SelectionStageView` / `CandidateStateRail`（含非空 date + 计数>0 断言）。
- 类型：`cd frontend && npx tsc --noEmit` 0 error。
- e2e：`/workflow` 路由 + 三 tab 切换 + 重定向链路（`/workflow/pre-market` → `?view=today`、`/workflow/post-market` → `?view=review`）。
  - **实测（2026-09-02）**：s031（重定向→盯盘执行台）/ s093（三视图，relabel 后）/ s094 / s099（forward=SelectionStageView，T4 提取 + T5 rail 后）**全绿**。s063 有 2 项 fail（`/sentiment/weather→/workflow/intraday` 重定向 + WeatherDecisionBar 天气文本）为 **pre-existing、出 A9 范围**——S140 未动 `/sentiment/weather` 与 `/workflow/intraday` 路由；WeatherDecisionBar line40 `toBeVisible` 通过、line42 文本不匹配属后端天气数据问题。留作 sentiment/weather spec 单独修，不属 S140。
- **打点验证（grill Round 1 共识）**：开 `/workflow` 真实会话，DevTools Network 数请求 + 抓各请求耗时；判定是否存在「爆炸」（某页/某交互）。若存在 → 单开 spec 治理，不塞 S140；若不存在 → 坐实 R8 注记（结构去重，非 perf 修复）。
  - **代码级 query 计数结论（2026-09-02，T1-T5 后）**：`FirstBoardPipeline`=0 请求（纯展示，data 全 props）；`Workflow.tsx` 顶层 2（`useDateTriplet` + `usePreMarketDates`）；`SelectionStageView`（选股语境）4（`usePreMarketBriefing` + `useCrossValidationGroups` + advisory + `useWorkflowStates`[rail，T5 新增]）。**无爆炸**——R8 注记坐实，真爆炸单开 spec 不需要。DevTools 真实会话确认留作用户手动复核。
- 手动验收：浏览器核对 stage 自动聚焦语境、三 tab label、rail 常驻且计数>0、`SelectionStageView` 与原 `ForwardTabSection` 视觉一致。
- 后端无改动，无需 `pytest`。

## 9. 风险与回滚

- **重定向**：bare `<Navigate>` 不透传 `?date=`（保现行为，§5.2 已证）。回滚：还原 router.tsx 两行。注：`pre-market` 路由名与 stage 名 `pre_market` 同词但历史上指向盯盘语境，是既有 wart，重定向只保行为、不修此命名。
- **R2 relabel 破文本匹配测试**：`Workflow.test.tsx` 硬编码 `getTabButton("当日")`/`("前瞻")`（~10 处），R2 须同步更新为 `("盯盘")`/`("选股")`，否则 A9 红。已列入 §4 + Phase 1。
- **`useMarketClock` 依赖 `triplet.next_*_at`**：`triplet` 须保留在顶层（stage 聚焦 + 定时器依赖），仅语境级 query 归语境视图。实现时核对 `useMarketClock` 依赖不破。回滚：还原 query 挂载位置。
- **R4 图元 import swap**：`FirstBoardPipeline`/`SelectionPipeline`/`NonLimitupPlaceholder` 改引用 `primitives.tsx`，核对 `NODE` class 与原一致（`NonLimitupPlaceholder` 的 `NODE` 是不同 class 命名碰撞，**保留不动**，仅 `ArrowDown` 引用）。回滚：还原本地定义。
- **IntradayMonitor date-prop 全零 bug**（活 bug，**前置单独修，不属本 spec**）：须在「盯盘复制」spec 挂 rail 前修好（`IntradayMonitor.tsx:108` 传 `date={triplet.today}` + 测）。本 spec 期间该 bug 仍在（pre-existing），不引入也不修。
- **R7 拆出 S141**：`FirstBoardPipeline` 节点拆分不在本 spec；S141 依赖 step-state 契约定稿，避免节点边界返工。R4 的 `FirstBoardPipeline` 图元 swap ~3 行不依赖拆分。
- **并发编辑**（见 memory）：提交时显式 `git add` 具体文件，禁 `git add -A`。
