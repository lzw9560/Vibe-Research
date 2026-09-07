// S166: 交易日志 + 风险账本 UI 契约——类型匹配 backend journal/at_risk/risk_rules/
// excursion/attribution/inbox 16 端点 EXACTLY。contract-first（UI 驱动，非反之）。
// 改后端 schema 须同步改本文件（双向锁）。
//
// ⚠️ 诚实标注（§44 + grill #8）：所有 available:False 都带 reason，UI 须如实呈现"暂无"
// 不臆造数据；risk_status/honest_summary 是 R3 诚实风险标签（stop 对 gap-down 仪式非保护，
// s144 path_lift<1），UI 须原文呈现不软化。

// ─────────────── journal：成交明细 + 结算 ───────────────
export type Playbook = "打板" | "低吸" | "接力" | "半路" | "套利" | "其它";
export const PLAYBOOKS: Playbook[] = ["打板", "低吸", "接力", "半路", "套利", "其它"];

export interface Fill {
  side: "buy" | "sell";
  date: string; // YYYY-MM-DD
  price: number;
  shares: number;
  fee?: number; // 可选：对账单实际费用（填了就以它为准）
}

export interface Settled {
  has_fills: boolean;
  closed: boolean;
  buy_shares?: number;
  sell_shares?: number;
  open_shares?: number; // 当前还持有多少
  cycles?: number; // 持仓周期数（>1 = 多轮进出）
  avg_cost?: number; // 当前持仓加权成本
  amount?: number; // 峰值占用资金
  first_buy?: string;
  last_sell?: string | null;
  avg_sell?: number;
  gross_pnl?: number; // 未计费用毛额
  fees?: number;
  fees_are_estimated?: boolean;
  realized_pnl?: number; // 净额（已扣费用）
  realized_by_date?: Record<string, number>;
  realized_pct?: number;
  hold_days?: number;
  is_t0?: boolean;
}

export interface MarketContext {
  emotion_phase: string | null;
  money_effect_median: number | null;
  promotion_overall: null; // ReviewReport 无此字段，不臆造
  limit_up_count: number | null;
  never_broken_rate: null; // 无此字段，不臆造
  has_review: boolean;
}

export interface StockContext {
  in_limit_up?: boolean;
  boards?: number;
  first_seal?: string | null;
  last_seal?: string | null;
  broken_times?: number;
  sector?: string;
  board_type?: string;
  was_broken?: boolean;
}

export interface Trade {
  id: string;
  date: string;
  fills: Fill[];
  settled: Settled;
  code: string;
  name: string;
  playbook: Playbook | string;
  pnl_pct: number | null;
  as_planned: boolean | null;
  planned_stop: number | null;
  planned_target: number | null;
  note: string;
  created_at: string;
  market?: MarketContext;
  stock?: StockContext;
  exit_market?: MarketContext | null;
  updated_at?: string;
  planned_edited_at?: string; // 计划边界事后改过（在险资金口径会失真）
}

export interface TradeListResponse {
  trades: Trade[];
  total: number;
}

// POST /api/journal/add body
export interface AddTradeInput {
  date: string;
  code: string;
  name?: string;
  playbook: Playbook;
  pnl_pct?: number | null;
  as_planned?: boolean | null;
  note?: string;
  fills?: Fill[] | null;
  planned_stop?: number | null;
  planned_target?: number | null;
}
export interface AddTradeResponse {
  ok: boolean;
  trade: Trade;
}

// POST /api/journal/update body（Partial——只改传进来的字段）
export interface UpdateTradeInput {
  fills?: Fill[] | null;
  note?: string | null;
  as_planned?: boolean | null;
  planned_stop?: number | null;
  planned_target?: number | null;
}
export interface UpdateTradeResponse {
  ok: boolean;
  trade?: Trade;
  reason?: string;
}

export interface DeleteTradeResponse {
  ok: boolean;
  removed?: number;
  reason?: string;
}

