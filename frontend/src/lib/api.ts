// Vibe-Research 后端 API 客户端。/api → vite 代理到本地 FastAPI（默认 8900）。
// 后端未启动或数据源异常时抛 ApiError，页面据此优雅降级。

export class ApiError extends Error {
  constructor(message: string, readonly status: number) {
    super(message);
  }
}

// 后端访问密钥（对应后端部署时的 VR_API_KEY，公网部署防蹭用）。只存本地浏览器。
const ACCESS_KEY = "vr-access-key";

export function loadAccessKey(): string {
  try {
    return localStorage.getItem(ACCESS_KEY) || "";
  } catch {
    return "";
  }
}

export function saveAccessKey(key: string) {
  try {
    if (key) localStorage.setItem(ACCESS_KEY, key);
    else localStorage.removeItem(ACCESS_KEY);
  } catch {
    /* 隐私模式等场景 localStorage 不可用 */
  }
}

export function authHeaders(): Record<string, string> {
  const k = loadAccessKey();
  return k ? { Authorization: `Bearer ${k}` } : {};
}

export interface MyReport {
  id: string; name: string; industry: string; size: number; ext: string; ts: number;
}

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

async function request<T>(path: string, method: "GET" | "POST" | "PUT" | "DELETE" = "GET", body?: unknown): Promise<T> {
  let resp: Response;
  const headers: Record<string, string> = { ...authHeaders() };
  const opts: RequestInit = { method };
  if (body !== undefined) {
    headers["Content-Type"] = "application/json";
    opts.body = JSON.stringify(body);
  }
  if (Object.keys(headers).length > 0) opts.headers = headers;
  try {
    resp = await fetch(`/api${path}`, opts);
  } catch {
    throw new ApiError("连接不到后端，请先启动 backend（uvicorn app:app --port 8900）", 0);
  }
  let payload: any = null;
  try {
    payload = await resp.json();
  } catch {
    /* 非 JSON 响应 */
  }
  if (!resp.ok) {
    if (resp.status === 401) {
      throw new ApiError("后端开启了访问鉴权（VR_API_KEY）：请在「接入 AI」页底部填写后端访问密钥", 401);
    }
    throw new ApiError(payload?.detail || `HTTP ${resp.status}`, resp.status);
  }
  return (payload?.data ?? payload) as T;
}

const get = <T>(path: string) => request<T>(path, "GET");

export interface Quote {
  name: string; price: number; last_close: number; change_pct: number;
  pe_ttm: number; pb: number; mcap_yi: number; turnover_pct: number;
  limit_up: number; limit_down: number;
}

export interface Valuation {
  name: string; code: string; price: number; mcap_yi: number;
  pe_ttm: number; pb: number;
  eps_26e: number | null; eps_27e: number | null; pe_26e: number | null;
  cagr_pct: number | null; peg: number | null; digest_years: number | null;
  analyst_count: number; forecast_note?: string;
}

export interface Report {
  title: string; publishDate: string; orgSName: string;
  emRatingName?: string; indvInduName?: string; pdfUrl?: string | null;
}

export interface ValMetric {
  current: number; percentile: number; min: number; max: number;
  p20: number; p50: number; p80: number; n: number;
}
export interface ValPercentile {
  period: string; metrics: { pe_ttm?: ValMetric; pb?: ValMetric };
}

export interface Announcement {
  date: string; title: string; type: string; url: string;
}

export interface Financials {
  period: string | null;
  revenue: string | null; revenue_yoy: string | null;
  net_profit: string | null; net_profit_yoy: string | null;
  eps: string | null; bvps: string | null; roe: string | null;
  gross_margin: string | null; net_margin: string | null; op_cf_ps: string | null;
}

export interface NewsItem {
  新闻标题?: string; 发布时间?: string; 文章来源?: string; 新闻链接?: string;
}

export interface IndexQuote {
  name: string; price: number; change_pct: number; change_amt: number;
}

