// S063 T18：盘中情绪辅助决策 TanStack Query hooks。
// 5 个 hooks 对应 5 个端点。刷新频率按数据源新鲜度错峰，且只在 A 股交易时段轮询
// （非交易时段数据不变，停拉既省请求又不给上游添压——同 coach.ts gating 范式）。
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
import { isTradingHours } from "@/hooks/useLiveQuotes";

// ─── 错峰间隔（按数据源新鲜度，证据来自后端 _IntradaySampler）──────────────
// 后端采样器 asyncio task 仅交易日 09:25-15:30 运行，且「防同分钟重复采样」→
// ring buffer 至多 1 sample/min。latest/timeline/scenarios/t1 都读 ring buffer
// 或由 snapshot 派生，故 <60s 轮询即冗余读（5s 会 11x 浪费）。holdings 每次
// 调 astock.tencent_quote 拉实时报价（level-1 3s 一笔），30s 兼顾新鲜度与限流。
// 不同周期自然错峰，避免 5 个 hook 同拍齐发。
const LATEST_INTERVAL_MS = 60_000; // Layer 1 实时速览条：匹配采样率（≤1/min）
const TIMELINE_INTERVAL_MS = 120_000; // 当日走势图：历史趋势，2min 足够
const HOLDINGS_INTERVAL_MS = 30_000; // 持仓×情绪：实时报价，30s 平衡
const SCENARIOS_INTERVAL_MS = 90_000; // 条件场景推演：派生数据，90s
const T1_INTERVAL_MS = 120_000; // T+1 预判：最不紧急，2min

/**
 * 构造交易时段轮询、非交易时段停拉的 refetchInterval（同 coach.ts isInCoachWindow 范式）。
 *
 * TanStack Query 的 refetchInterval 接受 `false` 表示「不自动 refetch」——
 * 收盘后 isTradingHours() 返 false，hook 停拉；手动刷新按钮仍可用。
 * 传入各自间隔实现错峰，避免常量同拍齐发。
 */
export function makeIntradayInterval(ms: number): () => number | false {
  return () => (isTradingHours() ? ms : false);
}

/**
 * 构造「盘中快、盘后慢但不停」的 refetchInterval。
 *
 * 与 makeIntradayInterval 的区别：盘后返回 offHoursMs（继续慢轮询）而非 false，
 * 适合盘后仍可能更新的派生数据（如情绪天气的熔断/赦免状态、当日走势趋势）。
 * 盘中段仍用 isTradingHours() 判定（beijingNow，海外时区正确）。
 */
export function makeMarketAwareInterval(intradayMs: number, offHoursMs: number): () => number {
  return () => (isTradingHours() ? intradayMs : offHoursMs);
}

/** Layer 1：最新 snapshot（4 维度+分数+趋势+色带）。交易时段 60s 刷新。 */
export function useIntradayLatest(options?: Opts<IntradaySnapshot | null>) {
  return useQuery({
    queryKey: ["intraday", "sentiment", "latest"] as const,
    queryFn: () => api.intradaySentimentLatest(),
    refetchInterval: makeIntradayInterval(LATEST_INTERVAL_MS),
    ...options,
  });
}

/** Layer 1：当日全量 timeline。随 latest 联动（同 prefix）。交易时段 120s。 */
export function useIntradayTimeline(options?: Opts<{ date: string; snapshots: IntradaySnapshot[] } | null>) {
  return useQuery({
    queryKey: ["intraday", "sentiment", "timeline"] as const,
    queryFn: () => api.intradaySentimentTimeline(),
    refetchInterval: makeIntradayInterval(TIMELINE_INTERVAL_MS),
    ...options,
  });
}

/** Layer 2：持仓×情绪联动表。交易时段 30s 刷新（实时报价驱动，较 Layer 1 更频）。 */
export function useIntradayHoldings(
  options?: Opts<{ holdings: IntradayHolding[]; current_zone: string; dual_pressure_count: number; message?: string } | null>,
) {
  return useQuery({
    queryKey: ["intraday", "sentiment", "holdings"] as const,
    queryFn: () => api.intradaySentimentHoldings(),
    refetchInterval: makeIntradayInterval(HOLDINGS_INTERVAL_MS),
    ...options,
  });
}

/** Layer 3：条件场景推演。随 latest 联动。交易时段 90s。 */
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
    refetchInterval: makeIntradayInterval(SCENARIOS_INTERVAL_MS),
    ...options,
  });
}

/** Layer 4：T+1 预判（14:30 后可用）。随 latest 联动。交易时段 120s。 */
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
    refetchInterval: makeIntradayInterval(T1_INTERVAL_MS),
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
