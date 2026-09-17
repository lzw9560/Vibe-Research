// S204 T9: 多日跟踪 TanStack Query hooks（candidate_tracking_pool + indicator_snapshots 只读看板）。
import { useQuery } from "@tanstack/react-query";
import { api } from "@/lib/api";
import type { Opts } from "./types";
import type { TrackingPoolResponse, TrackingSnapshotsResponse } from "@/lib/api";

// 活跃 track 列表（默认 current_status='tracking'）。30min 刷新（tracking 级 label 演进慢）。
export function useTrackingPool(
  status = "tracking",
  options?: Opts<TrackingPoolResponse>,
) {
  return useQuery({
    queryKey: ["tracking", "pool", status] as const,
    queryFn: () => api.trackingPool(status),
    refetchInterval: 30 * 60 * 1000,
    ...options,
  });
}

// 单 code 指标快照序列（按 date asc），供多日跟踪 aging/escalation 判定看指标演进。
export function useTrackingSnapshots(
  code: string | null,
  upTo?: string,
  options?: Opts<TrackingSnapshotsResponse>,
) {
  return useQuery({
    queryKey: ["tracking", "snapshots", code, upTo] as const,
    enabled: !!code,
    queryFn: () => api.trackingSnapshots(code as string, upTo),
    ...options,
  });
}