export interface MarketSentiment {
  up: number; down: number; flat: number; zt: number; zt_real: number; dt: number; dt_real: number;
  active: string; breadth: string; speculation: string; date: string;
}
export interface SectorFlow {
  name: string; pct: number; net: number; inflow: number; outflow: number; firms: number;
}
export interface MarketOverview {
  sentiment: MarketSentiment; sectors: SectorFlow[]; updated: string;
}

// 短线情绪：连板梯队 / 最高连板 / 炸板率 / 封板率 / 晋级率 / 涨跌停家数 + 连板股清单（客观公开榜单）
export interface EmotionTier { boards: number; count: number; plus: boolean }
export interface LianbanStock {
  code: string; name: string; boards: number;
  price: number; pct: number; amount: number | null; float_cap: number | null; industry: string;
}
export interface ShortTermEmotion {
  date: string;
  zt_count: number; dt_count: number; zb_count: number;
  max_boards: number; lianban_count: number;
  ladder: EmotionTier[];
  lianban_stocks: LianbanStock[];
  seal_rate: number | null; break_rate: number | null; promotion_rate: number | null;
  yzt_count: number;
}

// 全市场成交额榜（客观公开榜单）
export interface TurnoverStock {
  code: string; name: string;
  price: number | null; pct: number | null;
  amount: number | null; mcap: number | null; float_cap: number | null; industry: string;
}
export interface TurnoverTop { stocks: TurnoverStock[]; updated: string }

export interface RadarItem {
  title: string; url: string; time: string; source: string; summary?: string; zh?: string;
}
export interface Industry {
  key: string; name: string; accent: string; total: number; items: RadarItem[];
}
export interface RadarData {
  generated_at: string | null; recent_days: number; industries: Industry[];
  stats: { industries: number; total_sources: number; failed_sources?: number };
}

export interface Holding {
  code: string; name: string; price: number; shares: number; cost: number;
  market_value: number; pnl: number; pnl_pct: number;
}
export interface ClosedPosition {
  code: string; name: string; date: string; price: number; shares: number; cost: number;
  pnl: number; pnl_pct: number;
}
export interface PortfolioData {
  holdings: Holding[];
  totals: { market_value: number; cost: number; pnl: number; pnl_pct: number };
  closed: ClosedPosition[];
  realized_pnl: number;
  updated: string; last_refresh: string | null;
}

// 资金面 / 筹码 / 信号（v3.3 并入，均为「用户查的那只股」的公开数据）
export interface MarginRow { date: string; rzye: number; rzmre: number; rzche: number; rqye: number; rqmcl: number; rzrqye: number }
export interface BlockTradeRow { date: string; price: number; close: number; premium_pct: number; vol: number; amount: number; buyer: string; seller: string }
export interface HolderRow { date: string; holder_num: number; change_ratio: number; avg_shares: number }
export interface DividendRow { date: string; bonus_rmb: number; transfer_ratio: number; bonus_ratio: number | null; plan: string }
export interface FundFlowRow { date: string; main_net: number; small_net: number; mid_net: number; large_net: number; super_net: number }
export interface DtSeat { name: string; buy_amt: number; sell_amt: number; net: number }
export interface DragonTiger {
  records: { date: string; reason: string; net_buy: number; turnover: number }[];
  seats: { buy: DtSeat[]; sell: DtSeat[] };
  institution: { buy_amt: number; sell_amt: number; net_amt: number };
}
export interface LockupRow { date: string; type: string; shares: number; able_shares: number; ratio: number }
export interface Lockup { history: LockupRow[]; upcoming: LockupRow[] }
export interface Board { name: string; code: string; change_pct: number | string; lead_stock: string }
export interface Blocks { total: number; boards: Board[]; concept_tags: string[] }
export interface HotConcept { concept: string; bk: string; hit: number }
export interface QaRow { company: string; question: string; answer: string | null; answerer: string; ask_time: string }
export interface IndustryRow { rank: number; name: string; change_pct: number; code: string; up_count: number; down_count: number }
export interface IndustryData { top: IndustryRow[]; bottom: IndustryRow[]; total: number }

