// lib/query/limitup.ts — TanStack Query hooks（打板/工作流/调度/参数 只读端点）。S013 T8/T16。
// 类型收紧：Opts<Awaited<ReturnType<typeof api.X|getX>>> 参数化，消 {} 放宽。
import { useQuery } from "@tanstack/react-query";
import {
  api,
  getWorkflowStatus,
  getPreMarketBriefing,
  getIntradayData,
  getBombAlerts,
  getPostMarketReview,
  getScheduledTasks,
  getScheduledTask,
  getScheduledTaskRuns,
  getScheduledTaskTypes,
  getLlmEnvStatus,
  getLimitUpScreenerParams,
  getAuctionParams,
  getReviewParams,
} from "@/lib/api";
import type { Opts } from "./types";

// ---- 打板/竞价/席位 ----

export function useLimitupScreener(date?: string, options?: Opts<Awaited<ReturnType<typeof api.limitupScreener>>>) {
  return useQuery({
    queryKey: ["limitup", "screener", date] as const,
    queryFn: () => api.limitupScreener(date),
    ...options,
  });
}

export function useLimitupAnalysis(code: string, date?: string, options?: Opts<Awaited<ReturnType<typeof api.limitupAnalysis>>>) {
  return useQuery({
    queryKey: ["limitup", "analysis", code, date] as const,
    queryFn: () => api.limitupAnalysis(code, date),
    enabled: !!code,
    ...options,
  });
}

export function useAuctionTop(date?: string, n?: number, options?: Opts<Awaited<ReturnType<typeof api.auctionTop>>>) {
  return useQuery({
    queryKey: ["limitup", "auctionTop", date, n] as const,
    queryFn: () => api.auctionTop(date, n),
    ...options,
  });
}

export function useDailyReview(date?: string, options?: Opts<Awaited<ReturnType<typeof api.dailyReview>>>) {
  return useQuery({
    queryKey: ["limitup", "dailyReview", date] as const,
    queryFn: () => api.dailyReview(date),
    ...options,
  });
}

export function useSeatProfiles(options?: Opts<Awaited<ReturnType<typeof api.seatProfiles>>>) {
  return useQuery({
    queryKey: ["limitup", "seatProfiles"] as const,
    queryFn: () => api.seatProfiles(),
    ...options,
  });
}

export function useSeatProfile(name: string, options?: Opts<Awaited<ReturnType<typeof api.seatProfile>>>) {
  return useQuery({
    queryKey: ["limitup", "seatProfile", name] as const,
    queryFn: () => api.seatProfile(name),
    enabled: !!name,
    ...options,
  });
}

export function useSeatConsensus(stockCode: string, date?: string, options?: Opts<Awaited<ReturnType<typeof api.seatConsensus>>>) {
  return useQuery({
    queryKey: ["limitup", "seatConsensus", stockCode, date] as const,
    queryFn: () => api.seatConsensus(stockCode, date),
    enabled: !!stockCode,
    ...options,
  });
}

// ---- 工作流（返 T | null，useQuery 视 null 为成功数据，不 throwOnError）----

export function useWorkflowStatus(options?: Opts<Awaited<ReturnType<typeof getWorkflowStatus>>>) {
  return useQuery({
    queryKey: ["limitup", "workflowStatus"] as const,
    queryFn: () => getWorkflowStatus(),
    ...options,
  });
}

export function usePreMarketBriefing(options?: Opts<Awaited<ReturnType<typeof getPreMarketBriefing>>>) {
  return useQuery({
    queryKey: ["limitup", "preMarketBriefing"] as const,
    queryFn: () => getPreMarketBriefing(),
    ...options,
  });
}

export function useIntradayData(options?: Opts<Awaited<ReturnType<typeof getIntradayData>>>) {
  return useQuery({
    queryKey: ["limitup", "intradayData"] as const,
    queryFn: () => getIntradayData(),
    ...options,
  });
}

export function useBombAlerts(options?: Opts<Awaited<ReturnType<typeof getBombAlerts>>>) {
  return useQuery({
    queryKey: ["limitup", "bombAlerts"] as const,
    queryFn: () => getBombAlerts(),
    ...options,
  });
}

export function usePostMarketReview(date?: string, options?: Opts<Awaited<ReturnType<typeof getPostMarketReview>>>) {
  return useQuery({
    queryKey: ["limitup", "postMarketReview", date] as const,
    queryFn: () => getPostMarketReview(date),
    ...options,
  });
}

// ---- 定时任务/参数 ----

export function useScheduledTasks(options?: Opts<Awaited<ReturnType<typeof getScheduledTasks>>>) {
  return useQuery({
    queryKey: ["limitup", "scheduledTasks"] as const,
    queryFn: () => getScheduledTasks(),
    ...options,
  });
}

export function useScheduledTask(id: number, options?: Opts<Awaited<ReturnType<typeof getScheduledTask>>>) {
  return useQuery({
    queryKey: ["limitup", "scheduledTask", id] as const,
    queryFn: () => getScheduledTask(id),
    enabled: !!id,
    ...options,
  });
}

export function useScheduledTaskRuns(id: number, limit = 50, options?: Opts<Awaited<ReturnType<typeof getScheduledTaskRuns>>>) {
  return useQuery({
    queryKey: ["limitup", "scheduledTaskRuns", id, limit] as const,
    queryFn: () => getScheduledTaskRuns(id, limit),
    enabled: !!id,
    ...options,
  });
}

export function useScheduledTaskTypes(options?: Opts<Awaited<ReturnType<typeof getScheduledTaskTypes>>>) {
  return useQuery({
    queryKey: ["limitup", "scheduledTaskTypes"] as const,
    queryFn: () => getScheduledTaskTypes(),
    ...options,
  });
}

export function useLlmEnvStatus(options?: Opts<Awaited<ReturnType<typeof getLlmEnvStatus>>>) {
  return useQuery({
    queryKey: ["limitup", "llmEnvStatus"] as const,
    queryFn: () => getLlmEnvStatus(),
    ...options,
  });
}

export function useLimitUpScreenerParams(options?: Opts<Awaited<ReturnType<typeof getLimitUpScreenerParams>>>) {
  return useQuery({
    queryKey: ["limitup", "screenerParams"] as const,
    queryFn: () => getLimitUpScreenerParams(),
    ...options,
  });
}

export function useAuctionParams(options?: Opts<Awaited<ReturnType<typeof getAuctionParams>>>) {
  return useQuery({
    queryKey: ["limitup", "auctionParams"] as const,
    queryFn: () => getAuctionParams(),
    ...options,
  });
}

export function useReviewParams(options?: Opts<Awaited<ReturnType<typeof getReviewParams>>>) {
  return useQuery({
    queryKey: ["limitup", "reviewParams"] as const,
    queryFn: () => getReviewParams(),
    ...options,
  });
}
