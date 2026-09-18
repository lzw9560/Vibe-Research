// S218 C4: ValidatedEdgeCard 数据 hook——/api/signals/status。
// S218 #9: 加 daily（结构化当日信号）+ recordManualTrade（手动交易回录）。
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { api } from "@/lib/api";
import type {
  SignalsStatusResponse,
  SignalsDailyResponse,
  ManualTradeInput,
  ManualTradeResponse,
} from "@/lib/api/types";
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