// 全球市场（美股 / 港股，移植自 global-stock-data · 东财域内源）
export interface GlobalIndex {
  key: string; name: string; region: string;
  price: number | null; change_pct: number | null;
}
export interface GlobalQuote {
  code: string; name: string;
  price: number | null; open: number | null; high: number | null; low: number | null;
  prev_close: number | null; amount: number | null; mcap: number | null; change_pct: number | null;
}
export interface GlobalMetrics {
  report_date: string;
  revenue: number | null; revenue_yoy: number | null; net_profit: number | null;
  eps: number | null; roe: number | null; gross_margin: number | null;
  net_margin: number | null; debt_ratio: number | null;
}
export interface GlobalStock {
  code: string; name: string; market: string;
  quote: GlobalQuote; metrics: GlobalMetrics | null;
}

// STI 情绪温度
export interface STIDimension {
  limit_up_count: number;
  limit_down_count: number;
  seal_rate: number;
  advance_decline_ratio: number;
  promotion_rate: number;
  prev_zt_performance: number;
  max_boards: number;
  market_factor: number;
}

export interface STIResult {
  date: string;
  score: number | null;
  phase: "高潮" | "启动" | "分歧" | "冰点" | "退潮" | null;
  dimensions: STIDimension | null;
  source_ok: boolean;
  confidence: string;
  change_from_yesterday: number | null;
  data_updated: string | null;
  phase_explanation: string | null;
  disclaimer: string;
  data_freshness: "fresh" | "stale" | "expired";
  data_age_seconds: number;
}

export interface STITimelineItem {
  date: string;
  score: number | null;
  phase: string | null;
  change_from_yesterday: number | null;
}

// Sentiment Weather Station types
export interface WeatherFactor {
  id: string;
  name: string;
  score: number | null;
  weight: number;
  trend: "up" | "down" | "stable";
  explanation: string;
}

export interface WeatherState {
  weather_state: "暴风雨" | "阴天" | "晴天" | "极端反弹" | "未知";
  weather_icon: string;
  composite_score: number;
  confidence: string;
  sti_score: number | null;
  sti_phase: string | null;
  sti_date: string | null;
  sti_change: number | null;
  factors: Record<string, { score: number | null; weight: number; name: string }>;
  data_updated: string | null;
  data_freshness?: {
    is_stale: boolean;
    delay_ms: number;
    last_trigger_count: number;
  };
  execution_params?: {
    channel_latency_ms: number;
    slippage_compensation: number;
    settlement_buy_price: number;
    next_day_sell_base: number;
    t1_locked: boolean;
  };
}

export interface StrategyMatch {
  style: string;
  match_score: number;
  enabled: boolean;
  description: string;
  conditions: string[];
  order_config: string;
  execution_params?: {
    channel_latency_ms: number;
    slippage_compensation: number;
    settlement_buy_price: number;
    next_day_sell_base: number;
    t1_locked: boolean;
  };
}

export interface StrategyRecommendation {
  weather_state: string;
  strategies: StrategyMatch[];
  driver: string;
  risk_note: string;
}

export interface FuseRule {
  id: string;
  name: string;
  status: "enabled" | "disabled";
  trigger_condition: string;
  current_state: string;
  description: string;
  last_triggered?: string;
  is_pardoned?: boolean;
  pardon_expires_at?: string;
  pardon_enabled_by?: string;
}

export interface WeatherTimelineItem {
  date: string;
  sti_score: number | null;
  weather_state: string;
  composite_score: number;
  phase: string | null;
  change_from_yesterday: number | null;
}

export interface WeatherStats {
  total: number;
  晴天: number;
  阴天: number;
  暴风雨: number;
  极端反弹: number;
}

export interface WeatherEvent {
  date: string;
  title: string;
  description: string;
  impact: "positive" | "negative" | "neutral";
}

// Sentiment Weather Station V2.0.3 types
export interface DataFreshness {
  is_stale: boolean;
  delay_ms: number;
  last_trigger_count: number;
}

