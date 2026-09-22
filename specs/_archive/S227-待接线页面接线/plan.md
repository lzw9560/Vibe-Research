# S227 plan — 技术方案

## 接线策略

后端端点全有，只需前端接线 + 补 3 页 API 调用。按"已有端点优先 + 无端点补前端调用"分两批。

## 批 1：已有 API 的页面接 router（4 页，低风险）

BombAlertPanel（已 `api.bombAlerts()`）+ AuctionScreener（已 `useAuctionTop`）+ FirstBoardPipeline（已 `useFirstBoardCandidates`）+ PremarketSelectionSection（已 refetch）——只需 `router.tsx` 加 lazyEl，不改页面逻辑。

## 批 2：补 API 的页面（3 页，中风险）

IntradayMonitor / PostMarketReview / GeneScreener 当前无 API 调用（纯 UI）。补：
1. `lib/api/types.ts` 加 IntradayWorkflow / PostMarketWorkflow / GeneScreenerResult 响应类型（按后端 pydantic 模型）
2. `lib/api/client.ts` 或 `lib/query.ts` 加 `useIntradayWorkflow` / `usePostMarketWorkflow` / `useGeneScreener` hooks（useQuery 调对应端点）
3. 页面 import hook + 渲染数据（替换纯 UI 占位）

## 批 3：组件接进页（4 组件，低风险）

ScatterChart / TrendChart → 接进 stock 详情或 charts 页（数据可视化）；CandidateProgressiveCard / PremarketSelectionSection → 接进 workflow 页（PreMarketBriefing 或新入口）。评估具体接进页（plan 评估，避免强耦合）。

## 批 4：导航入口（nav）

按 nav-ia-phase2 collapsible 模式加 6 页面入口（workflow/limitup/archive 分组）。

## 依赖序
1. 批 1（router 接线，4 页）→ tsc 确认
2. 批 2（补 3 页 API）→ tsc + 页面渲染确认
3. 批 3（组件接进）→ tsc + 无 orphan 确认
4. 批 4（nav 入口）→ 导航可见
5. vitest + tsc 全绿

## 备选为何不选
- **不重构页面**：只接线 + 补 API，不重写页面逻辑（YAGNI，页面已实现）
- **不补后端端点**：后端全有，不新增（09-18 冻结新基建）
- **不删 archive FirstBoardPipeline**：用户明确"不删"

## 风险
- 3 页补 API 可能响应类型不匹配（后端 pydantic vs 前端 types）→ plan 评估后端模型，对齐类型
- 组件接进页可能强耦合 → 选低耦合页（charts 接 stock 详情，workflow 卡片接 PreMarketBriefing）
