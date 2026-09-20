// S218 C4: ValidatedEdgeCard 数据 hook——/api/signals/status。
// S218 #9: 加 daily（结构化当日信号）+ recordManualTrade（手动交易回录）。
// S221: 加 manualTrades（历史回录 + delivery leak 标记）+ deliveryFireStatus（推送状态灯）。
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { api } from "@/lib/api";
import type {
  SignalsStatusResponse,
  SignalsDailyResponse,
  ManualTradeInput,
  ManualTradeResponse,
  ManualTradesResponse,
} from "@/lib/api/types";
import { useScheduledTasksStatus, type ScheduledTaskStatus } from "./scheduledTasks";
import type { Opts } from "./types";

const SIGNALS_STALE_MS = 60 * 1000;

export function useSignalsStatus(options?: Opts<SignalsStatusResponse>) {
  return useQuery({
    queryKey: ["signals", "status"] as const,
    queryFn: () => api.signalsStatus(),
    staleTime: SIGNALS_STALE_MS,
    ...options,
  });
}

export function useSignalsDaily(options?: Opts<SignalsDailyResponse>) {
  return useQuery({
    queryKey: ["signals", "daily"] as const,
    queryFn: () => api.signalsDaily(),
    staleTime: SIGNALS_STALE_MS,
    ...options,
  });
}

/** S218 #9: 记录手动真实交易 → 后端算 actual vs reference P&L + delivery_leak。 */
export function useRecordManualTrade() {
  const qc = useQueryClient();
  return useMutation<ManualTradeResponse, Error, ManualTradeInput>({
    mutationFn: (body) => api.signalsManualTrade(body),
    onSuccess: () => {
      // 回录后失效 manual-trades 列表（daily 不变故不 invalidate）
      qc.invalidateQueries({ queryKey: ["signals", "manual-trades"] });
    },
  });
}

/** S221: 已录手动交易历史（倒序）——周度复盘 + delivery leak 标记共用。 */
export function useSignalsManualTrades(limit = 50, options?: Opts<ManualTradesResponse>) {
  return useQuery({
    queryKey: ["signals", "manual-trades", limit] as const,
    queryFn: () => api.signalsManualTrades(limit),
    staleTime: SIGNALS_STALE_MS,
    ...options,
  });
}

/** S221 gap1: delivery cron fire 状态灯——复用 useScheduledTasksStatus(always-on)，
 * filter daily_report task。today_status 映射 fire ✓/✗/⚠，notify_on_success 标飞书配置态。
 * 不臆造"已送达"（无 webhook receipt，只标配置态）。 */
export function useDeliveryFireStatus() {
  // always-on（enabled=true）→ 60s 轮询；DeliveryStatusCard 须随时反映 fire 态
  const q = useScheduledTasksStatus(true);
  const tasks = q.data ?? [];
  const dailyReport = tasks.find((t: ScheduledTaskStatus) => t.task_type === "daily_report") ?? null;
  const weeklyReview = tasks.find((t: ScheduledTaskStatus) => t.task_type === "weekly_review") ?? null;
  return {
    ...q,
    dailyReport,
    weeklyReview,
  };
}
