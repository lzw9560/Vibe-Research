// S013 T6: 打板工作流 5 helpers（从 api.ts 915-944 拆出），失败返 null 不抛。
import { get, request } from "./client";
import type {
  WorkflowStatus, PreMarketBriefing, PreMarketDates, PreMarketRefreshResponse, IntradayData, BombAlertItem, PostMarketReport,
  WorkflowState, WorkflowStateList, TransitionRequest, WorkflowStateHistoryItem,
  FirstBoardCandidatesResponse,
} from "./types";

// Workflow status — 失败返 null（不抛），故包 try/catch（S013 T2：原裸 fetch 改走 get，
// 顺带修 auth 部署下不发 Bearer；手动 data?.data 解包由 get 的 payload?.data ?? payload 覆盖）。
export async function getWorkflowStatus(): Promise<WorkflowStatus | null> {
  try { return await get<WorkflowStatus>("/workflow/status"); } catch { return null; }
}

// Pre-market briefing（S048：date 可选——历史视角按日取，级联降级由后端负责）
export async function getPreMarketBriefing(date?: string): Promise<PreMarketBriefing | null> {
  // 后端异步化后返 {status, factors?(done), data_date, as_of, market_emotion, run_id, msg?(idle), error?(error)}
  // S048 追加：no_snapshot 态 / from_snapshot / funnel_layers / is_backfill
  try {
    return await get<PreMarketBriefing>(
      date ? `/workflow/pre-market?date=${date}` : "/workflow/pre-market",
    );
  } catch { return null; }
}

// S048 R6: 有快照的日期降序列表（日期选择器标注用）
export async function getPreMarketDates(): Promise<PreMarketDates | null> {
  try { return await get<PreMarketDates>("/workflow/pre-market/dates"); } catch { return null; }
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

// ============ S033：工作流状态机（七态落库 + 手动流转） ============
// 后端返 {data: ...}，get/request 自动解包 .data；失败返 null 不抛（本文件既有约定）。

/** GET /api/workflow/state?date= → 全日状态列表 + 按态计数。 */
export async function getWorkflowStates(date?: string): Promise<WorkflowStateList | null> {
  try {
    const path = date ? `/workflow/state?date=${date}` : "/workflow/state";
    return await get<WorkflowStateList>(path);
  } catch { return null; }
}

/** GET /api/workflow/state/{code}?date= → 单股状态 + allowed_targets（无记录后端返 404 → 此处 null）。 */
export async function getWorkflowState(code: string, date?: string): Promise<WorkflowState | null> {
  try {
    const path = date ? `/workflow/state/${code}?date=${date}` : `/workflow/state/${code}`;
    return await get<WorkflowState>(path);
  } catch { return null; }
}

/** POST /api/workflow/state/transition → 流转后返回新状态行（含价格/战法）。 */
export async function transitionWorkflowState(req: TransitionRequest): Promise<WorkflowState | null> {
  try {
    return await request<WorkflowState>("/workflow/state/transition", "POST", req);
  } catch { return null; }
}

/** GET /api/workflow/state/{code}/history?date= → 流转历史数组（升序）。 */
export async function getWorkflowStateHistory(code: string, date?: string): Promise<WorkflowStateHistoryItem[] | null> {
  try {
    const path = date
      ? `/workflow/state/${code}/history?date=${date}`
      : `/workflow/state/${code}/history`;
    const data = await get<{ code: string; date: string | null; history: WorkflowStateHistoryItem[] }>(path);
    return data?.history ?? null;
  } catch { return null; }
}

// S075 首板流候选池——GET /api/workflow/first-board/candidates?date=
// 后端 run_first_board_filter 产出（首板过滤+三层剔除+9维度评分+落盘）。
// §44 诚实标注：9 维度评分未 validated 仅参考；阈值/权重待回测校准。
// from_cache=true 时为历史快照（zt_pool_count/first_board_count/excluded/env_flags 可能空）。
export async function getFirstBoardCandidates(date?: string): Promise<FirstBoardCandidatesResponse | null> {
  try {
    const path = date ? `/workflow/first-board/candidates?date=${date}` : "/workflow/first-board/candidates";
    return await get<FirstBoardCandidatesResponse>(path);
  } catch { return null; }
}

// S075 首板流可用历史日期列表——GET /api/workflow/first-board/dates
// 返回有快照的日期降序（YYYY-MM-DD），供日期选择器标注可用日期。
export async function getFirstBoardDates(): Promise<{ dates: string[]; count: number } | null> {
  try {
    return await get<{ dates: string[]; count: number }>("/workflow/first-board/dates");
  } catch { return null; }
}

// ============ S092 R9：dateTriplet（交易日锚 F + 时段推断三视图） ============
// 纯后端日期计算（vr_paths + datetime.now(BEIJING_TZ)），零外部请求。
// 前端 useMarketClock 用 next_*_at - Date.now() 算 setTimeout 延时（R14），
// 零本地时区判断。失败直接抛——消费方（useDateTriplet hook）用 react-query
// retry 处理；与上面"返 null 不抛"约定不同（dateTriplet 是基础设施，失败应让
// 上层感知而非静默降级为 null 导致整页日期错乱）。
export interface DateTripletResponse {
  F: string;
  review: string;
  today: string;
  forward: string;
  stage: "pre_market" | "intraday" | "post_transition" | "post_market" | "non_trading";
  is_trading_day: boolean;
  review_advanced: boolean;
  server_now: string;
  next_review_advance_at: number;
  next_f_advance_at: number;
  non_trading: boolean;
}

export async function getDateTriplet(date?: string): Promise<DateTripletResponse> {
  const path = date ? `/workflow/date-triplet?date=${date}` : "/workflow/date-triplet";
  return await get<DateTripletResponse>(path);
}
