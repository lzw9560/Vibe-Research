// S013 T6: 打板工作流 5 helpers（从 api.ts 915-944 拆出），失败返 null 不抛。
import { get } from "./client";
import type { WorkflowStatus, PreMarketReport, IntradayData, BombAlertItem, PostMarketReport } from "./types";

// Workflow status — 失败返 null（不抛），故包 try/catch（S013 T2：原裸 fetch 改走 get，
// 顺带修 auth 部署下不发 Bearer；手动 data?.data 解包由 get 的 payload?.data ?? payload 覆盖）。
export async function getWorkflowStatus(): Promise<WorkflowStatus | null> {
  try { return await get<WorkflowStatus>("/api/workflow/status"); } catch { return null; }
}

// Pre-market briefing
export async function getPreMarketBriefing(): Promise<PreMarketReport | null> {
  try { return await get<PreMarketReport>("/api/workflow/pre-market"); } catch { return null; }
}

// Intraday monitor
export async function getIntradayData(): Promise<IntradayData | null> {
  try { return await get<IntradayData>("/api/workflow/intraday"); } catch { return null; }
}

// Bomb alerts (same endpoint as intraday/alerts but returns array)
export async function getBombAlerts(): Promise<BombAlertItem[] | null> {
  try {
    const data = await get<any>("/api/workflow/alerts");
    return Array.isArray(data) ? data : (data?.alerts ?? data?.data ?? null);
  } catch { return null; }
}

// Post-market review
export async function getPostMarketReview(date?: string): Promise<PostMarketReport | null> {
  try {
    return await get<PostMarketReport>(date ? `/api/workflow/post-market?date=${date}` : "/api/workflow/post-market");
  } catch { return null; }
}
