// S013 T10：全量懒加载。每页 React.lazy + Suspense 包裹，Vite code-split 出独立 chunk，
// 首包只含 Layout + 当前路由。fallback 为轻量加载占位，避免空白闪烁。
// S186 Phase 2: 旧路由 redirect 到 6 域 19 内容路由（保留组件不删，Phase 3 才删）
import { createBrowserRouter, Navigate, Link } from "react-router-dom";
import { lazy, Suspense, type ComponentType } from "react";
import { Layout } from "@/components/layout/Layout";
import { PageSkeleton } from "@/components/ui/State";

const PageFallback = <PageSkeleton />;

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

/** S186 Phase 2: redirect 旧路由到新 6 域（保兼容，Phase 3 才删旧组件） */
function redirect(to: string) {
  return <Navigate to={to} replace />;
}

/** 404 catch-all（路由深度分析修复：未知路由不空白，提示+回首页） */
function NotFound() {
  return (
    <div className="flex h-[60vh] flex-col items-center justify-center gap-2 text-center">
      <div className="text-2xl font-semibold text-foreground">404 · 页面不存在 Not Found</div>
      <div className="text-sm text-muted-foreground">路由已迁移或不存在，回首页继续</div>
    <Link to="/today" className="text-primary underline">回首页 /today</Link>
    </div>
  );
}

