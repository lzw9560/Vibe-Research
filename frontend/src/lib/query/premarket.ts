// lib/query/premarket.ts — S071 盘前选股（breakout 弱信号 + 风控）TanStack Query hook。
// §44：breakout day-cluster lift=1.72x <2x 非 validated；honest_label 标弱信号，edge 主来自风控。
import { useQuery } from "@tanstack/react-query";
import { request } from "@/lib/api/client";
import type { Opts } from "./types";

export interface PremarketCandidate {
  code: string;
  name: string;
  breakout_score: number;
  breakout_binary: number;
  t1_close: number;
  t1_date: string;
  entry_ref: number;
  stop_loss: number;
  take_profit: number;
  position_pct: number;
}

export interface PremarketRiskParams {
  position_pct: number;
  max_positions: number;
  stop_loss_pct: number;
  take_profit_pct: number;
  max_hold_days: number;
}

export interface PremarketSelectionData {
  target_date: string;
  honest_label: string;
  risk_params: PremarketRiskParams;
  calendar_multiplier: number;
  calendar_reason: string;
  market_note: string;
  candidates: PremarketCandidate[];
  count: number;
}

/** S071 盘前选股——GET /api/strategy/premarket-selection?date=&top_n=&min_score=。
 * breakout_20d 排序 → top-N + 风控具体价。弱信号，前向测试期间不投真金。 */
export function usePremarketSelection(
  date: string,
  topN = 20,
  minScore = 0.9,
  options?: Opts<PremarketSelectionData>,
) {
  return useQuery({
    queryKey: ["strategy", "premarket-selection", date, topN, minScore] as const,
    queryFn: () =>
      request<PremarketSelectionData>(
        `/strategy/premarket-selection?date=${date}&top_n=${topN}&min_score=${minScore}`,
      ),
    enabled: Boolean(date),
    staleTime: 300_000, // 5min（日级 kline，盘前不需高频）
    ...options,
  });
}
