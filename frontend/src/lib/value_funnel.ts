// S005 中长线价值选股漏斗 — API 客户端
import { ApiError, authHeaders } from "@/lib/api";

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

async function call<T>(path: string, method: "GET" | "POST" = "GET", body?: unknown): Promise<T> {
  const headers: Record<string, string> = { ...authHeaders() };
  let resp: Response;
  const opts: RequestInit = { method, headers };
  if (body !== undefined) {
    headers["Content-Type"] = "application/json";
    opts.body = JSON.stringify(body);
  }
  try {
    resp = await fetch(`/api${path}`, opts);
  } catch {
    throw new ApiError("无法连接后端", 0);
  }
  if (!resp.ok) {
    let msg = `${resp.status}`;
    try { msg = (await resp.json()).detail || msg; } catch { /* noop */ }
    throw new ApiError(msg, resp.status);
  }
  return (await resp.json()) as T;
}

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
