// S013 T6: 打板工作流 5 helpers（从 api.ts 915-944 拆出），失败返 null 不抛。
import { get, request } from "./client";
import type { WorkflowStatus, PreMarketBriefing, PreMarketRefreshResponse, IntradayData, BombAlertItem, PostMarketReport } from "./types";

// Workflow status — 失败返 null（不抛），故包 try/catch（S013 T2：原裸 fetch 改走 get，
// 顺带修 auth 部署下不发 Bearer；手动 data?.data 解包由 get 的 payload?.data ?? payload 覆盖）。
export async function getWorkflowStatus(): Promise<WorkflowStatus | null> {
  try { return await get<WorkflowStatus>("/workflow/status"); } catch { return null; }
}

// Pre-market briefing
export async function getPreMarketBriefing(): Promise<PreMarketBriefing | null> {
  // S026: 后端异步化后返 {status, factors?(done), data_date, as_of, market_emotion, run_id, msg?(idle), error?(error)}
  try { return await get<PreMarketBriefing>("/workflow/pre-market"); } catch { return null; }
}

// Pre-market refresh（S026）: 触发后台异步采集，立即返 run_id + status=running
export async function refreshPreMarket(date?: string): Promise<PreMarketRefreshResponse | null> {
  try {
    const path = date ? `/workflow/pre-market/refresh?date=${date}` : "/workflow/pre-market/refresh";
    return await request<PreMarketRefreshResponse>(path, "POST");
  } catch { return null; }
}

// Intraday monitor
export async function getIntradayData(): Promise<IntradayData | null> {
  try { return await get<IntradayData>("/workflow/intraday"); } catch { return null; }
}

// Bomb alerts (same endpoint as intraday/alerts but returns array)
export async function getBombAlerts(): Promise<BombAlertItem[] | null> {
  try {
    const data = await get<any>("/workflow/alerts");
    return Array.isArray(data) ? data : (data?.alerts ?? data?.data ?? null);
  } catch { return null; }
}

// Post-market review
export async function getPostMarketReview(date?: string): Promise<PostMarketReport | null> {
  try {
    return await get<PostMarketReport>(date ? `/workflow/post-market?date=${date}` : "/workflow/post-market");
  } catch { return null; }
}
