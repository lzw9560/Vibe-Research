// lib/query/strategy.ts — 按战法回测 TanStack Query hook（S031 R22）。
// 合规 §0：仅搬运客观回测数据，不附加方向；胜率属历史统计特征。
import { useQuery } from "@tanstack/react-query";
import { request } from "@/lib/api/client";
import type { Opts } from "./types";

export interface StrategyBacktestItem {
  strategy: string;
  strategy_code: string;
  win_rate: number;
  avg_return: number;
  sample_size: number;
  available_days: number;
}

/** S031 R22：按战法回测——GET /api/strategy/backtest?lookback_days。
 * request 解包 .data → 返 8 战法真实回测胜率数组（每项含 available_days）。结果 12h 后端缓存。 */
export function useStrategyBacktest(lookback_days = 60, options?: Opts<StrategyBacktestItem[]>) {
  return useQuery({
    queryKey: ["strategy", "backtest", lookback_days] as const,
    queryFn: () => request<StrategyBacktestItem[]>(`/strategy/backtest?lookback_days=${lookback_days}`),
    ...options,
  });
}

/** 合成 historical_win_rate 公式（limitup_strategy.py:685）：min(confidence*0.8+0.2, 0.95)。
 * 供 WinRateComparePanel 右列重算（标注"估算"），与真实回测对比。 */
export function syntheticWinRate(confidence: number): number {
  return Math.min(confidence * 0.8 + 0.2, 0.95);
}
