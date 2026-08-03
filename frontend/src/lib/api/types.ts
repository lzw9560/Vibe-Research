// S013 T6: 接口/类型集中于此（从 api.ts 拆出，排除 downloadReport）。纯类型，无运行时导入。

export interface MyReport {
  id: string; name: string; industry: string; size: number; ext: string; ts: number;
}


// request<T> / get 已提取到 lib/api/client.ts（S013 T1），上方 import。


// S008 T1：/api/quote 返 S007 Quote 模型。字段名按模型契约：
// turnover_pct→turnover_rate、limit_up→limit_up_price、limit_down→limit_down_price、last_close 保留。
// mcap_yi 不在 Quote 序列化字段（展示用 Valuation.mcap_yi）。
export interface Quote {
  name: string; price: number; last_close: number; change_pct: number;
  pe_ttm: number; pb: number; turnover_rate: number;
  limit_up_price: number; limit_down_price: number;
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
  code: string; name: string | null; boards: number | null;
  price: number | null; pct: number | null; amount: number | null; float_cap: number | null; industry: string | null;
}
// S008 T10：/api/market/emotion 返 EmotionResponse——clean Emotion 聚合（嵌套）+
// lianban_stocks 客观榜单（并列出口）。字段更名：zt_count→limit_up_count、
// dt_count→limit_down_count、break_rate→broken_rate、promotion_rate→advance_rate。
export interface EmotionMetrics {
  max_boards: number | null;
  limit_up_count: number | null;
  limit_down_count: number | null;
  seal_rate: number | null;
  broken_rate: number | null;
  advance_rate: number | null;
}
export interface ShortTermEmotion {
  emotion: EmotionMetrics;
  lianban_stocks: LianbanStock[];
  date: string | null;
  lianban_count: number | null;
  zb_count: number | null;
  yzt_count: number | null;
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
// S008 T9：GlobalQuote 退役，quote 子字段走 S007 Quote（扁平）。amount→turnover、
// mcap→market_cap、prev_close→last_close；open/high/low 不在 Quote（如需再补）。
export interface GlobalMetrics {
  report_date: string;
  revenue: number | null; revenue_yoy: number | null; net_profit: number | null;
  eps: number | null; roe: number | null; gross_margin: number | null;
  net_margin: number | null; debt_ratio: number | null;
}
export interface GlobalStock {
  code: string; name: string | null; market: string | null;
  quote: Quote; metrics: GlobalMetrics | null;
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

export interface AuctionTopItem {
  code?: string;
  name?: string;
  score?: number;
  rating?: number;
  signal?: string;
  note?: string;
  [key: string]: unknown;
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
  auction_top: AuctionTopItem[];
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

// ---- 打板工作流类型 ----

// PreMarketBriefing
export interface PreMarketCandidate {
  code: string;
  name: string;
  price?: number;
  change_pct?: number;
  score?: number;
  [key: string]: unknown;
}

export interface PreMarketStrategyMatch {
  strategy_name?: string;
  style?: string;
  match_score?: number;
  confidence?: number;
  description?: string;
  entry_condition?: string;
  [key: string]: unknown;
}

export interface PositionSuggestion {
  code?: string;
  name?: string;
  suggested_weight?: number;
  weight?: number;
  reason?: string;
  action?: string;
  position_pct?: number;
  [key: string]: unknown;
}

export interface PreMarketReport {
  date?: string;
  generated_at?: string;
  sentiment_index?: number;
  sentiment_phase?: string;
  candidates?: PreMarketCandidate[];
  strong_candidates?: PreMarketCandidate[];
  filtered_out?: PreMarketCandidate[];
  strategy_matches?: PreMarketStrategyMatch[];
  position_suggestions?: PositionSuggestion[];
  total_suggested_position?: number;
  warnings?: string[];
  risk_warnings?: string[];
  updated?: string;
  disclaimer?: string;
}

// ---- S023 选股因子接口类型 ----

export interface FactorCandidate {
  code: string;
  name: string;
  source_factor_id: string;
  source_layer: string;
  hit_rules: string[];
  detail: Record<string, unknown>;
}

export interface FunnelLayer {
  layer_id: string;
  name: string;
  as_of: string;
  input_count: number;
  output_count: number;
  filtered_out: { code: string; name?: string | null; reason: string }[];
  output_codes: string[];
  conditions?: string[];
  passed?: FactorCandidate[];
  data_status?: string | null;
  data_reason?: string | null;
}

export interface FactorResult {
  factor_id: string;
  factor_name: string;
  candidates: FactorCandidate[];
  layers: FunnelLayer[];
  config: Record<string, unknown>;
  as_of: string;
  data_date: string;
  data_status: string;
}

export interface PreMarketBriefing {
  // S026: 异步化响应（status 驱动）；旧 fallback 字段保留供兼容
  status?: "idle" | "running" | "done" | "error";
  factors?: FactorResult[];
  data_date?: string;
  as_of?: string;
  market_emotion?: { sentiment_index?: number | null; phase?: string | null };
  run_id?: string;
  msg?: string; // idle: 提示先 refresh
  // 旧路径 fallback
  data?: PreMarketReport;
  fallback?: boolean;
  error?: string;
}

export interface PreMarketRefreshResponse {
  run_id: string;
  status: "running";
  msg?: string; // "已有采集在跑"
}

// IntradayMonitor
export interface TradingSignal {
  code: string;
  name?: string;
  signal_type?: string;
  type?: string;
  reasoning?: string | string[];
  description?: string;
  time?: string;
  [key: string]: unknown;
}

export interface BombAlertItem {
  timestamp: string;
  code: string;
  name: string;
  alert_level: "red" | "yellow" | "orange" | "blue";
  condition: string;
  current_seal_amount: number;
  seal_amount_change_5min: number;
  recommendation: string;
  [key: string]: unknown;
}

export interface PositionAdjustment {
  code: string;
  name?: string;
  action: "add" | "reduce" | "close" | "hold" | string;
  reason?: string;
  priority?: number;
  time?: string;
  [key: string]: unknown;
}

export interface IntradayData {
  date?: string;
  signals?: TradingSignal[];
  alerts?: BombAlertItem[];
  adjustments?: PositionAdjustment[];
  updated?: string;
  market_status?: {
    status: string;
    phase: string;
  };
}

// BombAlertPanel (extends IntradayMonitor types)
export interface HandledAlert extends BombAlertItem {
  handledAt: string;
}

// PostMarketReview
export interface SettlementTrade {
  code: string;
  name: string;
  buy_price?: number | string;
  sell_price?: number | string;
  entry_price?: number | string;
  exit_price?: number | string;
  hold_days?: number;
  return_pct?: number;
  won?: boolean;
  strategy_used?: string;
  type?: string;
  result?: string;
  [key: string]: unknown;
}

export interface StrategyAdjustment {
  strategy?: string;
  type?: string;
  action?: string;
  reason?: string;
  [key: string]: unknown;
}

export interface DailyReturnPoint {
  date: string;
  return_pct: number;
  return?: number; // alias for compatibility
  cumulative?: number;
}

export interface PostMarketReport {
  date?: string;
  generated_at?: string;
  total_trades?: number;
  win_count?: number;
  loss_count?: number;
  win_rate?: number;
  total_return?: number;
  avg_return?: number;
  max_drawdown?: number;
  settlements?: SettlementTrade[];
  adjustments?: StrategyAdjustment[];
  daily_returns?: DailyReturnPoint[];
  updated?: string;
  disclaimer?: string;
}

export interface WorkflowStatus {
  current_stage?: string;
  sentiment_index?: number;
  candidate_pool_count?: number;
  active_signals?: number;
  today_win_rate?: number;
  [key: string]: unknown;
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
