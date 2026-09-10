// S013 T10：全量懒加载。每页 React.lazy + Suspense 包裹，Vite code-split 出独立 chunk，
// 首包只含 Layout + 当前路由。fallback 为轻量加载占位，避免空白闪烁。
import { createBrowserRouter, Navigate } from "react-router-dom";
import { lazy, Suspense, type ComponentType } from "react";
import { Layout } from "@/components/layout/Layout";

const PageFallback = (
  <div className="flex h-[60vh] items-center justify-center text-sm text-gray-500">
    加载中…
  </div>
);

/** named export：传 name；default export：省略 name（取 m.default）。 */
function lazyEl<T extends ComponentType<any>>(
  loader: () => Promise<Record<string, T>>,
  name?: string,
) {
  const Lazy = lazy(async () => {
    const m = await loader();
    return { default: (name ? (m as Record<string, T>)[name] : m.default) as ComponentType<any> };
  });
  return (
    <Suspense fallback={PageFallback}>
      <Lazy />
    </Suspense>
  );
}

export const router = createBrowserRouter([
  {
    element: <Layout />,
    children: [
      { path: "/", element: <Navigate to="/market" replace /> },
      // S179 R3.3: DailyReview 删，功能已迁 /market。旧 URL redirect 保兼容
      { path: "/daily-review", element: <Navigate to="/market" replace /> },
      { path: "/daily-review/emotion", element: <Navigate to="/market" replace /> },
      { path: "/daily-review/sectors", element: <Navigate to="/market" replace /> },
      { path: "/daily-review/review", element: <Navigate to="/market" replace /> },
      { path: "/intel", element: lazyEl(() => import("@/pages/Intel"), "Intel") },
      { path: "/sectors", element: lazyEl(() => import("@/pages/Sectors"), "Sectors") },
      { path: "/sectors/:key", element: lazyEl(() => import("@/pages/SectorDetail"), "SectorDetail") },
      // S179 Phase 2 R2.4: /portfolio → PortfolioPage（四维 cockpit：持仓+风险+健康+PB-ROE）。旧 Portfolio.tsx 保留 Phase 3 删
      { path: "/portfolio", element: lazyEl(() => import("@/pages/portfolio/PortfolioPage"), "PortfolioPage") },
      { path: "/stock-data", element: lazyEl(() => import("@/pages/StockData"), "StockData") },
      // S179 Phase 1: 高价值新页（/market 首屏 cockpit + /screener 选股器）
      { path: "/market", element: lazyEl(() => import("@/pages/market/MarketPage"), "MarketPage") },
      { path: "/screener", element: lazyEl(() => import("@/pages/screener/ScreenerPage"), "ScreenerPage") },
      { path: "/stock/:code", element: lazyEl(() => import("@/pages/stock/StockCockpit"), "StockCockpit") },
      { path: "/watchlist", element: lazyEl(() => import("@/pages/Watchlist"), "Watchlist") },
      { path: "/candidates", element: lazyEl(() => import("@/pages/Candidates"), "Candidates") },
      { path: "/value-funnel", element: lazyEl(() => import("@/pages/ValueFunnel"), "ValueFunnel") },
      { path: "/my-reports", element: lazyEl(() => import("@/pages/MyReports"), "MyReports") },
      { path: "/notes", element: lazyEl(() => import("@/pages/Notes"), "Notes") },
      { path: "/settings", element: lazyEl(() => import("@/pages/Settings"), "Settings") },
      { path: "/limitup", element: lazyEl(() => import("@/pages/LimitUpStrategy"), "LimitUpStrategy") },
      { path: "/limitup/gene", element: lazyEl(() => import("@/pages/limitup/GeneScreener"), "GeneScreener") },
      { path: "/limitup/auction", element: lazyEl(() => import("@/pages/limitup/AuctionScreener"), "AuctionScreener") },
      { path: "/limitup/seats", element: lazyEl(() => import("@/pages/limitup/SeatEngine"), "SeatEngine") },
      { path: "/limitup/premarket", element: lazyEl(() => import("@/pages/limitup/PremarketSelection"), "PremarketSelection") },
      { path: "/recommendation", element: lazyEl(() => import("@/pages/Recommendation")) },
      // S179 Phase 2 R2.5: /advisory → AdvisoryPage（三区 cockpit）。旧 Advisory.tsx 保留 Phase 3 删
      { path: "/advisory", element: lazyEl(() => import("@/pages/advisory/AdvisoryPage"), "AdvisoryPage") },
      { path: "/strategy-signals", element: lazyEl(() => import("@/pages/StrategySignals")) },
      { path: "/backtest", element: lazyEl(() => import("@/pages/Backtest")) },
      { path: "/risk-dashboard", element: lazyEl(() => import("@/pages/RiskDashboard")) },
      // 情绪气象（T-1 天气独立页，4 tab 由 pathname 选；曾误重定向 intraday，恢复路由）
      { path: "/sentiment/weather", element: lazyEl(() => import("@/pages/sentiment/SentimentWeather")) },
      { path: "/sentiment/weather/history", element: lazyEl(() => import("@/pages/sentiment/SentimentWeather")) },
      { path: "/sentiment/weather/strategy", element: lazyEl(() => import("@/pages/sentiment/SentimentWeather")) },
      { path: "/sentiment/weather/fuse", element: lazyEl(() => import("@/pages/sentiment/SentimentWeather")) },
      { path: "/workflow", element: lazyEl(() => import("@/pages/Workflow")) },
      { path: "/workflow/first-board", element: lazyEl(() => import("@/pages/workflow/FirstBoardPage")) },
      { path: "/workflow/pre-market", element: <Navigate to="/workflow?view=today" replace /> },
      { path: "/behavior-loop", element: lazyEl(() => import("@/pages/BehaviorLoop")) },
      { path: "/workflow/intraday", element: lazyEl(() => import("@/pages/workflow/IntradayMonitor")) },
      // S178: OFI 盘中数据只读看板（read-only，非信号）
      { path: "/workflow/intraday/ofi", element: lazyEl(() => import("@/pages/workflow/OfiDashboardPage")) },
      { path: "/workflow/coach", element: lazyEl(() => import("@/pages/workflow/IntradayCoach")) },
      { path: "/workflow/alerts", element: lazyEl(() => import("@/pages/workflow/BombAlertPanel")) },
      { path: "/workflow/post-market", element: <Navigate to="/workflow?view=review" replace /> },
      { path: "/workflow/topology", element: lazyEl(() => import("@/pages/workflow/Topology"), "Topology") },
      // S090 战法 tab 404 修复：前向测试 + 阈值配置独立页（EntryCard 链接原指向 404）
      // S093 T20：/strategy 父路由（战法独立页），承接 S3 删的战法战绩折叠区
      { path: "/strategy", element: lazyEl(() => import("@/pages/strategy/StrategyPage")) },
      { path: "/strategy/funnel/forward-test", element: lazyEl(() => import("@/pages/strategy/ForwardTestPage")) },
      { path: "/strategy/funnel/config", element: lazyEl(() => import("@/pages/strategy/StrategyConfigPage")) },
      { path: "/workflow/candidates/:code", element: lazyEl(() => import("@/pages/workflow/CandidateDetail")) },
      { path: "/workflow/factor/:factorId", element: lazyEl(() => import("@/pages/workflow/FactorDetailPage"), "FactorDetailPage") },
      { path: "/sector-divergence", element: lazyEl(() => import("@/pages/SectorDivergence")) },
      { path: "/prediction", element: lazyEl(() => import("@/pages/Prediction")) },
      { path: "/metrics", element: lazyEl(() => import("@/pages/Metrics"), "Metrics") },
      { path: "/health", element: lazyEl(() => import("@/pages/Health"), "HealthPage") },
      { path: "/scheduled-tasks", element: lazyEl(() => import("@/pages/ScheduledTasks"), "ScheduledTasks") },
      { path: "/industry", element: lazyEl(() => import("@/pages/Industry"), "Industry") },
      { path: "/debate", element: lazyEl(() => import("@/pages/Debate"), "Debate") },
      // S165: §44 验证实验记录（RecorderRecord[]）+ 维度验证卡网格
      { path: "/verifier-records", element: lazyEl(() => import("@/pages/VerifierRecords"), "VerifierRecords") },
      // S166: 交易日志 + 风险账本（Trade Journal + Risk Ledger，fresh-impl）
      { path: "/journal", element: lazyEl(() => import("@/pages/Journal"), "Journal") },
      // S171: 价值因子月度验证看板（低 PE 价值溢价 §44v2 验证，UI 先行 mock，真 verdict 待 long_value_run.py）
      { path: "/value-verdict", element: lazyEl(() => import("@/pages/S171ValueVerdict"), "S171ValueVerdict") },
      // S179 Phase 2: 盘中+研究新页
      { path: "/multiline", element: lazyEl(() => import("@/pages/multiline/MultilinePage"), "MultilinePage") },
      { path: "/review", element: lazyEl(() => import("@/pages/review/ReviewPage"), "ReviewPage") },
    ],
  },
]);