export interface ExecutionParams {
  channel_latency_ms: number;
  slippage_compensation: number;
  settlement_buy_price: number;
  next_day_sell_base: number;
  t1_locked: boolean;
}

export interface AuctionMetric {
  name: string;
  value: number;
  unit: string;
  phase: "pre_competitive" | "competitive";
  threshold_high: number;
  threshold_low: number;
  is_warning: boolean;
}

export interface SealRiskMetric {
  stock_code: string;
  seal_amount: number;
  float_shares: number;
  seal_ratio: number;
  min_ratio_required: number;
  risk_level: "low" | "medium" | "high";
  cap_category: string;
  enforcement_action: string;
  reason: string;
}

export interface FusePardonRecord {
  id: string;
  strategy_code: string;
  strategy_name: string;
  enabled_by: string;
  enabled_ip: string;
  approved_by: string;
  max_position_pct: number;
  created_at: string;
  expires_at: string;
  reason: string;
  is_active: boolean;
  revoked_at?: string;
  revoked_by?: string;
  outcome?: {
    stock_code: string;
    entry_price: number;
    exit_price: number;
    return_pct: number;
    was_successful: boolean;
    lessons_learned: string;
  };
}

export interface PardonOutcome {
  pardon_id: string;
  stock_code: string;
  entry_price: number;
  exit_price: number;
  return_pct: number;
  was_successful: boolean;
  lessons_learned: string;
}

export interface GeneScore {
  code: string;
  name: string;
  total_score: number;        // 0-100
  factors: Record<string, number>;  // 五维因子
  wilson_adjusted: number;
  qualify: boolean;
  high_gene: boolean;
  last_zt_dates: string[];
  zt_count_250d: number;
  backtest_points: Array<{ date: string; gene_score: number; actual_next_day: number }>;
  backtest_summary: { samples: number; lianban_rate: number; avg_score_lianban: number | null };
}

export interface StrategyLogicMatch {
  code: string;
  name: string;
  matches: Array<{
    condition: string;    // 条件名称（如"高封单比"）
    value: string;        // 条件值（如"封单比 0.15"）
    description: string;  // 策略逻辑说明
  }>;
  logic_description: string;
  disclaimer: string;
}

export interface RiskRuleKnowledge {
  rule_name: string;
  description: string;
  default_value: string;
  configurable: boolean;
  example: string;
}

export interface LimitUpAnalysis {
  code: string;
  name: string;
  date: string;
  gene_score: GeneScore;
  strategy_logic: StrategyLogicMatch;
  risk: {
    code: string;
    date: string;
    risk_score: number;
    risk_level: string;
    score_components: Record<string, any>;
    capital_flow_signal: number;
    capital_flow_trend: string;
    big_fund_detected: boolean;
    big_fund_type: string;
    fund_flow_history: Array<Record<string, any>>;
    dragon_tiger_risk: number;
    one_day_seats: string[];
    multi_seat_signal: boolean;
    seat_confidence: number;
    recommendation: string;
    factors: string[];
    last_updated: string;
    dynamic_thresholds: Record<string, any>;
    risk_factors: string[];
    max_drawdown: number;
    volatility: number;
    liquidity_risk: number;
    concentration_risk: number;
  } | null;
  risk_rules: RiskRuleKnowledge[];
  backtest_points: Array<{ date: string; gene_score: number; actual_next_day: number }>;
  disclaimer: string;
  seal_amount: number;
  float_shares: number;
  seal_to_float_ratio: number;
  limit_up_price: number;
  limit_down_price: number;
}

export interface KlineBar {
  date: string; open: number; high: number; low: number; close: number; volume: number; amount: number;
}

export interface StockDeep {
  quote: Quote | null;
  kline: KlineBar[] | null;
  valuation: Valuation | null;
  percentile: ValPercentile | null;
  fund_flow: FundFlowRow[] | null;
  dragon_tiger: DragonTiger | null;
  limitup: LimitUpAnalysis | null;
  financials: Financials | null;
  blocks: Blocks | null;
  hot_concepts: HotConcept[] | null;
  announcements: Announcement[] | null;
  reports: Report[] | null;
}

