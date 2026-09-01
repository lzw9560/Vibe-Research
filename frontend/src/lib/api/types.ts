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
  pe_ttm: number; pb: number; turnover_pct: number;
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
// 交叉验证源（同花顺涨停揭秘，S049）
export interface EmotionCrossSource {
  ths_zt_count: number;      // 同花顺涨停家数
  diff_pct: number;          // 与东财涨停家数差异百分比
  divergent: boolean;        // 差异>5% 标注分歧
}
export interface ShortTermEmotion {
  emotion: EmotionMetrics;
  lianban_stocks: LianbanStock[];
  date: string | null;
  lianban_count: number | null;
  zb_count: number | null;
  yzt_count: number | null;
  // S049 同花顺交叉验证 / 降级源（可选，主源正常且无交叉验证时为 null）
  cross_source?: EmotionCrossSource | null;
  data_source?: string | null;  // "eastmoney" / "ths_fallback"
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
  code: string; name: string; price: number | null; shares: number; cost: number;
  market_value: number | null; pnl: number | null; pnl_pct: number | null;
  data_status?: string;  // S125 R1：degraded（行情取数失败）→ 字段 null，前端标"数据缺失"
}
export interface ClosedPosition {
  code: string; name: string; date: string; price: number; shares: number; cost: number;
  pnl: number; pnl_pct: number;
}
export interface PortfolioData {
  holdings: Holding[];
  totals: { market_value: number; cost: number; pnl: number; pnl_pct: number; data_status?: string };
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
  is_delayed?: boolean;  // S135：push2delay 延时镜像→true（gstock.py:128 透传）
}
// S008 T9：GlobalQuote 退役，quote 子字段走 S007 Quote（扁平）。amount→turnover、
// mcap→market_cap、prev_close→last_close；open/high/low 不在 Quote（如需再补）。
export interface GlobalMetrics {
  report_date: string;
  revenue: number | null; revenue_yoy: number | null; net_profit: number | null;
  eps: number | null; roe: number | null; gross_margin: number | null;
  net_margin: number | null; debt_ratio: number | null;
}
// S020/main：global-stock-data 的行情（含 mcap/amount/open/high/low，区别于 A 股 Quote）
export interface GlobalQuote {
  code: string; name: string;
  price: number | null; open: number | null; high: number | null; low: number | null;
  prev_close: number | null; amount: number | null; mcap: number | null; change_pct: number | null;
  is_delayed?: boolean;  // S135：push2delay 延时镜像→true（gstock._quote_from 透传，mapper 落 Quote）
}
export interface GlobalStock {
  code: string; name: string; market: string;
  quote: GlobalQuote; metrics: GlobalMetrics | null;
}
// 港股现金流量表（global-stock-data，仅港股）
export interface HkCashflowItem { amount: number | null; yoy: number | null }
export interface HkCashflowPeriod {
  report_date: string; report: string | null;
  currency: string | null; account_standard: string | null;
  items: Record<string, HkCashflowItem>;
}
export interface HkCashflow {
  code: string; name: string; market: string;
  currency: string | null; item_order: string[]; periods: HkCashflowPeriod[];
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
  // S056
  is_triggered?: boolean;
  weather_state?: string;
  data_status?: string;
}

// S056：熔断状态汇总
export interface FuseState {
  rules: FuseRule[];
  fuse_state: "triggered" | "normal";
  weather_state: string;
  updated_at: string;
}

// S056：次日强制离场信号
export interface ExitSignal {
  code: string;
  name: string;
  signal: string | null;
  reason: string;
  change_pct?: number | null;
  price?: number | null;
  ma_price?: number | null;
  data_status: "ok" | "missing";
}

