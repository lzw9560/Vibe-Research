// S178: OFI 盘中数据只读看板 hook（staleTime 30s，OFI 3min 采集一次，30s stale 平衡新鲜度与节流）。
import { useQuery } from "@tanstack/react-query";
import { api } from "@/lib/api";
import type { OfiResponse } from "@/lib/intraday-ofi-contract";
import type { Opts } from "./types";

export function useIntradayOfi(
  date: string,
  code?: string,
  limit = 2000,
  options?: Opts<OfiResponse>,
) {
  return useQuery({
    queryKey: ["intraday-ofi", date, code ?? "", limit] as const,
    queryFn: () => api.intradayOfi(date, code, limit),
    staleTime: 30_000,
    ...options,
  });
}