export interface ScreenerResult {
  date: string;
  gene_scores: GeneScore[];
  qualified: GeneScore[];
  high_gene: GeneScore[];
  updated: string;
  disclaimer: string;
  data_freshness: "fresh" | "stale" | "expired";
  data_age_seconds: number;
}

export interface BacktestPoint {
  date: string;
  gene_score: number;
  actual_next_day: number;
  seal_rate: number;
  premium_rate: number;
}

// ---- 推荐引擎 ----
export type RecommendationLevel = "高质量关注" | "中等质量关注" | "低质量关注" | "策略逻辑上回避";

export interface StockRecommendation {
  code: string;
  name: string;
  gene_score: number;
  industry_normalized: number;
  level: RecommendationLevel;
  position_suggestion: string;
  reasoning: string[];
  risk_notes: string[];
  factor_breakdown: Record<string, number>;
}

// ---- 胜率统计 ----
export interface WinRateStats {
  window_size: number;
  total_trades: number;
  win_count: number;
  win_rate: number;
  avg_return: number;
  max_drawdown: number;
  sharpe_ratio: number;
  trend: string;
  sector_breakdown: Record<string, any>;
  strategy_breakdown: Record<string, any>;
  score_breakdown: Record<string, any>;
}

// ---- 竞价信号 ----
export interface AuctionSignal {
  code: string;
  name: string;
  signal_type: string;
  confidence: number;
  open_premium: number;
  volume_ratio: number;
  reasoning: string[];
}

// ---- 回测结果 ----
export interface BacktestResult {
  period: string;
  total_signals: number;
  hit_count: number;
  hit_rate: number;
  avg_return: number;
  max_drawdown: number;
  sharpe_ratio: number;
  percentile_analysis: Record<string, any>;
}

// ---- 打板策略参数配置 ----
export interface LimitUpParams {
  gene_qualify_threshold: number;
  gene_high_threshold: number;
  lookback_days: number;
}

// ---- 竞价选股参数配置 ----
export interface AuctionParams {
  min_gene_score: number;
  min_zt_count: number;
  top_n: number;
}

// ---- 复盘报告参数配置 ----
export interface ReviewParams {
  max_zt_stocks: number;
  auction_top_n: number;
}

// ---- 每日复盘报告 ----
export interface ZTStockSummary {
  code: string;
  name: string;
  lbc: number;
  fbt: number;
  seal_rate: number;
  zbc: number;
}

export interface SectorHeatItem {
  sector: string;
  zt_count: number;
  total_count: number;
  zt_rate: number;
  avg_change: number;
}

export interface DailyReviewReport {
  date: string;
  sti_score: number | null;
  sti_phase: string | null;
  sti_change: number | null;
  zt_total: number;
  dt_total: number;
  zb_total: number;
  advance_count: number;
  decline_count: number;
  sector_heat: SectorHeatItem[];
  zt_stocks: ZTStockSummary[];
  prev_zt_stats: Record<string, number>;
  auction_top: Record<string, unknown>[];
  updated: string;
  disclaimer: string;
}

// ---- 竞价选股结果 ----
export interface AuctionCandidate {
  code: string;
  name: string;
  score: number;
  gene_score: number;
  zt_count_30d: number;
  seal_rate: number;
  avg_fbt: number;
  promotion_rate: number;
  prev_zt_return: number;
  max_boards: number;
  strategy_tags: string[];
  signal_strength: number;
  confidence: string;
  seal_amount: number;
  float_shares: number;
  seal_to_float_ratio: number;
}

export interface AuctionScreenerResult {
  date: string;
  candidates: AuctionCandidate[];
  sti_score: number | null;
  sti_phase: string | null;
  total_analyzed: number;
  updated: string;
  disclaimer: string;
}

