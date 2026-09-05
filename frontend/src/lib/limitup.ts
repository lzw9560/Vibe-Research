// S029 涨停基因选股 — API client（/limitup/gene GeneScreener 页用）
// 后端端点（S028 后已就绪）：
//   GET  /api/limitup/screener?date=        → ScreenerResult
//   GET  /api/limitup/screener/params        → 阈值参数
//   POST /api/limitup/screener/params         → 持久化阈值
//   POST /api/limitup/screener/trigger        → 手动触发今日预计算（后台异步）
import { request } from "@/lib/api/client";
import type { ScreenerResult } from "@/lib/api";

/** 涨停基因阈值/参数（后端 LimitUpParamsBody）。 */
export interface GeneScreenerParams {
  gene_qualify_threshold: number;
  gene_high_threshold: number;
  lookback_days: number;
}

/** 取指定日期涨停基因得分（客观数据）。date 缺省取最近交易日。 */
export function getGeneScreener(date?: string): Promise<ScreenerResult> {
  const qs = date ? `?date=${encodeURIComponent(date)}` : "";
  return request<ScreenerResult>(`/limitup/screener${qs}`);
}

/** 取当前阈值参数。 */
export function getGeneParams(): Promise<GeneScreenerParams> {
  return request<GeneScreenerParams>("/limitup/screener/params");
}

/** 持久化阈值参数（同时更新后端模块常量，需 trigger 重跑才重算 qualify 标志）。
 * S051 D2：响应带可选 warnings（阈值越界提醒）。 */
export function saveGeneParams(params: GeneScreenerParams): Promise<{ status: string; warnings?: string[] }> {
  return request<{ status: string; warnings?: string[] }>("/limitup/screener/params", "POST", params);
}

/** 手动触发今日基因得分预计算（后台异步，~90s 内懒算落库）。 */
export function triggerGenePrecompute(): Promise<{ status: string; date: string }> {
  return request<{ status: string; date: string }>("/limitup/screener/trigger", "POST");
}

// ───────────────── S149 Phase 2：派生情绪指标（赚钱效应/连板溢价/情绪周期）─────────────────
// 后端：GET /api/limitup/emotion-metrics + /api/limitup/consec-premium-detail
// aggregate 无个股名（守 market.py:166 零个股名契约）；明细带个股名走独立路由、不进 AI。

/** 赚钱效应（aggregate，无个股名）：昨日涨停股在目标日的表现分布。 */
export interface MoneyEffect {
  available: boolean;
  reason?: string;
  prev_date?: string;
  sample?: number;
  avg?: number | null;
  median?: number | null;
  positive_rate?: number | null;
  limit_up_again_rate?: number | null;
  source?: string;
  partial?: boolean;
}

/** 连板溢价（aggregate，无个股名）：昨日 2 板以上今日表现 = 高标承接度。 */
export interface ConsecPremium {
  available: boolean;
  reason?: string;
  prev_date?: string;
  sample?: number;
  avg?: number | null;
  median?: number | null;
  positive_rate?: number | null;
  source?: string;
  partial?: boolean;
}

/** 情绪周期（STIPhase 辅助读数，⚠️ 相对读数无绝对含义，不进 AI/journal 盖章）。 */
export interface CyclePosition {
  available: boolean;
  reason?: string;
  window?: number;
  trough_date?: string;
  trough_score?: number;
  current_score?: number;
  day_n?: number;
  rising?: boolean;
  trend?: string;
  pctile?: number | null;
}

/** 派生情绪指标 aggregate（build_metrics）。 */
export interface EmotionMetrics {
  date: string;
  prev_date?: string;
  money_effect: MoneyEffect;
  consec_premium: ConsecPremium;
  cycle?: CyclePosition;
  rendered?: string;
  disclaimer?: string;
}

/** 连板溢价按股明细（带 code/name，独立路由，不进 AI context）。 */
export interface ConsecPremiumDetailRow {
  code: string;
  name: string;
  prev_boards: number | null;
  ret: number | null;
}

/** 连板溢价按股明细响应（带 code/name，独立路由，不进 AI context）。 */
export interface ConsecPremiumDetailResponse {
  date: string;
  available: boolean;
  reason?: string;
  prev_date?: string;
  count: number;
  detail: ConsecPremiumDetailRow[];
}

/** 取派生情绪指标 aggregate（无个股名）。date 缺省取最近交易日。 */
export function getEmotionMetrics(date?: string): Promise<EmotionMetrics> {
  const qs = date ? `?date=${encodeURIComponent(date)}` : "";
  return request<EmotionMetrics>(`/limitup/emotion-metrics${qs}`);
}

/** 取连板溢价按股明细（带个股名，不进 AI context）。date 缺省取最近交易日。 */
export function getConsecPremiumDetail(date?: string): Promise<ConsecPremiumDetailResponse> {
  const qs = date ? `?date=${encodeURIComponent(date)}` : "";
  return request<ConsecPremiumDetailResponse>(`/limitup/consec-premium-detail${qs}`);
}
