// Vibe-Research 后端 API 客户端 barrel。/api → vite 代理到本地 FastAPI（默认 8900）。
// S013 T6：按域拆分——types(10-866)/scheduled(868-913)/workflow(915-944) 移至 lib/api/，
// 本文件留 client re-export + downloadReport + api 端点对象。import 路径 @/lib/api 不变（零行为变更）。
import { ApiError, authHeaders, request, get } from "./api/client";
import type {
  IndexQuote, MarketOverview, ShortTermEmotion, TurnoverTop, GlobalIndex, GlobalStock,
  RadarData, PortfolioData, Valuation, ValPercentile, Financials, Announcement, Quote,
  Report, NewsItem, MarginRow, BlockTradeRow, HolderRow, DividendRow, FundFlowRow,
  DragonTiger, Lockup, Blocks, HotConcept, QaRow, IndustryData, MyReport, ScreenerResult,
  LimitUpAnalysis, AuctionScreenerResult, DailyReviewReport, SeatProfile, ConsensusSignal,
  StockDeep, StrategyRecommendation, WeatherState, WeatherFactor, FuseRule, WeatherTimelineItem,
  WeatherStats, WeatherEvent, AuctionMetric, SealRiskMetric, FusePardonRecord, PardonOutcome,
  StockRecommendation, WinRateStats, WinRateRecordInput, WinRateRecordsResponse, WinRateTrendPoint,
  WinRateAdjustment, SectorWinStats, StrategyWinStats, AuctionSignal, BacktestResult, BacktestScatterPoint,
  BacktestSnapshotRow, STIResult, STITimelineItem,
  FunnelLayer,
  BoardLadderNode,
  GraphData,
} from "./api/types";
import {
  getLimitUpScreenerParams, saveLimitUpScreenerParams, getAuctionParams, saveAuctionParams,
  getReviewParams, saveReviewParams, getLlmEnvStatus,
} from "./api/scheduled";

export { ApiError, loadAccessKey, saveAccessKey, authHeaders } from "./api/client";
export * from "./api/types";
export * from "./api/scheduled";
export * from "./api/workflow";

// 下载/预览研报：带鉴权头 fetch → blob → 触发浏览器下载（<a download> 无法带 Authorization，故走 blob）。
export async function downloadReport(id: string, name: string): Promise<void> {
  const resp = await fetch(`/api/myreports/file/${id}`, { headers: authHeaders() });
  if (!resp.ok) throw new ApiError(`下载失败 HTTP ${resp.status}`, resp.status);
  const blob = await resp.blob();
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = name;
  document.body.appendChild(a);
  a.click();
  a.remove();
  URL.revokeObjectURL(url);
}

