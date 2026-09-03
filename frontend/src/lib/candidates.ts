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
  consec_boards?: number | null;
  main_net_inflow?: number | null; main_net_5d?: number | null; dragon_tiger_inst_net?: number | null; northbound?: number | null;
  announcements: Announcement[]; concepts: string[]; sector_flow?: number | null;
  ma5?: number | null; ma10?: number | null; ma20?: number | null; boll_upper?: number | null; boll_lower?: number | null; macd?: number | null;
  seal_amount?: number | null; auction_open_pct?: number | null;
  float_market_cap?: number | null;  // S057：流通市值（元）
  // S084：tencent_quote 扩展 + 板块资金 + 前日成交额（limit_up/limit_down 已有 L14 不重复）
  last_close?: number | null; open?: number | null; change_amt?: number | null;
  pe_ttm?: number | null; mcap_yi?: number | null; pb?: number | null;
  sector_net_inflow?: number | null; sector_inflow?: number | null; sector_outflow?: number | null;
  prev_amount_yi?: number | null;
  // S081 PRD 战法因子（K线派生，后端 build_indicator_set 填）
  max_high_pct?: number | null;       // 当日最高涨幅 = (high/prev_close - 1)*100
  shadow_length_pct?: number | null;  // 上影线长度 = (high/close - 1)*100
  ma_5_status?: string | null;        // MA5 状态
  prev_turnover_pct?: number | null;  // 前日换手率（供 vol_ratio_1d 计算）
  missing: Record<string, string>;
}
export type ActivityTier = "冷" | "活跃" | "热";
export interface ActivityAssessment { tier: ActivityTier; rules_applied: string[] }
export interface StabilizationSignals {
  fewer_limit_downs?: boolean | null; volume_stop_falling?: boolean | null;
  main_flow_turning_positive?: boolean | null; board_height_rising?: boolean | null;
  evidence: Record<string, string>;
}
// S057：八项标准三态判定
export type EightStandardStatus = "pass" | "fail" | "missing";
export interface EightStandardItem {
  key: string;
  label: string;
  status: EightStandardStatus;
  actual?: string | null;
  expected: string;
  note?: string | null;
}
export interface EightStandardResult {
  items: EightStandardItem[];
  fail_count: number;
  missing_count: number;
}
export interface DiagnosisCard {
  code: string; name: string;
  indicators: IndicatorSet;
  activity: ActivityAssessment;
  stabilization: StabilizationSignals;
  risk_flags: string[];
  st_play?: string | null;  // S148：ST carve-out 正向标（摘帽/重组/扭亏），radar 白名单 re-include 的 ST 股带
  first_board_analysis?: {
    scores: Record<string, number>;  // 9 维各分（描述性，-1=数据缺失）
    total: number | null;  // 复合分（§44 未 validated，仅参考）
    market_phase?: string | null;
  } | null;  // S148 Phase 2：首板 9 维评分（仅首板子集带）
  as_of: string;
  eight_standards?: EightStandardResult | null;  // S057
  capped?: boolean;  // S057：未过≥3 → 封顶 55
  cap_reason?: string | null;
  // S084：选股池战法解耦 3 子对象（Q6=B，各默认 null 降级；dict 透传避免跨模型耦合）
  gene_score?: Record<string, unknown> | null;  // 涨停基因完整对象 dump
  pool_item?: Record<string, unknown> | null;   // 涨停池原始 dict
  derived?: Record<string, unknown> | null;     // S070 R7 分时派生
}
export interface FilterRecord { code: string; name?: string | null; reason: string }

/** 漏斗层通过候选——code/name 必有；其余按层语义可选（S031 R14：L2 战法层携
 * best_strategy/confidence_value 供 R19 反筛/R22 合成胜率；L3 仓位层携 suggested_pct/
 * matched_strategy；L1 打分层携 gene_score）。S049 D1：全参数 passed（矩阵统一列）。 */
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
  /** S045 R2：R3 触发类型（竞价异动/公告催化/概念联动），供多选筛选 */
  matched_triggers?: string[];
  /** S049 D1：R1+ 连板数 */
  consec_boards?: number | null;
  /** S049 D1：R2+ 量价 */
  turnover_pct?: number | null;
  vol_ratio?: number | null;
  amount_yi?: number | null;
  amplitude_pct?: number | null;
  /** S049 D1：R2+ 资金流 */
  main_net_inflow?: number | null;
  main_net_5d?: number | null;
  northbound?: number | null;
  /** S049 D1：R3+ 催化 */
  auction_open_pct?: number | null;
  catalyst_summary?: string | null;
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
  // S087 R10：缓存优先——读落库 run_funnel 结果（秒开），404 时 fallback POST 实跑
  readFunnelCache: (date?: string) =>
    req<FunnelResult>(`/workflow/candidates/funnel/cache${date ? `?date=${date}` : ""}`),
  listCacheDates: () => req<{ dates: string[] }>("/workflow/candidates/funnel/dates"),
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
