// S218 C4: ValidatedEdgeCard 数据 hook——/api/signals/status。
import { useQuery } from "@tanstack/react-query";
import { api } from "@/lib/api";
import type { SignalsStatusResponse } from "@/lib/api/types";
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