export interface ExitSignalsResult {
  date: string;
  signals: ExitSignal[];
  summary: { total: number; triggered: number; missing: number };
  ma_days: number;
  note: string;
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

// ---- 胜率记录录入（S025-A1）----
// 字段对齐后端 WinRateRecord（win_rate_tracker.py:18）+ POST /api/winrate/records
// （routers/win_rate.py:92）。后端 rec.get(field, default) 全字段可选，但校验
// stock_code/entry_date/exit_date 非空（router:116）。故前端 input：三者必填，其余可选。
export interface WinRateRecordInput {
  stock_code: string;      // 必填
  stock_name?: string;
  strategy_used?: string;
  entry_date: string;      // 必填
  entry_price?: number;
  exit_date: string;        // 必填
  exit_price?: number;
  return_pct?: number;
  is_win?: boolean;
  gene_score?: number;
  sti_label?: string;
  sector?: string;
}

// POST /api/winrate/records 返回 {data:{added,added_count,errors,error_count}}；
// request() 自动解包 .data，故本类型为内层结构（同 WinRateStats 不带 data 包装）。
export interface WinRateRecordsResponse {
  added: string[];
  added_count: number;
  errors: { index: number; error: string }[];
  error_count: number;
}

// ---- S050 W0：影子对照（行为闭环）----
// 对齐后端 GET /api/winrate/shadow-comparison（routers/win_rate.py:_shadow_comparison_impl）。
// 三桶算账 + 独立性指标 + 诚实标记（sufficient/no_suggestion_days/missing_kline）。
export interface ShadowBucket {
  n: number;
  win_rate: number | null;
  avg_return: number | null;
}
export interface ShadowMissedBucket extends ShadowBucket {
  missing_kline: number;
  approx_note: string;
}
export interface ShadowComparison {
  window_days: number;
  follow: ShadowBucket;
  feeling: ShadowBucket;
  missed: ShadowMissedBucket;
  independence: {
    agreement_rate: number | null;
    feeling_win_rate: number | null;
  };
  no_suggestion_days: number;
  sufficient: boolean;
  disclaimer: string;
}

// ---- 胜率趋势/调整/下钻（S025-A 类型收紧）----
// 对齐后端 win_rate_tracker：get_trends / generate_strategy_adjustments /
// get_sector_stats / get_strategy_stats 返回结构（request() 自动解包 .data）。
export interface WinRateTrendPoint {
  date: string;
  total_trades: number;
  win_count: number;
  win_rate: number;
}

export interface WinRateAdjustment {
  type: string;
  reason: string;
  action: string;
}

export interface SectorWinStats {
  sector: string;
  total_trades: number;
  win_count: number;
  win_rate: number;
  avg_return: number;
}

export interface StrategyWinStats {
  strategy: string;
  total_trades: number;
  win_count: number;
  win_rate: number;
  avg_return: number;
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

// 回测散点：gene_score vs 次日收益。对齐后端 backtest_lite.generate_scatter_data
// 返回结构（date/industry 始终存在——industry 有 getattr 兜底 "未知"）。
export interface BacktestScatterPoint {
  gene_score: number;
  next_day_return: number;
  code: string;
  date: string;
  industry: string;
}

// ---- S041 回测趋势看板 ----
// GET /api/backtest/trend?days=90 返 BacktestSnapshotRow[]（daily_backtest_run 定时任务
// 每日落库的快照）。engine=lite 行带 hit_rate/avg_return；engine=strategy 行带
// strategy_breakdown_json（8 战法聚合 JSON 字符串，前端解析为 StrategyBacktestItem[]）。
export interface BacktestSnapshotRow {
  snapshot_date: string;        // "2026-08-09"
  engine: "lite" | "strategy";
  hit_rate: number | null;     // 0-1，仅 lite
  avg_return: number | null;   // 百分比小数（lite）或百分比数（strategy）
  max_drawdown: number | null;
  sharpe_ratio: number | null;
  total_signals: number | null;
  percentile_json: string | null;         // lite 分位分析 JSON 字符串
  strategy_breakdown_json: string | null; // strategy 战法明细 JSON 字符串
  created_at: string;
}

// strategy_breakdown_json 解析后元素类型。对齐 backend/strategies/strategy_backtest.py
// StrategyBacktestResult（strategy_code/strategy_name/win_rate 0-1/avg_return 百分比/sample_size）。
export interface StrategyBacktestItem {
  strategy_code: string;
  strategy_name: string;
  win_rate: number;      // 0-1
  avg_return: number;    // 百分比
  sample_size: number;
}

// ---- S043 单因子分位分析 ----
// GET /api/backtest/factor-analysis 返回结构。buckets 键为桶标签（"0-30"/"30-50"/"50-70"/"70-100"），
// 值含 count/avg_return/hit_rate（avg_return 为小数收益率，hit_rate 0-1）。
export interface FactorPercentileBucket {
  count: number;
  avg_return: number;
  hit_rate: number;
}

// S059：因子 IC 评估（Pearson + Spearman 秩相关）。样本<20 返 null（诚实标注）。
export interface FactorIcAnalysis {
  ic: number;
  rank_ic: number;
  n: number;
}

export interface FactorAnalysisResult {
  factor: string;
  period: string;
  sample_size: number;
  buckets: Record<string, FactorPercentileBucket>;
  ic_analysis: FactorIcAnalysis | null;
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

// ---- S054 W0：盘后三问 daily-review ----
// 对齐后端 GET /api/winrate/daily-review（routers/win_rate.py:_daily_review_impl）。
// pushed/bought/missed 三问 + prev_day_missed 上一交易日漏单次日收益。
export interface DailyReviewPushedItem {
  code: string;
  name: string;
  gene_score: number | null;
  strategies: string[];
}
export interface DailyReviewBoughtItem {
  code: string;
  name: string;
  entry_price: number | null;
  strategy: string | null;
  status: string;
  placeholder: string;
}
export interface DailyReviewMissedItem {
  code: string;
}
export interface PrevDayMissedItem {
  code: string;
  next_day_return: number;
}
export interface PrevDayMissedSummary {
  n: number;
  avg_return: number;
  win_rate: number;
  signal_date: string;
}
export interface DailyReviewResponse {
  date: string;
  no_snapshot: boolean;
  pushed: DailyReviewPushedItem[];
  bought: DailyReviewBoughtItem[];
  missed: DailyReviewMissedItem[];
  prev_day_missed: {
    items: PrevDayMissedItem[];
    summary: PrevDayMissedSummary | null;
  };
  missing_kline: number;
  disclaimer: string;
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
  // S031 R14/R19/R22：因子层 FunnelLayer.passed 各层语义可选字段
  //（L2 best_strategy/confidence_value 供 R19 反筛/R22 合成胜率；L3 suggested_pct/matched_strategy；L1 gene_score）
  best_strategy?: string;
  confidence?: string;
  confidence_value?: number;
  suggested_pct?: number;
  matched_strategy?: string;
  gene_score?: number | null;
  reasons?: string[];
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

/**
 * S024-D2 连板梯队树节点：后端 GET /api/topology/board-ladder 返嵌套树。
 * - name 展示名（叶节点后端拼好「code name」）
 * - code 仅叶节点带（个股代码，公开榜单客观事实）
 * - value 叶节点=连板高度（lbc）
 * - children 子层（height→industry→stock）
 */
export interface BoardLadderNode {
  name: string;
  code?: string;
  value?: number;
  children?: BoardLadderNode[];
}

/**
 * S024 拓扑图数据契约（共用图引擎 GraphView 输入）。
 * 后端 GET /api/topology/relation 返 {nodes,edges}，契约同 GraphData。
 * 拓扑只呈现客观关联（同板块/共流入/梯队/席位），不输出方向词（§0 弱合规·工程底线）。
 */

/**
 * 边类型：可扩展枚举。
 * 注意（S024-C review #4）：spec R5「新边类型加 provider 不动视图」仅后端成立——
 * 后端可免改视图；前端需注册 EdgeType（此联合）+ EDGE_COLORS（GraphView 内 Record）。
 * - sector: 同板块联动
 * - fund_flow: 共资金流入
 * - ladder: 连板梯队
 * - seat: 共席位
 * - flow: 漏斗层数据流向（R1→R2→R3→SELF，客观流向，非方向结论）
 */
export type EdgeType = "sector" | "fund_flow" | "ladder" | "seat" | "flow";

/**
 * 图节点。id 唯一；name 展示；category 分组着色；
 * value 可用于节点大小映射；code 关联个股代码。
 */
export interface GraphNode {
  id: string;
  name: string;
  category?: string;
  value?: number;
  code?: string;
}

/**
 * 图边。source/target 指向 GraphNode.id；
 * type 区分关联来源；weight 控制线宽/强度。
 */
export interface GraphEdge {
  source: string;
  target: string;
  type: EdgeType;
  weight: number;
}

/**
 * 统一图数据格式，GraphView 的输入契约。
 */
export interface GraphData {
  nodes: GraphNode[];
  edges: GraphEdge[];
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
  // S026: 异步化响应（status 驱动）；S048: 加 no_snapshot（历史无快照待补采）
  status?: "idle" | "running" | "done" | "error" | "no_snapshot";
  factors?: FactorResult[];
  // S048 R9/R4：快照随带漏斗层（from_snapshot 时前端直渲，历史零外部请求）
  funnel_layers?: FunnelLayer[];
  from_snapshot?: boolean;   // true = 来自盘上快照（非内存态）
  is_backfill?: boolean;     // true = 该快照为事后补采（非当日采集）
  data_date?: string;
  as_of?: string;
  // S049 B：市场情绪区重写——STI 分数+阶段 + 三率 + ladder + 涨跌停家数
  market_emotion?: MarketEmotionBriefing;
  // S063 T4：管线头部情绪上下文（T-1 硬标准）
  sentiment_context?: SentimentContext;
  run_id?: string;
  msg?: string; // idle: 提示先 refresh；no_snapshot: 提示可补采
  // S049 C4：快照随带 final_candidates 诊断卡（抽屉查看历史快照日期时优先用）
  final_candidates?: import("@/lib/candidates").DiagnosisCard[];
  // B-lite：战法打分候选（score_candidates 产出，供前端战法 tab 过滤）
  scored_candidates?: ScoredCandidate[];
  // S094 T17/R28：非涨停 pipeline 打分候选（market_scan funnel_type，briefing 分区透传）
  market_scan_scored?: ScoredCandidate[];
  // S079 P2 仓位闸 + 龙虎榜风控字段（D1-D3 透传，spec R9-R10）
  market_phase?: string;            // 冰点/普通/活跃/亢奋/红期
  market_phase_cap?: number;        // 绿1.0/黄0.5/红0.2
  position_cap_tier?: "green" | "yellow" | "red";
  // S096：P2 现象判据（完整链 + 红期 override + 数据降级）
  p2_factors?: { zt_count?: number | null; big_loss?: number | null; floor?: number | null; ladder_success?: number | null; ladder_height?: number | null };
  p2_fired_rule?: string;
  seat_risk_flags?: Record<string, string[]>;  // {code: ["【拒绝介入】..."/"独食独大"/"散户霸榜"]}
  data_missing_flags?: Record<string, string>; // {code: 警示字符串}
  execution_checklist?: string[];   // 人工执行 checklist
  param_disclaimer?: string;        // "仓位参数参考值，非执行指令..."
  // 旧路径 fallback
  data?: PreMarketReport;
  fallback?: boolean;
  error?: string;
}

/** S097 §5.4：逐条件因子过滤漏斗摘要——scored_candidates 每项可选携带（同战法共享）。 */
export interface StrategyFunnelCondition {
  condition_id: string;    // "first_plate.c1"
  condition_name: string;  // "基因得分合格"
  factor: string;          // "total_score"
  threshold: string;       // ">= 60"
  input_count: number;     // 评估候选数
  passed_count: number;    // 命中数
  data_unavailable_count: number;  // 数据缺失数（独立于逻辑过滤）
  pass_rate: number;       // passed/input
}

/** S097 §5.4：候选逐条件命中状态（三态）。 */
export interface StrategyFunnelCandidateCondition {
  condition_id: string;
  state: "hit" | "miss" | "data_unavailable";
}

/** S097 §5.4：漏斗内单个候选的逐条件命中明细。 */
export interface StrategyFunnelCandidate {
  code: string;
  name: string;
  fired: boolean;
  conditions: StrategyFunnelCandidateCondition[];
}

/** S097 §5.4：战法逐条件漏斗摘要（fired/total + conditions + candidates 三态明细）。 */
export interface StrategyFunnelSummary {
  strategy_code: string;
  strategy_name: string;
  fired_count: number;       // 该战法 fired 候选数
  total_count: number;       // 该战法评估候选总数
  conditions: StrategyFunnelCondition[];
  candidates: StrategyFunnelCandidate[];
}

/** B-lite：score_candidates 返回项（对齐 backend/strategies/strategy_funnel_registry.py:439-448）。 */
export interface ScoredCandidate {
  code: string;
  name: string;
  strategy_code: string;
  strategy_name: string;
  strategy_score: number;
  score_breakdown?: Record<string, number>;
  funnel_type?: string;
  weather_recommended?: boolean;
  position_params?: { stop_loss_pct: number; take_profit_pct: number; max_hold_days: number; position_scale: number };
  note?: string;
  // S097 D（R12/R13）：逐条件漏斗摘要（同战法共享，仅当后端产 strategy_funnel 时存在）
  strategy_funnel?: StrategyFunnelSummary;
  // 保留候选原有字段（factors/total_score/zt_count_250d 等）
  [key: string]: unknown;
}

/** S049 B：盘前简报市场情绪区 shape（_fetch_market_emotion 重写后）。 */
export interface MarketEmotionBriefing {
  sti_score: number | null;
  sti_phase: string | null;  // 高潮/启动/分歧/冰点/退潮
  seal_rate: number | null;   // 封板率
  break_rate: number | null;  // 炸板率
  promotion_rate: number | null;  // 晋级率
  ladder: { boards: number; count: number; plus?: boolean }[];
  zt_count: number | null;   // 涨停家数
  dt_count: number | null;   // 跌停家数
}

/** S049 D1：漏斗层 passed 全参数（行=三层 union，列=R1/R2/R3 + 统一参数列）。 */
export interface FunnelPassedEntry extends FactorCandidate {
  consec_boards?: number | null;
  turnover_pct?: number | null;
  vol_ratio?: number | null;
  amount_yi?: number | null;
  amplitude_pct?: number | null;
  main_net_inflow?: number | null;
  main_net_5d?: number | null;
  northbound?: number | null;
  auction_open_pct?: number | null;
  catalyst_summary?: string | null;
  matched_triggers?: string[];
}

/** S049 D8：战法回溯交易明细（GET /api/strategy/backtest/trades）。 */
export interface BacktestTrade {
  date: string;
  code: string;
  name: string;
  won: boolean;
  return_pct: number;
}

export interface BacktestTradesResponse {
  disclaimer: string;
  strategy_code: string;
  trades: BacktestTrade[];
  available_days: number;
  lookback_days: number;
}

/** S048 R6：GET /api/workflow/pre-market/dates 响应——有快照的日期降序。 */
export interface PreMarketDates {
  dates: string[];
}

export interface PreMarketRefreshResponse {
  run_id: string;
  status: "running";
  msg?: string; // "已有采集在跑"
}

// S063：管线头部情绪上下文（T-1 硬标准）
export interface SentimentContext {
  source_date: string | null;          // T-1 日期
  decision_date: string;              // T 日期
  weather_state: SentimentWeatherState;
  sti_score: number | null;
  sti_phase: string | null;
  fuse_state: SentimentFuseState | null;
  allowed_styles: string[];
  forbidden_styles: string[];
  composite_score: number | null;
  factors: Record<string, { score: number; weight: number; name: string }> | null;
  change_from_yesterday: number | null;
  data_status: "ok" | "missing";
}

// S063：情绪天气状态字符串字面量联合（区别于既有的 WeatherState interface）
export type SentimentWeatherState = "晴天" | "阴天" | "暴风雨" | "极端反弹" | "未知";

export interface SentimentFuseState {
  fuse_state: "triggered" | "normal";
  weather_state: string;
  rules: SentimentFuseRule[];
}

export interface SentimentFuseRule {
  id: string;
  name: string;
  current_state: string;
  weather_state?: string;
  is_triggered: boolean;
}

// S063：盘中情绪采样 snapshot
export interface IntradaySnapshot {
  date: string;
  time: string;
  zt_count: number | null;
  zb_count?: number | null;   // S093：炸板数（后端 intraday_sentiment 透传，C8 规则 + 市场情绪用）
  seal_rate: number | null;
  break_rate: number | null;
  ad_ratio: number | null;
  dt_count?: number | null;   // S093：跌停数（后端透传，C8 规则用）
  ladder?: Array<{ boards?: number; count?: number }> | null;  // S093：连板梯队（C9 规则用，渲染留 S094）
  score: number | null;
  trend: "up" | "flat" | "down";
  t1_baseline: number | null;
  zone: "green" | "yellow" | "red";
  projected_t1_score?: number | null;
  projected_t1_weather?: SentimentWeatherState | null;
  actual_score?: number | null;
  status?: string;
  message?: string;
}

export interface IntradayHolding {
  code: string;
  name: string;
  status: string;
  entry_price: number | null;
  current_price: number | null;
  pnl_pct: number | null;
  seal_status: string;       // 封住/炸板回封/炸板未回封/未封板/数据未取得
  current_zone: "green" | "yellow" | "red";
  dual_pressure: boolean;   // 个股炸板未回封 + 红色区
}

export interface IntradayScenario {
  condition: string;
  impact: string;
  suggestion: string;
}

export interface IntradayHistoryReference {
  sample_size: number;
  similar_count: number;
  follow_up_distribution: { up: number; flat: number; down: number };
  note: string;
}

export interface T1ProjectionScenario {
  name: string;             // 维持/反弹
  projected_t1_score: number;
  projected_t1_weather: SentimentWeatherState;
  assumption: string;
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

// ============ S033：工作流状态机（七态落库 + 手动流转） ============

/** 单股工作流状态行（workflow_state 表）。entry_price/exit_price/strategy 为
 * 用户自填操作记录（holding 买入价 / settled 卖出价 / 战法），非系统推荐。 */
export interface WorkflowState {
  code: string;
  name: string;
  trade_date: string;
  status: string;
  reason: string;
  created_at: string;
  updated_at: string;
  entry_price?: number | null;
  exit_price?: number | null;
  strategy?: string | null;
  /** S034：settled 行的结算摘要（单股端点确定性重算）。
   * S038：exit_price_source 标注卖出价来源——"market"（后端拉市价即结）/
   * "manual"（用户手填）/ null（未结算/缺价跳过）。 */
  settlement?: { return_pct: number; won: boolean; hold_days: number; exit_price_source?: "market" | "manual" | null } | null;
  /** 单股端点附带的当前态允许目标（全日列表端点不返） */
  allowed_targets?: string[];
}

export interface WorkflowStateList {
  date: string;
  states: WorkflowState[];
  counts: Record<string, number>;
}

/** POST /api/workflow/state/transition 请求体（价格/战法可选填）。
 * S038：auto_fill_exit_price=true → 后端拉市价即结（exit_price 空时）。 */
export interface TransitionRequest {
  code: string;
  date: string;
  target: string;
  reason?: string;
  entry_price?: number;
  exit_price?: number;
  strategy?: string;
  auto_fill_exit_price?: boolean;
  attention_mode?: "A" | "B" | "C";  // S050 W0：结算归因用（缺省 A）
}

export interface WorkflowStateHistoryItem {
  code: string;
  trade_date: string;
  from_status: string;
  to_status: string;
  reason: string;
  created_at: string;
}

// S042 统一持仓建议引擎（推荐/自选/持仓三场景）
export interface AdvisoryItem {
  code: string;
  name: string;
  scene: "recommendation" | "watchlist" | "holding";
  action: "enter" | "add" | "reduce" | "close" | "hold" | "no_signal";
  win_rate: number | null;
  win_rate_source: "backtest_90d" | "synthetic" | "none";
  matched_strategy: string | null;
  reasons: string[];
  risk_notes: string[];
  disclaimer: string;
  gene_score?: number;
  suggested_pct?: number;
  stop_loss_pct?: number;
  take_profit_pct?: number;
  pnl_pct?: number | null;  // S125 R1：degraded holding → null
  cost?: number;
  price?: number;
  status?: string;
}

export interface AdvisorySummary {
  recommendations: AdvisoryItem[];
  watchlist: AdvisoryItem[];
  holdings: AdvisoryItem[];
  disclaimer: string;
  // S067 P3：端点超时降级标记（partial=true 时三场景未全返回）
  partial?: boolean;
  timed_out?: boolean;
  timeout_seconds?: number;
  note?: string;
}

// S060：明日验证条件对账卡
export type VerificationStatus = "pending" | "met_up" | "met_down" | "within" | "data_missing";

export interface VerificationCondition {
  id: number;
  date: string;
  metric: string;
  subject: string | null;
  baseline: number | null;
  threshold_up: number | null;
  threshold_down: number | null;
  actual: number | null;
  status: VerificationStatus;
  note: string | null;
  created_at: string;
  verified_at: string | null;
}

export interface VerificationCardResult {
  date: string;
  conditions: VerificationCondition[];
  count: number;
  status_summary: Record<VerificationStatus, number>;
  note: string;
}

// S055：炸板预警 + 封单时序
export interface BombAlertItem {
  id: number;
  rule_id: string;  // C1/C2/C3/C4/C5/C6
  alert_level: "red" | "yellow" | "orange" | "blue";
  condition: string;
  code: string;
  name: string;
  ts: string;
  data_status: "ok" | "missing" | "degraded";
}

export interface BombAlertsResult {
  date: string;
  alerts: BombAlertItem[];
  count: number;
  note: string;
}

export interface SealSnapshot {
  ts: string;
  date: string;
  code: string;
  name?: string | null;
  seal_amount?: number | null;
  open_count?: number | null;
  price?: number | null;
  float_market_cap?: number | null;
  index_5min_change?: number | null;
}

export interface SealSnapshotsResult {
  code: string;
  date: string;
  snapshots: SealSnapshot[];
  count: number;
  data_status: "ok" | "missing";
}

// S064：盯盘教练
export interface CoachTimetableSlot {
  slot_id: string;
  label: string;
  start: string;
  end: string;
  watch: string;
  judge: string;
  teaching: string;
  mode_note: Record<"A" | "B" | "C", string>;
}

export interface CoachModeRules {
  label: string;
  desc: string;
}

export interface CoachChecklistItem {
  code: string;
  name: string;
  status: string;
  strategy: string | null;
  strategy_name: string;
  entry_condition: string;
  stop_loss_condition: string;
  matched_triggers: string[];
  seal_amount: number | null;
  bomb_alerts: { rule_id: string; reason: string }[];
  data_status: "ok" | "missing" | "degraded";
  max_hold_warning: string | null;
  attention_mode: string;
}

// ============ S075 首板流 ============
// 对齐后端 GET /api/workflow/first-board/candidates（routers/workflow.py:913）。
// run_first_board_filter 产出：候选池 + 三层剔除记录 + 9 维度评分 + 市场环境标记。
// §44 诚实标注：9 维度评分未 validated 仅参考；阈值/权重待回测校准（见 note 字段）。

/** 单个候选的 9 维度评分明细 + 总分 + 排名。 */
export interface FirstBoardScoreBreakdown {
  sector: number;          // 维度1 板块评分 15%
  hot_money: number;       // 维度2 游资画像 15%
  seal_strength: number;   // 维度3 封板强度 20%
  chip: number;            // 维度4 筹码结构 10%
  auction: number;         // 维度5 竞价确认 10%
  northbound: number;      // 维度6 北向资金 10%
  institution: number;     // 维度7 龙虎榜机构 10%
  theme: number;           // 维度8 题材热度 5%
  event: number;           // 维度9 事件评分 5%
  [key: string]: number;   // 容错后端未来扩展
}

/** 9 维度原始数据（raw_values——后端 score_candidate 新增字段）。
 * 旧快照无此字段 → undefined，前端降级显示"旧快照无原始值"。
 * 每个维度的子字段可能为 null（数据源缺失），前端标"—"。 */
export interface FirstBoardRawValues {
  sector?: { sector_zt_count?: number | null; sector_rank?: number | null };
  hot_money?: { seat_risk_label?: string | null; one_day_ratio?: number | null };
  seal_strength?: {
    first_seal?: number | null;       // 首封时间（HHMMSS 数字，如 93500）
    seal_amount?: number | null;      // 封单额（元）
    float_cap?: number | null;        // 流通市值（元）
    seal_ratio?: number | null;       // 封单/流通市值比
    break_times?: number | null;      // 炸板次数
  };
  chip?: { turnover?: number | null; vol_ratio?: number | null; amount?: number | null };
  auction?: { auction_open_pct?: number | null; auction_vol_ratio?: number | null };
  northbound?: { northbound_net?: number | null };
  institution?: { inst_net?: number | null };
  theme?: { theme_zt_count?: number | null; theme_name?: string | null };
  event?: { event_type?: string | null; announcement_title?: string | null };
}

export interface FirstBoardCandidate {
  code: string;
  name: string;
  total: number;                       // 加权总分 0-100
  scores: FirstBoardScoreBreakdown;    // 9 维度分明细
  rank: number;                        // 1-based
  raw_values?: FirstBoardRawValues;    // 9 维度原始数据（旧快照可能无此字段）
  [key: string]: unknown;              // 原始候选字段（price/industry/seal_amount 等）
}

/** 三层剔除记录（层1 封板质量 / 层2 筹码结构 / 层3 市场环境）。 */
export interface FirstBoardExcludedItem {
  code: string;
  name?: string;                            // 标的名称（后端 excluded 记录补 name 字段；旧快照可能无）
  layer: 1 | 2 | 3;
  reason: string;
  [key: string]: unknown;
}

/** 市场环境标记（层3 不直接剔除，仅 flag；high_risk=true 表示大盘跌 > 1.5%）。 */
export interface FirstBoardEnvFlags {
  market_drop_pct: number | null;
  high_risk: boolean;
  max_boards: number | null;
  ladder_broken: boolean;
  [key: string]: unknown;
}

export interface FirstBoardCandidatesResponse {
  date: string;                                  // YYYY-MM-DD
  zt_pool_count: number;                          // 涨停池总数（快照可能为 0）
  first_board_count: number;                      // 首板数（快照可能为 0）
  candidates: FirstBoardCandidate[];              // 通过三层剔除 + 评分排序后的候选池
  excluded: FirstBoardExcludedItem[];             // 三层剔除记录（快照可能为空）
  env_flags: FirstBoardEnvFlags;                  // 市场环境标记（快照可能为空对象）
  note: string;                                   // §44 诚实标注
  from_cache?: boolean;                           // true = 历史快照（zt_pool_count/excluded 可能空）
}
