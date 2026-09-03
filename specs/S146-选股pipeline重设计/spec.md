# Spec: S146 — 选股 pipeline 重设计与统一流

> 状态：已实现(2026-09-03)（v1 `f80bd6c` + v2 `ec273e4`；tsc 0 + vitest 192/25 文件绿；e2e 结构断言绿）
> 作者：lzw9560  日期：2026-09-03（retroactive 归档——v1/v2 实现先于 spec，本文件事后补全 SDD）
> 关联：S140（工作流层重脊柱，本 spec 是其选股 tab 内 pipeline 重设计）/ S094（双 pipeline）/ **§44**（CV 删除的依据）

## 1. 问题 / 目标

S140 脊柱试点后，选股（forward）tab 内 pipeline 用 `PipelineTopology`（echarts graph，476 行重组件）+ ④ 涨停叉内交叉验证（CV: `final_candidates ∩ scored_candidates`）。两问题：
- **echarts graph 太重**：476 行纯展示组件，render-break 风险高，且 graph 视图对"逐节点确认 pipeline"无增益（S140 脊柱已定 stage→语境视图→rail，graph 是平行冗余）。
- **④ CV 是 §44 假信号**：CV = 两 <2x 弱信号（finals 漏斗终选 + scored 战法命中）的交集；§44 判两 <2x 交集无 validated edge，且 `scored ⊆ finals`（战法命中是 finals 子集）非真双路交叉验证 → 呈现 CV 分组（dual/funnelOnly/strategyOnly）暗示不存在的 edge，违 §44 诚实。

目标：删 echarts graph → 轻量 2 列 pipeline（涨停叉 ‖ 非涨停叉，原始功能组件全保）；删 ④ CV（§44 诚实）；统一 date prop 流；死代码清零。

## 2. 背景

- **F** `PipelineTopology.tsx`（echarts graph，476 行）= S099 拓扑图，S140 后挂在选股 tab，纯展示 0 请求但重。
- **F** 双 pipeline（S094）：涨停叉（`final_candidates` 漏斗终选）‖ 非涨停叉（`market_scan_scored`）；`scored_candidates`（战法命中）⊆ `final_candidates`（构造上子集，因战法打分输入 = R3 幸存者 ⊆ finals）。
- **F** ④ CV（`computeLimitupInternalCV` + `useCrossValidationGroups`）：产 dual(∩)/funnelOnly/strategyOnly 三组 + `CrossValidationBadge`。选股 `PipelineFlow` ④ + 盯盘 `WatchlistBoard` 同源 CV。
- **F** §44 verdict：涨停叉/非涨停叉/breakout 全 <2x 无 validated edge（grill reframe + breakout-lift 1.36x 不可复现）。
- breakout（`premarket_selection`）§44 <2x 最弱方向特征，v1 降级为 2 级导航研究 tab（非 standalone edge）。

## 3. 需求清单

**v1（f80bd6c）—— pipeline 重设计**
- [x] R1 删 `PipelineTopology.tsx`（echarts graph，476 行）；新建 `PipelineFlow.tsx`（2 并行列：涨停叉 ‖ 非涨停叉，原始功能组件 `CandidateFunnelEmbed`/`StrategySubPipelineView`/`CandidateFactorTable`/`NonLimitupLane` 全保）
- [x] R2 ④ 涨停叉内 CV（`CrossValidationSummary` + `computeLimitupInternalCV`）接入 `PipelineFlow`（v1 加，v2 删）
- [x] R3 breakout 降级 2 级导航研究 tab（§44 <2x 最弱，非 standalone edge）

**v2（ec273e4）—— 统一流 + §44 诚实**
- [x] R4 删 ④ 涨停叉内 CV：`CrossValidationSummary`/`CrossValidationBadge`/`useCrossValidation` 三模块全删（§44 两 <2x 交集无 edge + scored⊆finals 非真双路）
- [x] R5 统一 date prop：`SelectionStageView`/`WatchlistBoard` drop `F`，用 `urlDate ?? forward`（统一日期源，去双 prop）
- [x] R6 `WatchlistBoard` 改用 `final_candidates` 直接列（去 CV 分组/badges/CollapsibleGroup）

## 4. 受影响文件

