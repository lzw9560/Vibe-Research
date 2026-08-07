// 候选池漏斗 + 诊断卡 API 客户端（S002）。
// S013 T3：req<T> 已并入 lib/api/client.ts 的 request<T>（语义等价：同鉴权/JSON/
// payload?.data ?? payload 解包/ApiError），此处别名复用，零 call-site 改动。
// 合规：仅客观数据，无方向/参考价位。

import { request as req } from "@/lib/api/client";

// ---- 类型（对齐 backend/candidate_funnel/models.py）----
export interface Announcement { title: string; date: string; type?: string | null }
export interface IndicatorSet {
  code: string; name: string;
  price?: number | null; change_pct?: number | null;
  turnover_pct?: number | null; vol_ratio?: number | null; amount_yi?: number | null;
  amplitude_pct?: number | null; limit_up?: number | null; limit_down?: number | null;
  consec_boards?: number | null; seal_rate?: number | null; bomb_rate?: number | null; advance_rate?: number | null;
  main_net_inflow?: number | null; main_net_5d?: number | null; dragon_tiger_inst_net?: number | null; northbound?: number | null;
  announcements: Announcement[]; concepts: string[]; sector_flow?: number | null;
  ma5?: number | null; ma10?: number | null; ma20?: number | null; boll_upper?: number | null; boll_lower?: number | null; macd?: number | null;
  seal_amount?: number | null; auction_open_pct?: number | null;
  missing: Record<string, string>;
}
export type ActivityTier = "冷" | "活跃" | "热";
export interface ActivityAssessment { tier: ActivityTier; rules_applied: string[] }
export interface StabilizationSignals {
  fewer_limit_downs?: boolean | null; volume_stop_falling?: boolean | null;
  main_flow_turning_positive?: boolean | null; board_height_rising?: boolean | null;
  evidence: Record<string, string>;
}
export interface DiagnosisCard {
  code: string; name: string;
  indicators: IndicatorSet;
  activity: ActivityAssessment;
  stabilization: StabilizationSignals;
  risk_flags: string[];
  as_of: string;
}
export interface FilterRecord { code: string; name?: string | null; reason: string }

/** 漏斗层通过候选——code/name 必有；其余按层语义可选（S031 R14：L2 战法层携
 * best_strategy/confidence_value 供 R19 反筛/R22 合成胜率；L3 仓位层携 suggested_pct/
 * matched_strategy；L1 打分层携 gene_score）。 */
export interface PassedItem {
  code: string;
  name: string;
  best_strategy?: string;
  confidence?: string;
  confidence_value?: number;
  suggested_pct?: number;
  matched_strategy?: string;
  gene_score?: number | null;
  reasons?: string[];
}

export interface FunnelLayer {
  layer_id: string; name: string; as_of: string;
  input_count: number; output_count: number;
  filtered_out: FilterRecord[]; output_codes: string[];
  conditions?: string[];
  passed?: PassedItem[];
  data_status?: string | null;
  data_reason?: string | null;
}
export interface BaseThreshold {
  turnover_cold: number; turnover_hot: number; vol_ratio_active: number;
  amount_yi_min: number; amplitude_high: number;
}
export interface ThresholdConfig {
  mode: "auto" | "suggest" | "manual";
  base: BaseThreshold;
  adjustment?: Record<string, unknown> | null;
  sentiment_phase?: string | null;
  effective?: BaseThreshold | null;
}
export interface FunnelResult {
  run_id: string; date: string;
  layers: FunnelLayer[];
  final_candidates: DiagnosisCard[];
  threshold_config: ThresholdConfig;
  sentiment_phase?: string | null;
  as_of: string;
}
export interface FunnelConfigResponse { config: ThresholdConfig; sources: Record<string, boolean> }

// ---- 请求封装：req = client.request（S013 T3 并入）----


export const candidatesApi = {
  runFunnel: (stage = "all", date?: string) =>
    req<FunnelResult>(`/workflow/candidates/funnel?stage=${stage}${date ? `&date=${date}` : ""}`, "POST"),
  listCandidates: (date?: string) =>
    req<DiagnosisCard[]>(`/workflow/candidates${date ? `?date=${date}` : ""}`),
  diagnosis: (code: string, date?: string) =>
    req<DiagnosisCard>(`/workflow/candidates/${code}/diagnosis${date ? `?date=${date}` : ""}`),
  layers: (runId: string, date?: string) =>
    req<FunnelLayer[]>(`/workflow/funnel/layers?run_id=${encodeURIComponent(runId)}${date ? `&date=${date}` : ""}`),
  getConfig: () => req<FunnelConfigResponse>("/workflow/funnel/config"),
  putConfig: (body: Partial<ThresholdConfig> & { sources?: Record<string, boolean> }) =>
    req<FunnelConfigResponse>("/workflow/funnel/config", "PUT", body),
  rerunLayer: (layerId: string, date?: string, body?: Record<string, unknown>) =>
    req<{ layer: FunnelLayer; final_candidates_count: number }>(
      `/workflow/funnel/layers/${layerId}/rerun${date ? `?date=${date}` : ""}`, "PUT", body ?? {}
    ),
  rerunDownstream: (layerId: string, date?: string) =>
    req<{ layers: FunnelLayer[]; final_candidates: DiagnosisCard[] }>(
      `/workflow/funnel/layers/${layerId}/rerun-downstream${date ? `?date=${date}` : ""}`, "POST"
    ),
};
