// lib/query/limitup.ts — TanStack Query hooks（打板/工作流/调度/参数 只读端点）。S013 T8/T16。
// 类型收紧：Opts<Awaited<ReturnType<typeof api.X|getX>>> 参数化，消 {} 放宽。
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import {
  api,
  getWorkflowStatus,
  getPreMarketBriefing,
  refreshPreMarket,
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
import type { WinRateRecordInput } from "@/lib/api";
import { AUCTION_START_MIN, AUCTION_END_MIN, isWeekday } from "@/lib/auction";

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
    // 盘前简报为日级数据，采集完成(done)后当天稳定；全局 staleTime 30s 对此过短，
    // 导致切页/聚焦反复重发。拉长到 5min（running 轮询走 refetchInterval，不受 staleTime 影响；
    // 手动刷新走 refetch()）。采集中的 idle→running 轮询仍由 refetchInterval 驱动。
    staleTime: 5 * 60_000,
    ...options,
  });
}

// S026: 触发后台异步采集；成功后失效 preMarketBriefing，让轮询立即拉新状态
export function usePreMarketRefresh() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (date?: string) => refreshPreMarket(date),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["limitup", "preMarketBriefing"] }),
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

// ---- S025 胜率追踪 + 竞价监控 ----

// 读 hooks：窗口参数入 queryKey，切窗自动重查（仿 useAuctionTop）。
// queryKey 统一 ["limitup","winrate",...] 前缀，便于 useWinRateRecords 批量 invalidate。
export function useWinRateStats(
  windowSize: number,
  options?: Opts<Awaited<ReturnType<typeof api.winRateStats>>>,
) {
  return useQuery({
    queryKey: ["limitup", "winrate", "stats", windowSize] as const,
    queryFn: () => api.winRateStats(windowSize),
    ...options,
  });
}

export function useWinRateTrends(
  windowSize: number,
  options?: Opts<Awaited<ReturnType<typeof api.winRateTrends>>>,
) {
  return useQuery({
    queryKey: ["limitup", "winrate", "trends", windowSize] as const,
    queryFn: () => api.winRateTrends(windowSize),
    ...options,
  });
}

export function useWinRateAdjustments(
  windowSize: number,
  options?: Opts<Awaited<ReturnType<typeof api.winRateAdjustments>>>,
) {
  return useQuery({
    queryKey: ["limitup", "winrate", "adjustments", windowSize] as const,
    queryFn: () => api.winRateAdjustments(windowSize),
    ...options,
  });
}

export function useWinRateSector(
  sector: string,
  windowSize: number,
  options?: Opts<Awaited<ReturnType<typeof api.winRateSector>>>,
) {
  return useQuery({
    queryKey: ["limitup", "winrate", "sector", sector, windowSize] as const,
    queryFn: () => api.winRateSector(sector, windowSize),
    enabled: !!sector,
    ...options,
  });
}

export function useWinRateStrategy(
  strategy: string,
  windowSize: number,
  options?: Opts<Awaited<ReturnType<typeof api.winRateStrategy>>>,
) {
  return useQuery({
    queryKey: ["limitup", "winrate", "strategy", strategy, windowSize] as const,
    queryFn: () => api.winRateStrategy(strategy, windowSize),
    enabled: !!strategy,
    ...options,
  });
}

// 写 hook：录入交易记录。成功后批量失效 winrate 查询前缀，触发 stats/trends/sector/strategy 刷新。
export function useWinRateRecords() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (records: WinRateRecordInput[]) => api.winRateRecords(records),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["limitup", "winrate"] }),
  });
}

// 竞价窗口判定：周一至五 9:15-9:30（客户端本地时间）。注入 now 便测；驱动 useAuctionMonitor 的 refetchInterval。
export function isInAuctionWindow(now: Date = new Date()): boolean {
  if (!isWeekday(now)) return false; // 周末
  const minutes = now.getHours() * 60 + now.getMinutes();
  return minutes >= AUCTION_START_MIN && minutes <= AUCTION_END_MIN;
}

// 9:25 盘中监控：并行拉 auction/monitor + auction/watchlist；窗口内 15s 刷新，窗口外停。
// refetchInterval 用函数形式，每次轮询时重判窗口边界（组件长驻跨窗时自动停拉/重启）。
export function useAuctionMonitor(
  options?: Opts<
    [Awaited<ReturnType<typeof api.auctionMonitor>>, Awaited<ReturnType<typeof api.auctionWatchlist>>]
  >,
) {
  return useQuery({
    queryKey: ["limitup", "auction", "monitor"] as const,
    // S025 review fix：allSettled 防独立端点 fail-fast 耦合（watchlist 502 不再丢弃已成功的 monitor 信号）
    queryFn: async () => {
      const results = await Promise.allSettled([api.auctionMonitor(), api.auctionWatchlist()]);
      const monitor = results[0].status === "fulfilled" ? results[0].value : [];
      const watchlist = results[1].status === "fulfilled" ? results[1].value : [];
      return [monitor, watchlist] as [typeof monitor, typeof watchlist];
    },
    refetchInterval: () => (isInAuctionWindow() ? 15_000 : false),
    ...options,
  });
}
