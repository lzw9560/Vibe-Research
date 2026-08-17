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
      { path: "/", element: <Navigate to="/daily-review" replace /> },
      { path: "/daily-review", element: lazyEl(() => import("@/pages/DailyReview"), "DailyReview") },
      { path: "/daily-review/emotion", element: lazyEl(() => import("@/pages/DailyReview/pages/EmotionDetail"), "EmotionDetail") },
      { path: "/daily-review/sectors", element: lazyEl(() => import("@/pages/DailyReview/pages/SectorDetail"), "SectorDetail") },
      { path: "/daily-review/review", element: lazyEl(() => import("@/pages/DailyReview/pages/ReviewDetail"), "ReviewDetail") },
      { path: "/intel", element: lazyEl(() => import("@/pages/Intel"), "Intel") },
      { path: "/sectors", element: lazyEl(() => import("@/pages/Sectors"), "Sectors") },
      { path: "/sectors/:key", element: lazyEl(() => import("@/pages/SectorDetail"), "SectorDetail") },
      { path: "/portfolio", element: lazyEl(() => import("@/pages/Portfolio"), "Portfolio") },
      { path: "/stock-data", element: lazyEl(() => import("@/pages/StockData"), "StockData") },
      { path: "/stock/:code", element: lazyEl(() => import("@/pages/StockDeep"), "StockDeep") },
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
      { path: "/advisory", element: lazyEl(() => import("@/pages/Advisory")) },
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
      { path: "/workflow/pre-market", element: lazyEl(() => import("@/pages/workflow/PreMarketBriefing")) },
      { path: "/behavior-loop", element: lazyEl(() => import("@/pages/BehaviorLoop")) },
      { path: "/workflow/intraday", element: lazyEl(() => import("@/pages/workflow/IntradayMonitor")) },
      { path: "/workflow/coach", element: lazyEl(() => import("@/pages/workflow/IntradayCoach"), "IntradayCoach") },
      { path: "/workflow/alerts", element: lazyEl(() => import("@/pages/workflow/BombAlertPanel")) },
      { path: "/workflow/post-market", element: lazyEl(() => import("@/pages/workflow/PostMarketReview")) },
      { path: "/workflow/topology", element: lazyEl(() => import("@/pages/workflow/Topology"), "Topology") },
      { path: "/workflow/candidates/:code", element: lazyEl(() => import("@/pages/workflow/CandidateDetail")) },
      { path: "/workflow/factor/:factorId", element: lazyEl(() => import("@/pages/workflow/FactorDetailPage"), "FactorDetailPage") },
      { path: "/sector-divergence", element: lazyEl(() => import("@/pages/SectorDivergence")) },
      { path: "/prediction", element: lazyEl(() => import("@/pages/Prediction")) },
      { path: "/metrics", element: lazyEl(() => import("@/pages/Metrics"), "Metrics") },
      { path: "/health", element: lazyEl(() => import("@/pages/Health"), "HealthPage") },
      { path: "/scheduled-tasks", element: lazyEl(() => import("@/pages/ScheduledTasks"), "ScheduledTasks") },
      { path: "/industry", element: lazyEl(() => import("@/pages/Industry"), "Industry") },
      { path: "/debate", element: lazyEl(() => import("@/pages/Debate"), "Debate") },
    ],
  },
]);
