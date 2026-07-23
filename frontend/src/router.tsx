import { createBrowserRouter, Navigate } from "react-router-dom";
import { Layout } from "@/components/layout/Layout";
import { DailyReview } from "@/pages/DailyReview";
import { Intel } from "@/pages/Intel";
import { Sectors } from "@/pages/Sectors";
import { SectorDetail } from "@/pages/SectorDetail";
import { Industry } from "@/pages/Industry";
import { Portfolio } from "@/pages/Portfolio";
import { StockDeep } from "@/pages/StockDeep";
import { StockData } from "@/pages/StockData";
import { Watchlist } from "@/pages/Watchlist";
import { MyReports } from "@/pages/MyReports";
import { Notes } from "@/pages/Notes";
import { Settings } from "@/pages/Settings";
import { GeneScreener } from "@/pages/limitup/GeneScreener";
import { AuctionScreener } from "@/pages/limitup/AuctionScreener";
import { SeatEngine } from "@/pages/limitup/SeatEngine";
import { Metrics } from "@/pages/Metrics";
import Recommendation from "@/pages/Recommendation";
import StrategySignals from "@/pages/StrategySignals";
import RiskDashboard from "@/pages/RiskDashboard";
import Backtest from "@/pages/Backtest";

export const router = createBrowserRouter([
  {
    element: <Layout />,
    children: [
      { path: "/", element: <Navigate to="/daily-review" replace /> },
      { path: "/daily-review", element: <DailyReview /> },
      { path: "/intel", element: <Intel /> },
      { path: "/sectors", element: <Sectors /> },
      { path: "/sectors/:key", element: <SectorDetail /> },
      { path: "/industry", element: <Industry /> },
      { path: "/stock-data", element: <StockData /> },
      { path: "/stock/:code", element: <StockDeep /> },
      { path: "/watchlist", element: <Watchlist /> },
      { path: "/portfolio", element: <Portfolio /> },
      { path: "/my-reports", element: <MyReports /> },
      { path: "/notes", element: <Notes /> },
      { path: "/limitup", element: <Navigate to="/limitup/gene" replace /> },
      { path: "/limitup/gene", element: <GeneScreener /> },
      { path: "/limitup/auction", element: <AuctionScreener /> },
      { path: "/limitup/seats", element: <SeatEngine /> },
      { path: "/metrics", element: <Metrics /> },
      { path: "/recommendation", element: <Recommendation /> },
      { path: "/strategy-signals", element: <StrategySignals /> },
      { path: "/backtest", element: <Backtest /> },
      { path: "/risk-dashboard", element: <RiskDashboard /> },
      { path: "/settings", element: <Settings /> },
    ],
  },
]);