| 文件 | 改动 |
|---|---|
| `frontend/src/components/pipeline/PipelineTopology.tsx` | v1 删（echarts graph，-476） |
| `frontend/src/components/pipeline/PipelineFlow.tsx` | v1 新（2 列 pipeline）；v2 删 ④ CV（-17） |
| `frontend/src/components/pipeline/CrossValidationSummary.tsx` | v1 新（+65）；v2 删（-65，死代码清零） |
| `frontend/src/components/workflow/CrossValidationBadge.tsx` | v2 删（-27，死代码清零） |
| `frontend/src/lib/query/useCrossValidation.ts` | v1 改；v2 删（-84，死代码清零） |
| `frontend/src/components/workflow/WatchlistBoard.tsx` | v1 改（接 CV）；v2 改用 final_candidates 直接列（-111） |
| `frontend/src/pages/workflow/SelectionStageView.tsx` | v1 重构（2 级 nav）；v2 统一 date prop |
| `frontend/src/components/pipeline/SelectionPipeline.tsx` | v2 同步 |
| `frontend/src/pages/Workflow.tsx`/`PreMarketBriefing.tsx` | v2 同步 label/date |
| 测试 | `WatchlistBoard.test`/`Workflow.test`/`PreMarketBriefing.test` 同步更新 |

## 5. 设计方案

- **2 列 pipeline（PipelineFlow）**：涨停叉（`CandidateFunnelEmbed`①漏斗 + `StrategySubPipelineView`②战法匹配 + `CandidateFactorTable`★因子表）‖ 非涨停叉（`NonLimitupLane`⑤⑥⑦⑧）。原始功能组件全保，只换编排壳（graph → 2 列 flex）。
- **breakout 2 级 nav**：`SelectionStageView` 顶层 `pipeline | breakout` subtab；breakout（`BreakoutResearchView`/`PremarketSelectionSection`）降研究 tab，§44 <2x 非可操作 edge。
- **④ CV 删除（§44）**：CV 呈现 dual/funnelOnly/strategyOnly 暗示"交集=双路验证=更可信"——但 scored⊆finals 非真双路，且两 <2x 交集无 edge。删 CV 分组 + badges，`WatchlistBoard` 直接列 `final_candidates`（52 只漏斗终选），无虚假增强。
- **统一 date prop**：`SelectionStageView` 原收 `F`+`forward`+`urlDate`+`today` 四 prop；v2 drop `F`，briefing 用 `urlDate ?? forward`（统一日期源，去重复 prop）。`WatchlistBoard` 同步 drop `F`，用 `date`。
- **死代码清零**：v2 删 CV 三模块（`CrossValidationSummary`/`CrossValidationBadge`/`useCrossValidation`）——无外部 import、无 barrel re-export、无测试 import（grep 确认），真死代码，删。

## 6. 验收标准

- [x] A1 `PipelineTopology.tsx` 已删（echarts graph 清零）
- [x] A2 `CrossValidationSummary`/`CrossValidationBadge`/`useCrossValidation` 已删（CV 死代码清零）
- [x] A3 双 lane 在（`PipelineFlow` 涨停叉 ‖ 非涨停叉）
- [x] A4 `WatchlistBoard` 用 `final_candidates` 直接列（无 CV 分组）
- [x] A5 date prop 统一（`urlDate ?? forward`，无 `F` 双 prop）
- [x] A6 `tsc --noEmit` 0 error + `vitest run` 192/25 文件绿
- [x] A7 e2e 结构断言：选股 tab 渲染含"涨停叉"+"非涨停叉"、不含"交叉验证"/"funnelOnly"（CV 删坐实）

## 7. 合规与工程底线自查

- [x] 研判/推荐：本 spec 为前端结构重构，**删 §44 假信号（CV）是诚实化**（不新增方向输出）；breakout 降研究 tab 非 standalone edge。无新增买卖时机研判。
- [x] 判断可复现：无新数据计算；CV 删除依据 §44 verdict（grill reframe + breakout-lift 1.36x 不可复现，均 memory 登记）。
- [x] 涨停四池/连板股榜：不动 zt_pool 呈现。
- [x] 用户私有数据：纯前端重构。
- [x] 东财 em_get：无新增端点。

## 8. 测试计划

- 单元/组件：`vitest run` 192/25 文件绿（`WatchlistBoard.test`/`Workflow.test`/`PreMarketBriefing.test`/`SelectionStageView` 等）。
- 类型：`tsc --noEmit` 0 error。
- e2e 结构：`/workflow?view=forward` 渲染含"涨停叉"+"非涨停叉"+不含"交叉验证"（DOM 断言，2026-09-03 绿）。
- 视觉：`_preview-s146v2.spec.ts` 截图（dev 工具，手动复核）。

## 9. 风险与回滚

- **删 CV（§44 诚实）**：回滚 = 复活三模块（不推荐，违 §44）。CV 是假信号，删是修正非退步。
- **删 PipelineTopology（echarts）**：回滚 = `git revert f80bd6c`（v1）。echarts graph 已被 2 列 pipeline 取代，无功能损失。
- **统一 date prop**：`urlDate ?? forward` 与原 `F` 语义一致（F=forward 数据日），无行为变更（vitest 验证）。
- **breakout 降级**：仍可经 subtab 访问，无功能丢失，仅降级呈现。