export const router = createBrowserRouter([
  {
    element: <Layout />,
    children: [
      // ─── 多维度 IA: 5 线主入口 + 数据层 + 系统次入口 ───
      // 主入口（5 线 + 数据底座）
      { path: "/", element: redirect("/today") },
      { path: "/today", element: lazyEl(() => import("@/pages/today/TodayPage"), "TodayPage") },
      { path: "/workspace", element: lazyEl(() => import("@/pages/workspace/WorkspacePage"), "WorkspacePage") },
      { path: "/review", element: lazyEl(() => import("@/pages/review/ReviewPage"), "ReviewPage") },
      { path: "/graph", element: lazyEl(() => import("@/pages/cognition/CognitionPage"), "CognitionPage") },
      { path: "/data", element: lazyEl(() => import("@/pages/data/DataFoundationPage"), "DataFoundationPage") },
      { path: "/quant-models", element: lazyEl(() => import("@/pages/quant/QuantModelsPage"), "QuantModelsPage") },  // Track D M3: 量化模型 M1-M7（via Cmd+K palette）
      { path: "/earnings-calendar", element: lazyEl(() => import("@/pages/workspace/EarningsCalendarPage"), "EarningsCalendarPage") },  // Track E A3: 财报季日历（honest-empty，待接线 earnings-calendar endpoint）

      // ─── 旧页保留作详情页（新主入口链过去或嵌，保兼容）───
      // 看盘域
      { path: "/market", element: lazyEl(() => import("@/pages/market/MarketPage"), "MarketPage") },
      { path: "/intraday", element: lazyEl(() => import("@/pages/intraday/IntradayCockpit"), "IntradayCockpit") },
      { path: "/sentiment/weather", element: lazyEl(() => import("@/pages/sentiment/SentimentWeather")) },
      { path: "/sentiment/weather/macro", element: lazyEl(() => import("@/pages/sentiment/SentimentWeather")) },
      { path: "/sectors/:key", element: lazyEl(() => import("@/pages/SectorDetail"), "SectorDetail") },

      // 选股域
      { path: "/screener", element: lazyEl(() => import("@/pages/screener/ScreenerPage"), "ScreenerPage") },
      { path: "/watchlist", element: lazyEl(() => import("@/pages/Watchlist"), "Watchlist") },
      { path: "/bidding", element: lazyEl(() => import("@/pages/BiddingPage")) },  // FE-4: 集合竞价监控页（/api/auction/monitor+watchlist 前端独立页）
      { path: "/limitup", element: lazyEl(() => import("@/pages/LimitUpStrategy"), "LimitUpStrategy") },
      { path: "/limitup/premarket", element: lazyEl(() => import("@/pages/limitup/PremarketSelection"), "PremarketSelection") },

      // 个股域
      { path: "/stock/:code", element: lazyEl(() => import("@/pages/stock/StockCockpit"), "StockCockpit") },
      { path: "/stock-data", element: lazyEl(() => import("@/pages/StockData"), "StockData") },
      { path: "/fusion", element: lazyEl(() => import("@/pages/FusionPage")) },  // FE-6: S194 融合研判展示（输股票代码查 regime/方向/置信度/相似 case）

      // 模拟盘域
      { path: "/ledger", element: lazyEl(() => import("@/pages/ledger/LedgerPage"), "LedgerPage") },  // 持仓+日志（策略线"模拟"步，经 CTA 脊访问）
      { path: "/journal", element: lazyEl(() => import("@/pages/Journal"), "Journal") },
      { path: "/portfolio", element: lazyEl(() => import("@/pages/portfolio/PortfolioPage"), "PortfolioPage") },
      { path: "/risk", element: lazyEl(() => import("@/pages/RiskDashboard")) },  // FE-1: RiskDashboard 组件已写，S179 清理漏挂，补回独立路由
      { path: "/advisory", element: lazyEl(() => import("@/pages/advisory/AdvisoryPage"), "AdvisoryPage") },
      { path: "/multiline", element: lazyEl(() => import("@/pages/multiline/MultilinePage"), "MultilinePage") },

      // 复盘策略域
      { path: "/strategy", element: lazyEl(() => import("@/pages/strategy/StrategyPage")) },
      { path: "/topology", element: lazyEl(() => import("@/pages/workflow/Topology"), "Topology") },  // FE-5: 拓扑图独立页（组件在 workflow/，旧 /workflow/topology redirect 到 /review，补独立 /topology）
      { path: "/tracking", element: lazyEl(() => import("@/pages/tracking/TrackingPage"), "TrackingPage") },  // S204 T9: 多日跟踪只读看板（活跃 track 池 + 指标快照演进）

      // 系统域
      { path: "/settings", element: lazyEl(() => import("@/pages/Settings"), "Settings") },
      { path: "/chat", element: lazyEl(() => import("@/pages/ChatPage")) },  // FE-3: AI 对话网页入口（不依赖飞书 bot，调 /api/chat 流式）
      { path: "/scheduled-tasks", element: lazyEl(() => import("@/pages/ScheduledTasks"), "ScheduledTasks") },
      { path: "/pipeline", element: lazyEl(() => import("@/pages/PipelinePage"), "PipelinePage") },  // FE-S206: 流程管线 N8N 风格节点图（9步流程+34 task 状态+子工作流展开+run 日志 Drawer）
      { path: "/architecture", element: lazyEl(() => import("@/pages/ArchitecturePage"), "ArchitecturePage") },  // FE: 项目架构图（archify standalone HTML iframe embed，6 子模块架构图在图谱 quantitative-system/）
      { path: "/health", element: lazyEl(() => import("@/pages/Health"), "HealthPage") },
      { path: "/metrics", element: lazyEl(() => import("@/pages/Metrics"), "Metrics") },
      { path: "/industry", element: lazyEl(() => import("@/pages/Industry"), "Industry") },

      // ─── ~20 redirect 旧路由（S186 Phase 2 保兼容）───
      // daily-review → /market
      { path: "/daily-review", element: redirect("/market") },
      { path: "/daily-review/emotion", element: redirect("/market") },
      { path: "/daily-review/sectors", element: redirect("/market") },
      { path: "/daily-review/review", element: redirect("/market") },
      // 看盘散页 → /market
      { path: "/intel", element: lazyEl(() => import("@/pages/Intel"), "Intel") },  // 审计修: 恢复资讯雷达页（原 redirect /market 致孤儿,MarketPage 链此）
      { path: "/sectors", element: redirect("/market") },
      { path: "/sector-divergence", element: redirect("/market") },
      { path: "/prediction", element: lazyEl(() => import("@/pages/Prediction"), "Prediction") },  // 恢复前瞻页 S017 短线预测工作台（原 redirect /market 致页面孤儿，用户看不到）
      { path: "/debate", element: lazyEl(() => import("@/pages/Debate"), "Debate") },  // 审计修: 恢复多空辩论页（原 redirect /market 致孤儿,AdvisoryPage 链此）
      // 选股散页 → /screener
      { path: "/candidates", element: lazyEl(() => import("@/pages/Candidates"), "Candidates") },  // 恢复候选池主页（漏斗R1/R2+选股池+因子参数ThresholdPanel，69126e2 误删）
      { path: "/value-funnel", element: lazyEl(() => import("@/pages/ValueFunnel"), "ValueFunnel") },  // 恢复选股漏斗页 S005 中长线价值漏斗（原 redirect /screener 致页面孤儿，用户看不到）
      { path: "/limitup/gene", element: redirect("/limitup") },
      { path: "/limitup/auction", element: redirect("/limitup") },
      { path: "/limitup/seats", element: redirect("/limitup") },
      // 复盘散页 → /review
      { path: "/behavior-loop", element: redirect("/review") },
      { path: "/my-reports", element: redirect("/review") },
      { path: "/notes", element: redirect("/review") },
      // 建议散页 → /advisory
      { path: "/recommendation", element: lazyEl(() => import("@/pages/Recommendation")) },  // 恢复建议页（MultiArm+StockRecommendation）；只有 default export，lazyEl 无 name 用 m.default
      // 风险 → /portfolio
      { path: "/risk-dashboard", element: redirect("/risk") },  // 路由修复: →/risk(风险看板独立页 S179) 非 /portfolio(lossy)
      // 策略散页 → /strategy
      { path: "/strategy-signals", element: redirect("/review?tab=strategy") },
      { path: "/backtest", element: redirect("/review?tab=validation") },
      { path: "/verifier-records", element: redirect("/review?tab=validation") },
      { path: "/value-verdict", element: redirect("/multiline") },  // 审计修: VerdictRenderer 在 /multiline 非 /strategy
      // workflow → 新域
      { path: "/workflow", element: redirect("/review") },
      { path: "/workflow/intraday", element: redirect("/intraday") },
      { path: "/workflow/intraday/ofi", element: lazyEl(() => import("@/pages/workflow/OfiDashboardPage")) },  // 保留（OFI 看板独立）
      { path: "/workflow/coach", element: lazyEl(() => import("@/pages/workflow/IntradayCoach")) },  // 盯盘教练全页（Compact 版嵌在 /intraday）
      { path: "/workflow/alerts", element: redirect("/intraday") },
      { path: "/workflow/post-market", element: redirect("/review") },
      { path: "/workflow/topology", element: redirect("/topology") },  // 路由修复: →/topology(独立拓扑页) 非 /review(lossy)
      { path: "/workflow/first-board", element: redirect("/screener") },
      { path: "/workflow/pre-market", element: redirect("/limitup/premarket") },  // 审计修: →盘前选股页(PreMarketBriefing)非 /screener,FactorDetailPage 回链期待
      { path: "/workflow/selection", element: redirect("/screener") },
      { path: "/workflow/candidates/:code", element: lazyEl(() => import("@/pages/workflow/CandidateDetail")) },  // 保留（参数化详情页）
      { path: "/workflow/factor/:factorId", element: lazyEl(() => import("@/pages/workflow/FactorDetailPage"), "FactorDetailPage") },  // 保留
      // 情绪气象子路由 → /sentiment/weather（同组件 4 tab，保留兼容）
      { path: "/sentiment/weather/history", element: redirect("/sentiment/weather") },
      { path: "/sentiment/weather/strategy", element: redirect("/sentiment/weather") },
      { path: "/sentiment/weather/fuse", element: redirect("/sentiment/weather") },
      // strategy 子路由 → /strategy
      { path: "/strategy/funnel/forward-test", element: lazyEl(() => import("@/pages/strategy/ForwardTestPage")) },  // 审计修: 恢复前向测试页(StrategyPage EntryCard 链此,原 redirect /strategy 致孤儿)
      { path: "/strategy/funnel/config", element: lazyEl(() => import("@/pages/strategy/StrategyConfigPage")) },  // 审计修: 恢复战法阈值配置页(StrategyPage EntryCard 链此,原 redirect /strategy 致孤儿)
      // 404 catch-all（路由修复：未知路由不空白，兜底到 NotFound 提示页）
      { path: "*", element: <NotFound /> },
    ],
  },
]);
