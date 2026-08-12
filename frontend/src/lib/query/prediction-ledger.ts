// lib/query/prediction-ledger.ts — S061 预测账本 TanStack Query hook。
// 记系统判断（含未执行的）→ 到期自动验证 → 按来源统计命中率。
// 合规 §0：仅客观算账，挂「历史统计特征，市场有风险，研究参考」。
import { useQuery } from "@tanstack/react-query";
import { request } from "@/lib/api/client";

/** 预测账本条目。 */
export interface PredictionEntry {
  id: number;
  stated_at: string;
  source: string; // funnel_candidate | strategy_hit | manual
  signal_ref: string;
  code: string;
  name: string;
  prediction_type: string; // next_day_premium | strategy_outcome
  expected: string;
  horizon: number;
  due_date: string;
  actual_return: number | null;
  status: string; // pending | hit | miss | expired | voided
  attribution: string;
  verified_at: string | null;
}

/** 命中率分桶统计。 */
export interface PredictionStat {
  source: string;
  total: number;
  hit: number;
  miss: number;
  voided: number;
  hit_rate: number | null;
  sample_sufficient: boolean; // n>=10
  verified: number;
}

interface LedgerResponse {
  data: PredictionEntry[];
  stats: PredictionStat[];
  disclaimer: string;
}

/** S061：预测账本——GET /api/prediction-ledger?days=30&source=
 *  列表 + 按 source 命中率分桶；n<10 标注 sample_sufficient=false。 */
export function usePredictionLedger(days = 30, source = "", options?: { enabled?: boolean }) {
  const params = new URLSearchParams({ days: String(days) });
  if (source) params.set("source", source);
  return useQuery({
    queryKey: ["prediction-ledger", days, source] as const,
    queryFn: () => request<LedgerResponse>(`/prediction-ledger?${params}`),
    staleTime: 60 * 1000,
    enabled: options?.enabled ?? true,
  });
}
