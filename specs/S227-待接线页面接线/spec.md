# S227 待接线页面接线

## 状态
已实现（2026-09-23）—— 批 1/2/3/4 done；CandidateProgressiveCard defer（CandidateCardData 无完整匹配 API，硬接需臆造 risk_label/one_line_reason，违背"不臆造"工程底线，待后端补完整 candidate recommendation endpoint 后接）

## 问题/目标
10 个前端页面/组件已实现但未接进 router（用户无法通过导航访问）：
- **5 页面**：IntradayMonitor / PostMarketReview / BombAlertPanel / AuctionScreener / GeneScreener + archive FirstBoardPipeline
- **4 组件**：ScatterChart / TrendChart / CandidateProgressiveCard / PremarketSelectionSection

后端端点已存在（`/api/workflow/intraday` + `/api/workflow/post-market` + `/api/risk/bomb-alerts` + `/api/limitup/auction/top` + `/api/limitup/screener` + `/api/workflow/first-board/candidates`），但前端 3 页（IntradayMonitor / PostMarketReview / GeneScreener）未调 API（纯 UI 无数据）。

**目标**：10 页面接进 router + 补 3 页前端 API 调用 + 4 组件接进其他页，用户可导航访问 + 页面显示真数据。

## 需求清单
1. `router.tsx` 加 6 路由：
   - `/workflow/intraday-monitor` → IntradayMonitor
   - `/workflow/post-market-review` → PostMarketReview
   - `/workflow/bomb-alerts` → BombAlertPanel
   - `/limitup/auction-screener` → AuctionScreener
   - `/limitup/gene-screener` → GeneScreener
   - `/archive/first-board-pipeline` → FirstBoardPipeline
2. IntradayMonitor 补 `useQuery` 调 `/api/workflow/intraday`（workflow.py:790）
3. PostMarketReview 补 `useQuery` 调 `/api/workflow/post-market`（workflow.py:797）
4. GeneScreener 补 `useQuery` 调 `/api/limitup/screener`（limitup/screener.py:55）
5. 4 组件接进相关页：
   - ScatterChart / TrendChart → charts 页或 stock 详情（数据可视化用）
   - CandidateProgressiveCard / PremarketSelectionSection → workflow 页（PreMarketBriefing 或新 workflow 入口）
6. 导航 nav 加 6 页面入口（如适用，按 nav-ia-phase2 collapsible 模式）

## 受影响文件
- `frontend/src/router.tsx`（加 6 lazyEl）
- `frontend/src/pages/workflow/IntradayMonitor.tsx`（补 useQuery + 渲染数据）
- `frontend/src/pages/workflow/PostMarketReview.tsx`（补 useQuery + 渲染数据）
- `frontend/src/pages/limitup/GeneScreener.tsx`（补 useQuery + 渲染数据）
- `frontend/src/components/nav/*`（加导航入口，如适用）
- 4 组件接进的页面（plan 评估定具体页）
- `frontend/src/lib/api/types.ts`（如需补 IntradayMonitor/PostMarketReview/GeneScreener 响应类型）
- `frontend/src/lib/query.ts`（如需补 useIntradayWorkflow/usePostMarketWorkflow/useGeneScreener hooks）

## 验收标准
1. `tsc --noEmit` 0 错
2. 6 路由可访问（curl 或浏览器返 200 + 渲染组件）
3. IntradayMonitor / PostMarketReview / GeneScreener 显示真数据（调对应后端端点，非空态）
4. vitest 全绿（新增接线不破坏现有测试，含 IntradayMonitor/PostMarketReview/BombAlertPanel/AuctionScreener/GeneScreener/FirstBoardPipeline 测试）
5. 4 组件接进至少 1 页（非 orphan，tsc 无 unused）

## 合规自查
- **工程底线**：不臆造数据（API 返空标 missing/降级，不编造）；私有数据隔离（持仓不进 git）
- **弱合规**：页面如实呈现数据，缺数据标 missing 不崩（对齐 S069 降级不崩契约）
