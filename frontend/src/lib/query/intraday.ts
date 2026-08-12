// S063 T18：盘中情绪辅助决策 TanStack Query hooks。
// 5 个 hooks 对应 5 个端点。刷新频率：Layer 1/2 每 5 分钟，Layer 3/4 随 Layer 1 联动。
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api } from "@/lib/api";
import type { Opts } from "./types";
import type {
  IntradaySnapshot,
  IntradayHolding,
  IntradayScenario,
  IntradayHistoryReference,
  T1ProjectionScenario,
} from "@/lib/api";

/** Layer 1：最新 snapshot（4 维度+分数+趋势+色带）。每 5 分钟刷新。 */
export function useIntradayLatest(options?: Opts<IntradaySnapshot | null>) {
  return useQuery({
    queryKey: ["intraday", "sentiment", "latest"] as const,
    queryFn: () => api.intradaySentimentLatest(),
    refetchInterval: 5 * 60 * 1000,
    ...options,
  });
}

/** Layer 1：当日全量 timeline。随 latest 联动（同 prefix）。 */
export function useIntradayTimeline(options?: Opts<{ date: string; snapshots: IntradaySnapshot[] } | null>) {
  return useQuery({
    queryKey: ["intraday", "sentiment", "timeline"] as const,
    queryFn: () => api.intradaySentimentTimeline(),
    refetchInterval: 5 * 60 * 1000,
    ...options,
  });
}

/** Layer 2：持仓×情绪联动表。每 5 分钟刷新。 */
export function useIntradayHoldings(
  options?: Opts<{ holdings: IntradayHolding[]; current_zone: string; dual_pressure_count: number; message?: string } | null>,
) {
  return useQuery({
    queryKey: ["intraday", "sentiment", "holdings"] as const,
    queryFn: () => api.intradaySentimentHoldings(),
    refetchInterval: 5 * 60 * 1000,
    ...options,
  });
}

/** Layer 3：条件场景推演。随 latest 联动。 */
export function useIntradayScenarios(
  options?: Opts<{
    current: { score: number; trend: string; zone: string };
    scenarios: IntradayScenario[];
    history_reference: IntradayHistoryReference;
  } | null>,
) {
  return useQuery({
    queryKey: ["intraday", "sentiment", "scenarios"] as const,
    queryFn: () => api.intradaySentimentScenarios(),
    refetchInterval: 5 * 60 * 1000,
    ...options,
  });
}

/** Layer 4：T+1 预判（14:30 后可用）。随 latest 联动。 */
export function useIntradayT1Projection(
  options?: Opts<{
    status: string;
    current_score?: number;
    scenarios?: T1ProjectionScenario[];
    disclaimer?: string;
    as_of?: string;
    message?: string;
  } | null>,
) {
  return useQuery({
    queryKey: ["intraday", "sentiment", "t1-projection"] as const,
    queryFn: () => api.intradaySentimentT1Projection(),
    refetchInterval: 5 * 60 * 1000,
    ...options,
  });
}

/** 手动触发一次采样（调试用）。invalidate latest/timeline 让前端立即刷新。 */
export function useTriggerIntradaySnapshot() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: () => api.intradaySentimentSnapshot(),
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: ["intraday", "sentiment"] });
    },
  });
}