// ---- 席位引擎 ----
export interface SeatProfile {
  seat_name: string;
  total_appearances: number;
  total_buy_amt: number;
  total_sell_amt: number;
  net_amt: number;
  avg_buy_amt: number;
  avg_sell_amt: number;
  stock_cooldown: number;
  last_seen: string;
  seat_type: string;  // "机构专用" | "量化席位" | "活跃游资" | "跟风席位" | "inactive"
}

export interface ConsensusSignal {
  signal: string | null;  // "多资金共识" | "分歧信号" | "机构主导" | "游资主导" | null
  details: Record<string, unknown>;
  date: string;
  stock_code: string;
  disclaimer: string;
}

export interface LlmEnvStatus {
  has_env_base_url: boolean;
  has_env_api_key: boolean;
  has_env_model: boolean;
}

export interface ScheduledTask {
  id: number;
  name: string;
  description: string;
  task_type: string;
  cron_expr: string;
  payload: Record<string, any>;
  enabled: boolean;
  notify_on_success: boolean;
  notify_on_failure: boolean;
  last_run_at: string | null;
  last_run_status: string | null;
  created_at: string;
  updated_at: string;
}

export interface TaskRun {
  id: number;
  task_id: number;
  status: string;
  started_at: string;
  finished_at: string | null;
  result: Record<string, any>;
  error: string | null;
}

export async function getScheduledTasks(): Promise<ScheduledTask[]> {
  const res = await fetch("/api/scheduled-tasks", { headers: authHeaders() });
  if (!res.ok) throw new ApiError(`Failed to get scheduled tasks: ${res.statusText}`, res.status);
  const payload = await res.json();
  return (payload?.data ?? payload) as ScheduledTask[];
}

export async function getScheduledTask(id: number): Promise<ScheduledTask> {
  const res = await fetch(`/api/scheduled-tasks/${id}`, { headers: authHeaders() });
  if (!res.ok) throw new ApiError(`Failed to get scheduled task: ${res.statusText}`, res.status);
  const payload = await res.json();
  return (payload?.data ?? payload) as ScheduledTask;
}

export async function createScheduledTask(data: Partial<ScheduledTask>): Promise<{ id: number }> {
  const res = await fetch("/api/scheduled-tasks", {
    method: "POST",
    headers: { ...authHeaders(), "Content-Type": "application/json" },
    body: JSON.stringify(data),
  });
  if (!res.ok) throw new ApiError(`Failed to create scheduled task: ${res.statusText}`, res.status);
  const payload = await res.json();
  return payload as { id: number };
}

export async function updateScheduledTask(id: number, data: Partial<ScheduledTask>): Promise<void> {
  const res = await fetch(`/api/scheduled-tasks/${id}`, {
    method: "PUT",
    headers: { ...authHeaders(), "Content-Type": "application/json" },
    body: JSON.stringify(data),
  });
  if (!res.ok) throw new ApiError(`Failed to update scheduled task: ${res.statusText}`, res.status);
}

export async function deleteScheduledTask(id: number): Promise<void> {
  const res = await fetch(`/api/scheduled-tasks/${id}`, {
    method: "DELETE",
    headers: authHeaders(),
  });
  if (!res.ok) throw new ApiError(`Failed to delete scheduled task: ${res.statusText}`, res.status);
}

export async function runScheduledTaskNow(id: number): Promise<any> {
  const res = await fetch(`/api/scheduled-tasks/${id}/run`, {
    method: "POST",
    headers: authHeaders(),
  });
  if (!res.ok) throw new ApiError(`Failed to run scheduled task: ${res.statusText}`, res.status);
  return res.json();
}

export async function getScheduledTaskRuns(id: number, limit = 50): Promise<TaskRun[]> {
  const res = await fetch(`/api/scheduled-tasks/${id}/runs?limit=${limit}`, { headers: authHeaders() });
  if (!res.ok) throw new ApiError(`Failed to get task runs: ${res.statusText}`, res.status);
  const payload = await res.json();
  return (payload?.data ?? payload) as TaskRun[];
}

