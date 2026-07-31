// S013 T6: 定时任务/参数配置/LLM env 状态 helpers（从 api.ts 868-913 拆出）。
import { get, request } from "./client";
import type { ScheduledTask, TaskRun, LimitUpParams, AuctionParams, ReviewParams, LlmEnvStatus } from "./types";

// S013 T2：以下端点原裸 fetch，现统一走 client.request/get（鉴权/JSON/解包一致）。
export async function getScheduledTasks(): Promise<ScheduledTask[]> {
  return get<ScheduledTask[]>("/scheduled-tasks");
}
export async function getScheduledTask(id: number): Promise<ScheduledTask> {
  return get<ScheduledTask>(`/scheduled-tasks/${id}`);
}
export async function createScheduledTask(data: Partial<ScheduledTask>): Promise<{ id: number }> {
  return request<{ id: number }>("/scheduled-tasks", "POST", data);
}
export async function updateScheduledTask(id: number, data: Partial<ScheduledTask>): Promise<void> {
  await request<void>(`/scheduled-tasks/${id}`, "PUT", data);
}
export async function deleteScheduledTask(id: number): Promise<void> {
  await request<void>(`/scheduled-tasks/${id}`, "DELETE");
}
export async function runScheduledTaskNow(id: number): Promise<any> {
  return request<any>(`/scheduled-tasks/${id}/run`, "POST");
}
export async function getScheduledTaskRuns(id: number, limit = 50): Promise<TaskRun[]> {
  return get<TaskRun[]>(`/scheduled-tasks/${id}/runs?limit=${limit}`);
}
export async function getScheduledTaskTypes(): Promise<string[]> {
  return get<string[]>("/scheduled-tasks/types");
}
export async function getLlmEnvStatus(): Promise<LlmEnvStatus> {
  return get<LlmEnvStatus>("/settings/llm-env-status");
}
export async function getLimitUpScreenerParams(): Promise<LimitUpParams> {
  return get<LimitUpParams>("/limitup/screener/params");
}
export async function saveLimitUpScreenerParams(params: LimitUpParams): Promise<void> {
  await request<void>("/limitup/screener/params", "POST", params);
}
export async function getAuctionParams(): Promise<AuctionParams> {
  return get<AuctionParams>("/limitup/auction/params");
}
export async function saveAuctionParams(params: AuctionParams): Promise<void> {
  await request<void>("/limitup/auction/params", "POST", params);
}
export async function getReviewParams(): Promise<ReviewParams> {
  return get<ReviewParams>("/review/params");
}
export async function saveReviewParams(params: ReviewParams): Promise<void> {
  await request<void>("/review/params", "POST", params);
}