export const api = {
  health: () => get<{ ok: boolean }>("/health"),
  indices: () => get<IndexQuote[]>("/indices"),
  marketOverview: () => get<MarketOverview>("/market/overview"),
  emotion: () => get<ShortTermEmotion>("/market/emotion"),
  turnoverTop: () => get<TurnoverTop>("/market/turnover-top"),
  globalIndices: () => get<GlobalIndex[]>("/global/indices"),
  globalStock: (symbol: string) => get<GlobalStock>(`/global/stock?symbol=${encodeURIComponent(symbol)}`),
  radar: () => get<RadarData>("/radar"),
  radarRefresh: () => request<RadarData>("/radar/refresh", "POST"),
  portfolio: () => get<PortfolioData>("/portfolio"),
  addHolding: (code: string, shares: number, cost: number) => request<PortfolioData>("/portfolio/holding", "POST", { code, shares, cost }),
  removeHolding: (code: string) => request<PortfolioData>(`/portfolio/holding?code=${code}`, "DELETE"),
  refreshPortfolio: () => request<PortfolioData>("/portfolio/refresh", "POST"),
  closePosition: (code: string, date: string, price: number, shares: number, cost: number) =>
    request<PortfolioData>("/portfolio/close", "POST", { code, date, price, shares, cost }),
  removeClosed: (index: number) => request<PortfolioData>(`/portfolio/close?index=${index}`, "DELETE"),
  valuation: (code: string) => get<Valuation>(`/valuation?code=${code}`),
  percentile: (code: string) => get<ValPercentile>(`/valuation/percentile?code=${code}`),
  financials: (code: string) => get<Financials>(`/financials?code=${code}`),
  announcements: (code: string) => get<Announcement[]>(`/announcements?code=${code}`),
  quote: (codes: string) => get<Record<string, Quote>>(`/quote?codes=${codes}`),
  reports: (code: string) => get<Report[]>(`/reports?code=${code}`),
  news: (code: string) => get<NewsItem[]>(`/news?code=${code}`),
  margin: (code: string) => get<MarginRow[]>(`/margin?code=${code}`),
  blockTrade: (code: string) => get<BlockTradeRow[]>(`/block-trade?code=${code}`),
  holders: (code: string) => get<HolderRow[]>(`/holders?code=${code}`),
  dividend: (code: string) => get<DividendRow[]>(`/dividend?code=${code}`),
  fundFlow: (code: string) => get<FundFlowRow[]>(`/fund-flow?code=${code}`),
  dragonTiger: (code: string) => get<DragonTiger>(`/dragon-tiger?code=${code}`),
  lockup: (code: string) => get<Lockup>(`/lockup?code=${code}`),
  blocks: (code: string) => get<Blocks>(`/blocks?code=${code}`),
  hotConcepts: (code: string) => get<HotConcept[]>(`/hot-concepts?code=${code}`),
  investorQa: (code: string) => get<QaRow[]>(`/investor-qa?code=${code}`),
  industry: (top = 20) => get<IndustryData>(`/industry?top=${top}`),
  myReports: () => get<MyReport[]>("/myreports"),
  uploadReport: (name: string, contentB64: string) =>
    request<MyReport>("/myreports", "POST", { name, content_b64: contentB64 }),
  deleteReport: (id: string) => request<{ ok: boolean }>(`/myreports/${id}`, "DELETE"),
  // 打板策略
  limitupScreener: (date?: string) =>
    get<ScreenerResult>(`/limitup/screener${date ? `?date=${date}` : ""}`),
  limitupAnalysis: (code: string, date?: string) =>
    get<LimitUpAnalysis>(`/limitup/analysis/${code}${date ? `?date=${date}` : ""}`),
  triggerLimitupScreener: () =>
    request<{ status: string; date: string }>("/limitup/screener/trigger", "POST"),
  getLimitUpScreenerParams,
  saveLimitUpScreenerParams,
  getAuctionParams,
  saveAuctionParams,
  getReviewParams,
  saveReviewParams,
  getLlmEnvStatus,
  // 竞价选股 TOP N
  auctionTop: (date?: string, n?: number) =>
    get<AuctionScreenerResult>(`/limitup/auction/top${date ? `?date=${date}` : ""}${n ? `&n=${n}` : ""}`),
  // 每日复盘报告
  dailyReview: (date?: string) =>
    get<DailyReviewReport>(`/review/daily${date ? `?date=${date}` : ""}`),
  // 席位引擎
  seatProfiles: () => get<{profiles: SeatProfile[]; total: number}>("/limitup/seats/profiles"),
  seatProfile: (name: string) => get<SeatProfile>(`/limitup/seats/profile/${encodeURIComponent(name)}`),
  seatConsensus: (stockCode: string, date?: string) =>
    get<ConsensusSignal>(`/limitup/seats/consensus?stock_code=${stockCode}${date ? `&trade_date=${date}` : ""}`),
  seatBuildProfiles: (lookbackDays?: number) =>
    request<{ status: string; profiles: number }>("/limitup/seats/build", "POST", lookbackDays ? { lookback_days: lookbackDays } : {}),
  // STI 情绪温度
  stiLatest: (date?: string) =>
    get<STIResult>(`/market/sti/latest${date ? `?date=${date}` : ""}`),
  stiTimeline: (days = 30) =>
    get<STITimelineItem[]>(`/market/sti/timeline?days=${days}`),
  // 情绪气象站
  sentimentWeatherLatest: () =>
    get<WeatherState>("/sentiment/weather/latest"),
  sentimentWeatherFactors: () =>
    get<{ data: { weather_state: string; composite_score: number; factors: WeatherFactor[] } }>("/sentiment/weather/factors"),
  sentimentWeatherStrategy: () =>
    get<StrategyRecommendation>("/sentiment/weather/strategy"),
  sentimentWeatherFuse: () =>
    get<{ data: { rules: FuseRule[]; updated_at: string } }>("/sentiment/weather/fuse"),
  sentimentWeatherTimeline: (days = 30) =>
    get<{ data: { timeline: WeatherTimelineItem[]; stats: WeatherStats } }>(`/sentiment/weather/timeline?days=${days}`),
  sentimentWeatherEvents: (days = 30) =>
    get<{ data: { events: WeatherEvent[] } }>(`/sentiment/weather/events?days=${days}`),
  sentimentWeatherAuction: () =>
    get<{ data: { auction_metrics: AuctionMetric[]; phase: string } }>("/sentiment/weather/auction"),
  sentimentWeatherSealRisk: () =>
    get<{ data: { seal_risk_metrics: SealRiskMetric[] } }>("/sentiment/weather/seal-risk"),
  sentimentWeatherPardon: () =>
    get<{ data: { pardon_records: FusePardonRecord[]; is_admin: boolean } }>("/sentiment/weather/pardon"),
  sentimentWeatherPardonToggle: (data: { strategy_code: string; reason: string; max_position_pct?: number }) =>
    request<{ data: FusePardonRecord }>("/sentiment/weather/pardon/toggle", "POST", data),
  sentimentWeatherPardonRevoke: (pardonId: string) =>
    request<{ data: { success: boolean } }>(`/sentiment/weather/pardon/revoke?pardon_id=${pardonId}`, "POST"),
  sentimentWeatherPardonOutcome: (data: PardonOutcome) =>
    request<{ data: { success: boolean } }>("/sentiment/weather/pardon/outcome", "POST", data),
  stockDeep: (code: string) => get<StockDeep>(`/stock/${code}/deep`),
  // 性能监控（PRD V2.0.2 三层拆分）
  metricsDataFetch: () => get<any>("/metrics/data_fetch"),
  metricsCompute: () => get<any>("/metrics/compute"),
  metricsApiResponse: () => get<any>("/metrics/api_response"),
  metricsBreakdown: () => get<any>("/metrics/breakdown"),
  // 推荐引擎
  recommendationToday: (limit?: number) =>
    get<StockRecommendation[]>(`/recommendation/today${limit ? `?limit=${limit}` : ""}`),
  recommendationStock: (code: string, date?: string) =>
    get<StockRecommendation>(`/recommendation/${code}${date ? `?date=${date}` : ""}`),
  // 胜率追踪
  winRateStats: (windowSize?: number) =>
    get<WinRateStats>(`/winrate/stats${windowSize ? `?window_size=${windowSize}` : ""}`),
  winRateAdjustments: (windowSize?: number) =>
    get<WinRateAdjustment[]>(`/winrate/adjustments${windowSize ? `?window_size=${windowSize}` : ""}`),
  winRateTrends: (windowSize?: number) =>
    get<WinRateTrendPoint[]>(`/winrate/trends${windowSize ? `?window_size=${windowSize}` : ""}`),
  winRateSector: (sector: string, windowSize?: number) =>
    get<SectorWinStats>(`/winrate/sector/${encodeURIComponent(sector)}${windowSize ? `?window_size=${windowSize}` : ""}`),
  winRateStrategy: (strategy: string, windowSize?: number) =>
    get<StrategyWinStats>(`/winrate/strategy/${encodeURIComponent(strategy)}${windowSize ? `?window_size=${windowSize}` : ""}`),
  // S025-A2：录入交易记录（批量）。后端 POST /api/winrate/records 接 List[Dict]，返 {data:{added,...}}，
  // request() 自动解包 .data，故泛型为内层 WinRateRecordsResponse。
  winRateRecords: (records: WinRateRecordInput[]) =>
    request<WinRateRecordsResponse>("/winrate/records", "POST", records),
  // 竞价监控
  auctionMonitor: () => get<AuctionSignal[]>("/auction/monitor"),
  auctionWatchlist: () => get<string[]>("/auction/watchlist"),
  // 战法信号
  strategySignals: (code: string, date?: string) =>
    get<any[]>(`/strategy/signals/${code}${date ? `?date=${date}` : ""}`),
  strategyRegistry: () =>
    get<any[]>("/strategy/registry"),
  // 回测
  backtestScatter: (start: string, end: string) =>
    get<BacktestScatterPoint[]>(`/backtest/scatter?start=${start}&end=${end}`),
  backtestResult: (start: string, end: string) =>
    get<BacktestResult>(`/backtest/result?start=${start}&end=${end}`),
  // S041 趋势看板：daily_backtest_run 落库快照的时间序列。days 默认 90。
  backtestTrend: (days?: number) =>
    get<BacktestSnapshotRow[]>(`/backtest/trend?days=${days ?? 90}`),
  // 风险仪表盘
  riskDashboard: (date?: string) =>
    get<any>(`/risk/dashboard${date ? `?date=${date}` : ""}`),
  riskStock: (code: string) =>
    get<any>(`/risk/stock/${code}`),
  riskOnedayList: (date?: string, minRiskScore?: number) => {
    const params = new URLSearchParams();
    if (date) params.set("date", date);
    if (minRiskScore !== undefined) params.set("min_risk_score", String(minRiskScore));
    const qs = params.toString();
    return get<any>(`/risk/oneday/list${qs ? `?${qs}` : ""}`);
  },
  riskSeats: () =>
    get<any>("/risk/seats"),
  // 板块分化度
  sectorDivergence: (date?: string) =>
    get<any>(`/sector/divergence${date ? `?date=${date}` : ""}`),
  sectorRotation: (date?: string) =>
    get<any>(`/sector/rotation${date ? `?date=${date}` : ""}`),
  sectorDivergenceHistory: (days?: number) =>
    get<any[]>(`/sector/divergence/history${days ? `?days=${days}` : ""}`),
  // 定时任务
  scheduledTasks: () => get<any[]>("/scheduled-tasks"),
  scheduledTask: (id: number) => get<any>(`/scheduled-tasks/${id}`),
  createScheduledTask: (data: any) => request<any>("/scheduled-tasks", "POST", data),
  updateScheduledTask: (id: number, data: any) => request<any>(`/scheduled-tasks/${id}`, "PUT", data),
  deleteScheduledTask: (id: number) => request<{ ok: boolean }>(`/scheduled-tasks/${id}`, "DELETE"),
  runScheduledTaskNow: (id: number) => request<any>(`/scheduled-tasks/${id}/run`, "POST"),
  scheduledTaskRuns: (id: number, limit?: number) =>
    get<any[]>(`/scheduled-tasks/${id}/runs${limit ? `?limit=${limit}` : ""}`),
  scheduledTaskTypes: () => get<string[]>("/scheduled-tasks/types"),
  // S024-B7 拓扑关系网：候选标的四类客观关联边（sector/fund_flow/ladder/seat）。
  // 后端 GET /api/topology/relation 返 {nodes,edges}（无方向结论，§0 弱合规·工程底线）。
  // S024-C review #3：API 层直接返 GraphData（共享契约），消除 query 层 as cast。
  topologyRelation: (date?: string) =>
    get<GraphData>(`/topology/relation${date ? `?date=${date}` : ""}`),
  // S024-C1 漏斗流程拓扑：复用 S023 funnel/layers，返 FunnelLayer[]（含 conditions/passed）。
  // 后端 GET /api/workflow/funnel/layers（run_id 可选，此处不传；客观层数据流向）。
  funnelLayers: (date?: string) =>
    get<FunnelLayer[]>(`/workflow/funnel/layers${date ? `?date=${date}` : ""}`),
  // S024-D2 连板梯队树：em_zt_topic_pool 涨停池，按连板高度分层，同题材归枝。
  // 后端 GET /api/topology/board-ladder 返嵌套树（root→height→industry→stock 叶），
  // 叶节点如实呈现 code/name（公开榜单客观事实，§0 弱合规·工程底线）。
  boardLadder: (date?: string) =>
    get<BoardLadderNode>(`/topology/board-ladder${date ? `?date=${date}` : ""}`),
};