export async function getScheduledTaskTypes(): Promise<string[]> {
  const res = await fetch("/api/scheduled-tasks/types", { headers: authHeaders() });
  if (!res.ok) throw new ApiError(`Failed to get task types: ${res.statusText}`, res.status);
  const payload = await res.json();
  return (payload?.data ?? payload) as string[];
}

export async function getLlmEnvStatus(): Promise<LlmEnvStatus> {
  const res = await fetch(`/api/settings/llm-env-status`, { headers: authHeaders() });
  if (!res.ok) throw new ApiError(`Failed to get LLM env status: ${res.statusText}`, res.status);
  return res.json();
}

export async function getLimitUpScreenerParams(): Promise<LimitUpParams> {
  const res = await fetch(`/api/limitup/screener/params`, { headers: authHeaders() });
  if (!res.ok) throw new ApiError(`Failed to get params: ${res.statusText}`, res.status);
  return res.json();
}

export async function saveLimitUpScreenerParams(params: LimitUpParams): Promise<void> {
  const res = await fetch(`/api/limitup/screener/params`, {
    method: "POST",
    headers: { ...authHeaders(), "Content-Type": "application/json" },
    body: JSON.stringify(params),
  });
  if (!res.ok) throw new ApiError(`Failed to save params: ${res.statusText}`, res.status);
}

export async function getAuctionParams(): Promise<AuctionParams> {
  const res = await fetch(`/api/limitup/auction/params`, { headers: authHeaders() });
  if (!res.ok) throw new ApiError(`Failed to get auction params: ${res.statusText}`, res.status);
  return res.json();
}

export async function saveAuctionParams(params: AuctionParams): Promise<void> {
  const res = await fetch(`/api/limitup/auction/params`, {
    method: "POST",
    headers: { ...authHeaders(), "Content-Type": "application/json" },
    body: JSON.stringify(params),
  });
  if (!res.ok) throw new ApiError(`Failed to save auction params: ${res.statusText}`, res.status);
}

export async function getReviewParams(): Promise<ReviewParams> {
  const res = await fetch(`/api/review/params`, { headers: authHeaders() });
  if (!res.ok) throw new ApiError(`Failed to get review params: ${res.statusText}`, res.status);
  return res.json();
}

export async function saveReviewParams(params: ReviewParams): Promise<void> {
  const res = await fetch(`/api/review/params`, {
    method: "POST",
    headers: { ...authHeaders(), "Content-Type": "application/json" },
    body: JSON.stringify(params),
  });
  if (!res.ok) throw new ApiError(`Failed to save review params: ${res.statusText}`, res.status);
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
    get<any>(`/winrate/adjustments${windowSize ? `?window_size=${windowSize}` : ""}`),
  winRateTrends: (windowSize?: number) =>
    get<any[]>(`/winrate/trends${windowSize ? `?window_size=${windowSize}` : ""}`),
  winRateSector: (sector: string, windowSize?: number) =>
    get<any>(`/winrate/sector/${encodeURIComponent(sector)}${windowSize ? `?window_size=${windowSize}` : ""}`),
  winRateStrategy: (strategy: string, windowSize?: number) =>
    get<any>(`/winrate/strategy/${encodeURIComponent(strategy)}${windowSize ? `?window_size=${windowSize}` : ""}`),
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
    get<any[]>(`/backtest/scatter?start=${start}&end=${end}`),
  backtestResult: (start: string, end: string) =>
    get<BacktestResult>(`/backtest/result?start=${start}&end=${end}`),
  // 风险仪表盘
  riskDashboard: (date?: string) =>
    get<any>(`/risk/dashboard${date ? `?date=${date}` : ""}`),
  riskStock: (code: string) =>
    get<any>(`/risk/stock/${code}`),
  riskOnedayList: (date?: string, minRiskScore?: number) =>
    get<any>(`/risk/oneday/list${date ? `?date=${date}` : ""}${minRiskScore !== undefined ? `&min_risk_score=${minRiskScore}` : ""}`),
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
};