// ─────────────── journal.stats（自我体检分组） ───────────────
export interface BucketStats {
  count: number;
  scored: number;
  money_scored: number;
  net_pnl: number | null;
  win_rate: number | null; // 持平不计入分母，全持平给 null
  avg: number | null;
  best: number | null;
  worst: number | null;
}
export interface StatsResponse {
  available: boolean;
  reason?: string;
  overall: BucketStats;
  by_phase: Record<string, BucketStats>;
  by_playbook: Record<string, BucketStats>;
  by_planned: Record<string, BucketStats>;
  by_boards: Record<string, BucketStats>;
  by_hold: Record<string, BucketStats>;
  playbooks: Playbook[];
}

// ─────────────── journal fees ───────────────
export interface Fees {
  commission_rate: number;
  commission_min: number;
  stamp_tax_rate: number;
  transfer_fee_rate: number;
  is_default?: boolean;
}
export interface SaveFeesInput {
  commission_rate?: number | null;
  commission_min?: number | null;
  stamp_tax_rate?: number | null;
  transfer_fee_rate?: number | null;
}
export interface SaveFeesResponse {
  ok: boolean;
  fees: Fees;
}

// ─────────────── risk_rules.report（权益 + 纪律 + 违反） ───────────────
export interface EquityPoint {
  date: string;
  cum_pnl: number;
  pnl: number;
  drawdown: number;
}
export interface EquityCurve {
  available: boolean;
  reason?: string;
  points: EquityPoint[];
  trades: number;
  net_pnl: number;
  peak: number;
  peak_date: string | null;
  current_drawdown: number;
  max_drawdown: number;
  max_drawdown_since: string | null;
  trades_since_peak: number;
  longest_underwater: number;
  win_rate: number | null;
  avg_win: number | null;
  avg_loss: number | null;
  payoff_ratio: number | null;
  profit_factor: number | null;
  worst_losing_streak: number;
  worst_trade: number;
  net_without_best1: number;
  net_without_best3: number;
  best_trade_share: number | null;
}
export interface RollingWindow {
  trades: number;
  net_pnl?: number | null;
  win_rate?: number | null;
  avg_win?: number | null;
  avg_loss?: number | null;
  payoff_ratio?: number | null;
  profit_factor?: number | null;
  execution_rate?: number | null;
  date_from?: string;
  date_to?: string;
  window?: number;
  enough?: boolean;
}
export interface Rolling {
  available: boolean;
  reason?: string;
  windows: Record<string, RollingWindow>;
  lifetime: RollingWindow;
  win_rate_drift?: number;
  profit_factor_drift?: number;
  note?: string;
}
export interface DisciplineBucket {
  count: number;
  win_rate: number | null;
  avg_pct: number | null;
  net_pnl: number | null;
}
export interface Discipline {
  available: boolean;
  reason?: string;
  planned: DisciplineBucket;
  unplanned: DisciplineBucket;
  untagged: DisciplineBucket;
  execution_rate: number | null;
  what_if_only_planned: {
    actual_net: number | null;
    planned_only_net: number | null;
    cost_of_indiscipline: number | null;
  };
  note?: string;
}
export interface Violation {
  date: string;
  rule: string;
  label: string;
  limit: number;
  actual: number;
  detail: string;
}
export interface Violations {
  available: boolean;
  reason?: string;
  rules: Record<string, number>;
  is_default_rules: boolean;
  rule_status: Record<string, string>; // "checked" | "unavailable：..."
  unchecked: string[];
  violations: Violation[];
  violation_count: number;
  after_loss_streak: {
    threshold: number;
    trades: number;
    avg_pct: number | null;
    win_rate: number | null;
  };
}
export interface RiskReportResponse {
  equity: EquityCurve;
  rolling: Rolling;
  discipline: Discipline;
  violations: Violations;
  trade_count: number;
}

