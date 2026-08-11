// lib/query/winrate.ts — S050 W0 影子对照 TanStack Query hook。
// 合规 §0：仅客观算账，不附加方向结论；对照卡挂「历史统计特征，市场有风险，研究参考」。
import { useQuery } from "@tanstack/react-query";
import { request } from "@/lib/api/client";
import type { ShadowComparison } from "@/lib/api/types";
import type { Opts } from "./types";

/** S050：影子对照——GET /api/winrate/shadow-comparison?window_days=28。
 * follow/feeling/missed 三桶 + 独立性指标（一致率/feeling 胜率）。
 * 5 分钟刷新（行为数据每日结算后变，盘中不变）。 */
export function useShadowComparison(window_days = 28, options?: Opts<ShadowComparison>) {
  return useQuery({
    queryKey: ["winrate", "shadow-comparison", window_days] as const,
    queryFn: () => request<ShadowComparison>(`/winrate/shadow-comparison?window_days=${window_days}`),
    staleTime: 5 * 60 * 1000,
    ...options,
  });
}
