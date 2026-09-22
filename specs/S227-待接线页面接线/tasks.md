# S227 tasks — 可执行 checklist

## 批 1：已有 API 页面接 router（6 页）

- [x] T1.1 `router.tsx` 加 6 lazyEl：BombAlertPanel（/workflow/bomb-alerts）+ AuctionScreener（/limitup/auction-screener）+ FirstBoardPipeline（/archive/first-board-pipeline）+ IntradayMonitor（/workflow/intraday-monitor）+ PostMarketReview（/workflow/post-market-review）+ GeneScreener（/limitup/gene-screener）
- [x] T1.2 `tsc --noEmit` 确认 0 错
- [x] T1.3 vitest 全绿（修 2 pre-existing fail：BombAlertBanner MemoryRouter + modules.test live 数同步）

## 批 2：3 页已接线（非纯 UI，确认 hooks 已在）

- [x] T2.1 确认 IntradayMonitor 用 useIntradayLatest（:75）+ PostMarketReview 用 useDailyWinReview/useShadowComparison（:65/68）+ GeneScreener 用 getGeneScreener（:53）
- [x] T2.2 类型已对齐（lib/api/types.ts 现有）
- [x] T2.3 hooks 已在 lib/query（useIntradayLatest/useDailyWinReview/useShadowComparison）+ lib/api（getGeneScreener）
- [x] T2.4-T2.6 3 页已渲染真数据（非空态）
- [x] T2.7 router 3 lazyEl 已在批 1 加
- [x] T2.8 tsc 0 错 + 3 页有真数据 hook

## 批 3：组件接进页（3 接 + 1 defer）

- [x] T3.1 ScatterChart/TrendChart 接进 ForwardTestPanel（backtest 可视化自然 home）
- [x] T3.2 ScatterChart 接进 ForwardTestPanel（建 useBacktestScatter hook → api.backtestScatter，BacktestScatterPoint ≡ ScatterPoint 字段对齐）
- [x] T3.3 TrendChart 接进 ForwardTestPanel（建 useBacktestTrend hook → api.backtestTrend，HitRateChart + AvgReturnChart 用 BacktestSnapshotRow[]）
- [x] T3.4 PremarketSelectionSection 接进 PreMarketBriefing（WatchlistBoard 前，传 date，自取 usePremarketSelection）
- [x] T3.6 PremarketSelectionSection 接进 + tsc 0 错
- [ ] T3.5 CandidateProgressiveCard **defer**——CandidateCardData 字段（strategy_code/score/one_line_reason/risk_label/sector_phase/quality_standards/...）无完整匹配 API（ScoredCandidate 部分匹配但 risk_label/one_line_reason 需臆造，违背"不臆造"工程底线）。待后端补完整 candidate recommendation endpoint 或诚实 adapter fallback（risk_label="未评级"）后接

## 批 4：导航入口

- [ ] T4.1 nav 加 6 页面入口（workflow/limitup/archive 分组，按 nav-ia-phase2 collapsible）
- [ ] T4.2 导航可见 + 点击跳转

## 验收

- [x] T5.1 tsc --noEmit 0 错
- [x] T5.2 vitest 全绿（457/457）
- [ ] T5.3 6 路由 curl 200 + 渲染（待后端启动）
- [~] T5.4 4 组件非 orphan：3 接进（ScatterChart/TrendChart/PremarketSelectionSection）+ 1 defer（CandidateProgressiveCard 数据源不匹配）
- [ ] T5.5 commit + 引用 S227