// ─────────────── at_risk.report（在险资金 + R3 诚实标签） ───────────────
export interface AtRiskPosition {
  id: string;
  code: string;
  name: string;
  date: string;
  playbook: string;
  shares: number;
  avg_cost: number;
  capital: number;
  planned_stop: number | null;
  planned_target: number | null;
  at_risk: number | null;
  at_risk_pct: number | null;
  bounded: boolean;
}
export interface HonestRiskLabel {
  key: string;
  text: string;
}
export interface HonestRiskLabels {
  labels: HonestRiskLabel[];
  kill_switch_note: string;
  honest_summary: string;
}
export interface AtRiskReport {
  available: boolean;
  reason?: string;
  positions: AtRiskPosition[];
  position_count: number;
  total_capital: number;
  total_at_risk: number;
  bounded_count: number;
  unbounded_count: number;
  unbounded_capital: number;
  equity_base: number | null;
  rules: {
    max_loss_per_trade_pct: number | null;
    max_positions: number | null;
    is_default: boolean;
  };
  risk_status: HonestRiskLabels;
  at_risk_of_equity_pct?: number;
  capital_of_equity_pct?: number;
  over_per_trade_limit?: { name: string; code: string; pct_of_equity: number }[];
  equity_base_hint?: string;
  over_position_limit?: { actual: number; limit: number };
  unbounded_note?: string;
}

// ─────────────── excursion.summary（MFE/MAE） ───────────────
export interface ExcursionItem {
  available: boolean;
  code: string;
  name: string;
  date: string;
  exit_date: string;
  realized_pct: number;
  mfe_pct: number;
  mae_pct: number;
  mfe_certain: number | null;
  mae_certain: number | null;
  certain_note: string | null;
  bars: number;
  bars_inner: number;
  same_day: boolean;
  precision: string;
  give_back_pct: number;
  capture_rate: number | null;
  capture_note: string | null;
}
export interface ExcursionSummary {
  available: boolean;
  reason?: string;
  failed?: number;
  trades: number;
  enough_samples: boolean;
  median_capture_rate: number | null;
  capture_samples: number;
  median_give_back: number;
  median_mae: number;
  endured_count: number;
  bad_entry_count: number;
  same_day_count: number;
  lost_with_move_count: number;
  capture_note: string | null;
  items: ExcursionItem[];
  bias_note: string;
  caveat?: string;
}

// ─────────────── attribution（判断/执行归因，⚠️ 暂降级 available:False） ───────────────
export interface AttributionResponse {
  available: boolean;
  reason?: string;
  days_counted?: number;
  enough_samples?: boolean;
  quadrant_labels?: Record<string, string>;
  quadrants?: Record<string, { days: number; pnl: number; days_list: string[] }>;
  cells?: Record<string, unknown>;
  skipped_no_amount?: number;
  skipped_no_read?: number;
  note?: string;
}

// ─────────────── inbox（异常收件箱） ───────────────
export interface InboxFlag {
  key: string;
  text: string;
}
export interface InboxItem {
  id: string;
  date: string;
  code: string;
  name: string;
  playbook: string;
  pnl_pct: number | null;
  note: string;
  closed: boolean;
  flags: InboxFlag[];
}
export interface InboxResponse {
  available: boolean;
  reason?: string;
  items: InboxItem[];
  count: number;
  scanned: number;
  by_flag: Record<string, number>;
  baseline: {
    median_capital: number | null;
    median_hold_days: number | null;
    history_enough: boolean;
    min_history: number;
  };
  rules_is_default: boolean;
  excursion_skipped: number;
  excursion_hint: string | null;
  note: string;
  excursion_available: boolean;
}

// ─────────────── risk_rules + equity_base（风险宪法 + 账户规模） ───────────────
export interface RiskRules {
  max_loss_per_trade_pct: number;
  max_loss_per_day_pct: number;
  max_positions: number;
  max_trades_per_day: number;
  pause_after_losses: number;
  max_unplanned_ratio: number;
  is_default?: boolean;
}
export interface SaveRulesInput {
  max_loss_per_trade_pct?: number | null;
  max_loss_per_day_pct?: number | null;
  max_positions?: number | null;
  max_trades_per_day?: number | null;
  pause_after_losses?: number | null;
  max_unplanned_ratio?: number | null;
}
export interface SaveRulesResponse {
  ok: boolean;
  rules: Partial<RiskRules>;
}
export interface EquityBaseResponse {
  equity_base: number | null;
}
export interface SaveEquityBaseInput {
  base: number;
}
export interface SaveEquityBaseResponse {
  ok: boolean;
  equity_base: number;
}
