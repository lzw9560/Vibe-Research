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
import { HealthPage } from "@/pages/Health";
import SentimentWeather from "@/pages/sentiment/SentimentWeather";
import Workflow from "@/pages/Workflow";
import PreMarketBriefing from "@/pages/workflow/PreMarketBriefing";
import IntradayMonitor from "@/pages/workflow/IntradayMonitor";
import BombAlertPanel from "@/pages/workflow/BombAlertPanel";
import PostMarketReview from "@/pages/workflow/PostMarketReview";
import { ScheduledTasks } from "@/pages/ScheduledTasks";

export interface RouteMeta {
  title: string;
  group: number; // which nav group (0-indexed)
  breadcrumb?: string[];
}

export const routeMetaMap: Record<string, Partial<RouteMeta>> = {
  "/daily-review": { title: "每日复盘", group: 0 },
  "/sentiment/weather": { title: "情绪气象站", group: 0 },
  "/sentiment/weather/history": { title: "历史趋势", group: 0 },
  "/sentiment/weather/strategy": { title: "策略建议", group: 0 },
  "/sentiment/weather/fuse": { title: "熔断规则", group: 0 },
  "/intel": { title: "资讯雷达", group: 0 },
  "/sectors": { title: "板块中心", group: 0 },
  "/sectors/:key": { title: "板块详情", group: 0 },
  "/industry": { title: "行业排行", group: 0 },
  "/stock-data": { title: "个股数据", group: 1 },
  "/stock/:code": { title: "个股深度分析", group: 1 },
  "/watchlist": { title: "自选股", group: 1 },
  "/recommendation": { title: "推荐关注", group: 1 },
  "/portfolio": { title: "我的持仓", group: 2 },
  "/my-reports": { title: "我的研报", group: 2 },
  "/notes": { title: "研究记录", group: 2 },
  "/workflow": { title: "打板工作流", group: 3 },
  "/workflow/pre-market": { title: "盘前简报", group: 3 },
  "/workflow/intraday": { title: "盘中监控", group: 3 },
  "/workflow/alerts": { title: "炸板预警", group: 3 },
  "/workflow/post-market": { title: "盘后复盘", group: 3 },
  "/limitup/gene": { title: "基因选股", group: 4 },
  "/limitup/auction": { title: "竞价预案", group: 4 },
  "/limitup/seats": { title: "席位引擎", group: 4 },
  "/strategy-signals": { title: "战法信号", group: 4 },
  "/backtest": { title: "简化回测", group: 4 },
  "/risk-dashboard": { title: "风险仪表盘", group: 4 },
  "/scheduled-tasks": { title: "定时任务", group: 5 },
  "/settings": { title: "系统设置", group: 5 },
  "/metrics": { title: "性能监控", group: 5 },
  "/health": { title: "系统健康", group: 5 },
};

// 分组定义（与 routerMetaMap 的 group 索引对应）
export const NAV_GROUPS = [
  { name: "市场概览", icon: "activity" as const },
  { name: "个股分析", icon: "search" as const },
  { name: "投资管理", icon: "wallet" as const },
  { name: "打板工作流", icon: "flame" as const },
  { name: "策略工具", icon: "flame" as const },
  { name: "系统管理", icon: "cog" as const },
];

// 路由到分组的映射表（用于 findActiveGroup）
const GROUP_MAP: Record<string, number> = {
  // Group 0: 市场概览
  "/daily-review": 0,
  "/sentiment/": 0,
  "/intel": 0,
  "/sectors": 0,
  "/industry": 0,
  // Group 1: 个股分析
  "/stock-data": 1,
  "/stock/": 1,
  "/watchlist": 1,
  "/recommendation": 1,
  // Group 2: 投资管理
  "/portfolio": 2,
  "/my-reports": 2,
  "/notes": 2,
  // Group 3: 打板工作流
  "/workflow": 3,
  // Group 4: 策略工具
  "/limitup/": 4,
  "/strategy-signals": 4,
  "/backtest": 4,
  "/risk-dashboard": 4,
  // Group 5: 系统管理
  "/scheduled-tasks": 5,
  "/settings": 5,
  "/metrics": 5,
  "/health": 5,
};

/**
 * 根据 pathname 找到所属分组索引
 * 支持前缀匹配（如 /stock/123456 → group 1）
 */
export function findActiveGroup(pathname: string): number {
  // 精确匹配优先
  if (GROUP_MAP[pathname] !== undefined) return GROUP_MAP[pathname];
  // 前缀匹配
  for (const [prefix, groupIdx] of Object.entries(GROUP_MAP)) {
    if (pathname.startsWith(prefix)) return groupIdx;
  }
  return 0; // default
}

/**
 * 根据 pathname 找到在分组内的 tab 索引
 * 返回该分组下所有 tab 中匹配的第一个
 */
export function findActiveTabIndex(pathname: string, groupIndex: number): number {
  const tabsByGroup: string[][] = [
    ["/daily-review", "/sentiment/weather", "/intel", "/sectors", "/industry"],
    ["/stock-data", "/watchlist", "/recommendation"],
    ["/portfolio", "/my-reports", "/notes"],
    ["/workflow", "/workflow/pre-market", "/workflow/intraday", "/workflow/alerts", "/workflow/post-market"],
    ["/limitup/gene", "/limitup/auction", "/limitup/seats", "/strategy-signals", "/backtest", "/risk-dashboard"],
    ["/scheduled-tasks", "/settings", "/metrics", "/health"],
  ];
  const tabs = tabsByGroup[groupIndex] || [];
  for (let i = 0; i < tabs.length; i++) {
    const tab = tabs[i];
    if (pathname === tab || pathname.startsWith(tab + "/")) return i;
  }
  return 0;
}

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
      { path: "/workflow", element: <Workflow /> },
      { path: "/workflow/pre-market", element: <PreMarketBriefing /> },
      { path: "/workflow/intraday", element: <IntradayMonitor /> },
      { path: "/workflow/alerts", element: <BombAlertPanel /> },
      { path: "/workflow/post-market", element: <PostMarketReview /> },
      { path: "/sentiment/weather", element: <SentimentWeather /> },
      { path: "/sentiment/weather/history", element: <SentimentWeather /> },
      { path: "/sentiment/weather/strategy", element: <SentimentWeather /> },
      { path: "/sentiment/weather/fuse", element: <SentimentWeather /> },
      { path: "/metrics", element: <Metrics /> },
      { path: "/recommendation", element: <Recommendation /> },
      { path: "/strategy-signals", element: <StrategySignals /> },
      { path: "/backtest", element: <Backtest /> },
      { path: "/risk-dashboard", element: <RiskDashboard /> },
      { path: "/settings", element: <Settings /> },
      { path: "/health", element: <HealthPage /> },
      { path: "/scheduled-tasks", element: <ScheduledTasks /> },
    ],
  },
]);
