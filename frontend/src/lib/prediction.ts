// 短线预测级联 + 盘中研判框架 API 客户端（S017）。
// 合规：后端响应恒带 disclaimer「研究参考·不构成投资建议」，本层保留全信封
// （不走 lib/api request 的 .data 解包），确保免责声明直达 UI。

import { ApiError, authHeaders } from "@/lib/api";

export interface PredictionSnapshot {
  head: string;
  stage: string;
  t: string;
  prob: number;
  quantiles: number[];
  shap_topk: [string, number][];
  features_used: string[];
  backends: string[];
  model_version: string;
}

export interface PredictionEnvelope {
  data: PredictionSnapshot | null;
  status: "ok" | "no_snapshot";
  head: string;
  stage: string;
  t: string;
  disclaimer: string;
}

export interface IntradayFrameworkItem {
  key: string;
  label: string;
  how_to_read: string;
  reference: string;
  current_value: number | string | null;
  hint: string;
}

export interface IntradayFrameworkEnvelope {
  head: string;
  stage: "s4";
  items: IntradayFrameworkItem[];
  disclaimer: string;
}

// 保留全信封（含 disclaimer），不解包 .data。
async function fetchEnvelope<T>(path: string): Promise<T> {
  let resp: Response;
  try {
    resp = await fetch(`/api${path}`, { headers: authHeaders() });
  } catch {
    throw new ApiError("连接不到后端，请先启动 backend（uvicorn app:app --port 8900）", 0);
  }
  let payload: any = null;
  try {
    payload = await resp.json();
  } catch {
    /* 非 JSON */
  }
  if (!resp.ok) {
    if (resp.status === 401) {
      throw new ApiError("后端开启了访问鉴权（VR_API_KEY）：请在「接入 AI」页填写密钥", 401);
    }
    throw new ApiError(payload?.detail || `HTTP ${resp.status}`, resp.status);
  }
  return payload as T;
}

export function fetchPrediction(
  head: string,
  stage: "s1" | "s2" | "s3",
  date?: string
): Promise<PredictionEnvelope> {
  const params = new URLSearchParams({ stage });
  if (date) params.set("date", date);
  return fetchEnvelope<PredictionEnvelope>(
    `/prediction/${encodeURIComponent(head)}?${params.toString()}`
  );
}

export function fetchIntradayFramework(head = "short_sector"): Promise<IntradayFrameworkEnvelope> {
  return fetchEnvelope<IntradayFrameworkEnvelope>(
    `/prediction/intraday-framework?head=${encodeURIComponent(head)}`
  );
}

// 免责墙 opt-in（localStorage）。首次进页面前确认「研究参考·不构成投资建议」。
const DISCLAIMER_KEY = "vr-prediction-disclaimer-accepted";

export function isDisclaimerAccepted(): boolean {
  try {
    return localStorage.getItem(DISCLAIMER_KEY) === "1";
  } catch {
    return false;
  }
}

export function acceptDisclaimer() {
  try {
    localStorage.setItem(DISCLAIMER_KEY, "1");
  } catch {
    /* 隐私模式 */
  }
}
