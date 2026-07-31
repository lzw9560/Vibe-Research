import { createBrowserRouter, Navigate } from "react-router-dom";
import { Layout } from "@/components/layout/Layout";
import { DailyReview } from "@/pages/DailyReview";
import { Intel } from "@/pages/Intel";
import { Sectors } from "@/pages/Sectors";
import { SectorDetail } from "@/pages/SectorDetail";
import { Portfolio } from "@/pages/Portfolio";
import { StockData } from "@/pages/StockData";
import { Watchlist } from "@/pages/Watchlist";
import { Candidates } from "@/pages/Candidates";
import { ValueFunnel } from "@/pages/ValueFunnel";
import { MyReports } from "@/pages/MyReports";
import { Notes } from "@/pages/Notes";
import { Settings } from "@/pages/Settings";
import { LimitUpStrategy } from "@/pages/LimitUpStrategy";
import { StockDeep } from "@/pages/StockDeep";
import Recommendation from "@/pages/Recommendation";
import StrategySignals from "@/pages/StrategySignals";
import RiskDashboard from "@/pages/RiskDashboard";
import Backtest from "@/pages/Backtest";
import { HealthPage as Health } from "@/pages/Health";
import { Metrics } from "@/pages/Metrics";
import { ScheduledTasks } from "@/pages/ScheduledTasks";
import { Industry } from "@/pages/Industry";
import Workflow from "@/pages/Workflow";
import SentimentWeather from "@/pages/sentiment/SentimentWeather";
import { GeneScreener } from "@/pages/limitup/GeneScreener";
import { AuctionScreener } from "@/pages/limitup/AuctionScreener";
import { SeatEngine } from "@/pages/limitup/SeatEngine";
import PreMarketBriefing from "@/pages/workflow/PreMarketBriefing";
import IntradayMonitor from "@/pages/workflow/IntradayMonitor";
import BombAlertPanel from "@/pages/workflow/BombAlertPanel";
import PostMarketReview from "@/pages/workflow/PostMarketReview";
import SectorDivergence from "@/pages/SectorDivergence";
import { Prediction } from "@/pages/Prediction";

export const router = createBrowserRouter([
  {
    element: <Layout />,
    children: [
      { path: "/", element: <Navigate to="/daily-review" replace /> },
      { path: "/daily-review", element: <DailyReview /> },
      { path: "/intel", element: <Intel /> },
      { path: "/sectors", element: <Sectors /> },
      { path: "/sectors/:key", element: <SectorDetail /> },
      { path: "/portfolio", element: <Portfolio /> },
      { path: "/stock-data", element: <StockData /> },
      { path: "/stock/:code", element: <StockDeep /> },
      { path: "/watchlist", element: <Watchlist /> },
      { path: "/candidates", element: <Candidates /> },
      { path: "/value-funnel", element: <ValueFunnel /> },
      { path: "/my-reports", element: <MyReports /> },
      { path: "/notes", element: <Notes /> },
      { path: "/settings", element: <Settings /> },
      { path: "/limitup", element: <LimitUpStrategy /> },
      { path: "/limitup/gene", element: <GeneScreener /> },
      { path: "/limitup/auction", element: <AuctionScreener /> },
      { path: "/limitup/seats", element: <SeatEngine /> },
      { path: "/recommendation", element: <Recommendation /> },
      { path: "/strategy-signals", element: <StrategySignals /> },
      { path: "/backtest", element: <Backtest /> },
      { path: "/risk-dashboard", element: <RiskDashboard /> },
      { path: "/sentiment/weather", element: <SentimentWeather /> },
      { path: "/sentiment/weather/history", element: <SentimentWeather /> },
      { path: "/sentiment/weather/strategy", element: <SentimentWeather /> },
      { path: "/sentiment/weather/fuse", element: <SentimentWeather /> },
      { path: "/workflow", element: <Workflow /> },
      { path: "/workflow/pre-market", element: <PreMarketBriefing /> },
      { path: "/workflow/intraday", element: <IntradayMonitor /> },
      { path: "/workflow/alerts", element: <BombAlertPanel /> },
      { path: "/workflow/post-market", element: <PostMarketReview /> },
      { path: "/sector-divergence", element: <SectorDivergence /> },
      { path: "/prediction", element: <Prediction /> },
      { path: "/metrics", element: <Metrics /> },
      { path: "/health", element: <Health /> },
      { path: "/scheduled-tasks", element: <ScheduledTasks /> },
      { path: "/industry", element: <Industry /> },
    ],
  },
]);
