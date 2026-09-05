// lib/journal.ts — S149 P3 交易日志 + 个人风控 API client。
// 后端：GET/POST /api/journal/{list,stats,add,update,delete,fees} +
//       GET/POST /api/risk/{report,at-risk,excursion,attribution,inbox,rules,equity-base}
// ⛠ 个人交易数据——不接入 AI prompt（后端 P3-T1 闭包扫描锁定；前端只读渲染）。
import { request } from "@/lib/api/client";

// ── 类型（对齐后端 journal/risk_rules/at_risk 输出）──
export interface Settled {
  has_fills: boolean;
  closed: boolean;
  avg_cost?: number | null;
  open_shares?: number;
  realized_pnl?: number | null;
  realized_pct?: number | null;
  hold_days?: number;
  first_buy?: string;
  last_sell?: string | null;
  cycles?: number;
  amount?: number;
}

export interface Trade {
  id: string;
  date: string;
  code: string;
  name: string;
  playbook: string;
  pnl_pct: number | null;
  as_planned: boolean | null;
  fills: { side: "buy" | "sell"; date: string; price: number; shares: number; fee?: number }[];
  settled: Settled;
  planned_stop: number | null;
  planned_target: number | null;
  note: string;
  created_at: string;
  market?: { emotion_phase?: string | null; money_effect_median?: number | null; limit_up_count?: number | null };
  stock?: { in_limit_up?: boolean; boards?: number };
}

export interface JournalListResponse {
  trades: Trade[];
  total: number;
}

export interface Fees {
  commission_rate: number;
  commission_min: number;
  stamp_tax_rate: number;
  transfer_fee_rate: number;
  is_default: boolean;
}

export interface RiskRules {
  max_loss_per_trade_pct: number;
  max_loss_per_day_pct: number;
  max_positions: number;
  max_trades_per_day: number;
  pause_after_losses: number;
  max_unplanned_ratio: number;
  _is_default?: boolean;
}

export interface AddTradeBody {
  date: string;
  code: string;
  name?: string;
  playbook: string;
  pnl_pct?: number | null;
  as_planned?: boolean | null;
  note?: string;
  fills?: { side: "buy" | "sell"; date: string; price: number; shares: number; fee?: number }[];
  planned_stop?: number | null;
  planned_target?: number | null;
}

// ── API 函数 ──
export function getJournalList(limit = 200): Promise<JournalListResponse> {
  return request<JournalListResponse>(`/journal/list?limit=${limit}`);
}
export function getJournalStats(): Promise<Record<string, unknown>> {
  return request<Record<string, unknown>>("/journal/stats");
}
export function addJournalTrade(body: AddTradeBody): Promise<{ ok: boolean; trade: Trade }> {
  return request<{ ok: boolean; trade: Trade }>("/journal/add", "POST", body);
}
export function updateJournalTrade(
  tradeId: string,
  body: Partial<AddTradeBody> & { note?: string },
): Promise<{ ok: boolean; trade?: Trade; reason?: string }> {
  return request<{ ok: boolean; trade?: Trade; reason?: string }>(
    `/journal/update?trade_id=${encodeURIComponent(tradeId)}`, "POST", body);
}
export function deleteJournalTrade(tradeId: string): Promise<{ ok: boolean; removed?: number; reason?: string }> {
  return request<{ ok: boolean; removed?: number; reason?: string }>(
    `/journal/delete?trade_id=${encodeURIComponent(tradeId)}`, "POST");
}
export function getJournalFees(): Promise<Fees> {
  return request<Fees>("/journal/fees");
}
export function saveJournalFees(body: Partial<Fees>): Promise<{ ok: boolean; fees: Fees }> {
  return request<{ ok: boolean; fees: Fees }>("/journal/fees", "POST", body);
}

export function getRiskReport(): Promise<Record<string, unknown>> {
  return request<Record<string, unknown>>("/risk/report");
}
export function getAtRisk(): Promise<Record<string, unknown>> {
  return request<Record<string, unknown>>("/risk/at-risk");
}
export function getExcursionSummary(limit = 300): Promise<Record<string, unknown>> {
  return request<Record<string, unknown>>(`/risk/excursion?limit=${limit}`);
}
export function getAttribution(limit = 500): Promise<Record<string, unknown>> {
  return request<Record<string, unknown>>(`/risk/attribution?limit=${limit}`);
}
export function getInbox(limit = 500): Promise<Record<string, unknown>> {
  return request<Record<string, unknown>>(`/risk/inbox?limit=${limit}`);
}
export function getRiskRules(): Promise<RiskRules> {
  return request<RiskRules>("/risk/rules");
}
export function saveRiskRules(rules: Partial<RiskRules>): Promise<{ ok: boolean; rules: RiskRules }> {
  return request<{ ok: boolean; rules: RiskRules }>("/risk/rules", "POST", rules);
}
export function getEquityBase(): Promise<{ equity_base: number | null }> {
  return request<{ equity_base: number | null }>("/risk/equity-base");
}
export function setEquityBase(base: number): Promise<{ ok: boolean; equity_base: number }> {
  return request<{ ok: boolean; equity_base: number }>("/risk/equity-base", "POST", { base });
}

export const PLAYBOOKS = ["打板", "低吸", "接力", "半路", "套利", "其它"] as const;
export type Playbook = (typeof PLAYBOOKS)[number];
