// S005 中长线价值选股漏斗 — API 客户端
// S013 T4：call<T> 已并入 lib/api/client.ts 的 request<T>。后端 value-funnel 端点
// 全返裸对象（无 {data:} 包封），故 request 的 payload?.data ?? payload 解包在此
// 回退到 payload，与原 call 的「不解包」行为等价（发散点均不触发）。别名复用，零 call-site 改动。
import { request as call } from "@/lib/api/client";

// ---------- 类型 ----------

export interface QualityMetric {
  index: number; name: string; value: number | null; threshold: number | null;
  passed: boolean | null; inapplicable: boolean; inapplicable_reason: string | null;
  exempt: boolean; exempt_rule: string | null; evidence: string; missing: boolean;
}

export interface MoatSignals {
  gross_margin_persistence: boolean | null; market_share_rank: number | null;
  roe_stability: number | null; identifiable_moat: string[];
  note: string;
}

export interface QualityAssessment {
  metrics: QualityMetric[]; moat: MoatSignals;
  pass_count: number; inapplicable_count: number;
  pass_rate_absolute: number; pass_rate_adjusted: number | null;
  data_years: number | null; data_years_note: string | null;
  as_of: string;
}

export interface CompanyAnalysis {
  code: string; name: string; business_model: string; moat_evidence: string;
  financials_summary: string; valuation_position: string;
  risks: string[]; counter_arguments: string[]; as_of: string;
}

export interface MasterPerspective {
  master: string; framework: string; data_skeleton: string;
  key_questions: string[]; ai_text: string | null;
}

export interface DeepAnalysisSkeleton {
  code: string; name: string; perspectives: MasterPerspective[];
  as_of: string; ai_pending: boolean;
}

export interface ValueFilterRecord { code: string; name: string | null; layer: string; reason: string }

export interface ValueFunnelLayer {
  layer_id: string; name: string; as_of: string;
  input_count: number; output_count: number;
  filtered_out: ValueFilterRecord[]; output_codes: string[];
}

export interface ValueFunnelResult {
  run_id: string; direction: string; layers: ValueFunnelLayer[];
  l2_assessments: Record<string, QualityAssessment>;
  l3_analyses: Record<string, CompanyAnalysis>;
  l4_finals: DeepAnalysisSkeleton[];
  as_of: string;
}

export interface LLMConfig { provider?: string; baseURL?: string; apiKey?: string; model: string }

// ---------- 调用 ----------

// ---------- 请求封装：call = client.request（S013 T4 并入）----------


export const scanValueFunnel = (direction: string) =>
  call<{ candidates: { code: string; name: string }[] }>("/value-funnel/scan", "POST", { direction });

export const runValueFunnel = (direction: string, stage = "all") =>
  call<ValueFunnelResult>("/value-funnel/run", "POST", { direction, stage });

export const getValueFunnelLayers = (runId: string) =>
  call<ValueFunnelLayer[]>(`/value-funnel/layers?run_id=${encodeURIComponent(runId)}`);

export const getQuality = (code: string) =>
  call<QualityAssessment>(`/value-funnel/${code}/quality`);

export const getAnalysis = (code: string) =>
  call<CompanyAnalysis>(`/value-funnel/${code}/analysis`);

export const deepAi = (code: string, llm: LLMConfig) =>
  call<DeepAnalysisSkeleton>(`/value-funnel/${code}/deep-ai`, "POST", llm);
