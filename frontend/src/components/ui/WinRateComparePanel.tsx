import type { StrategyBacktestItem } from "@/lib/query/strategy";
import { syntheticWinRate } from "@/lib/query/strategy";
import type { PassedItem } from "@/lib/candidates";
import { GlassCard } from "@/components/ui/GlassCard";
import { SectionHeader } from "@/components/ui/SectionHeader";
import { Skeleton } from "@/components/ui/Skeleton";

interface Props {
  backtest?: StrategyBacktestItem[];
  /** L2 战法层 passed（携 best_strategy + confidence_value）——供合成胜率重算。 */
  l2Passed?: PassedItem[];
  loading?: boolean;
}

/** S031 R22：战法胜率对比——左列真实回测（R20）/ 右列合成 historical_win_rate（标注"估算"）。
 * 合成公式 min(confidence_value*0.8+0.2, 0.95)（limitup_strategy.py:685），按战法取均值，
 * 与真实回测并列对比，让用户看清合成 vs 真实差异。 */
export function WinRateComparePanel({ backtest, l2Passed, loading }: Props) {
  // 合成胜率按战法聚合（当日命中各股的 confidence_value → 公式 → 均值）
  const synth: Record<string, { sum: number; n: number }> = {};
  for (const p of l2Passed ?? []) {
    const s = p.best_strategy;
    if (!s) continue;
    const v = syntheticWinRate(p.confidence_value ?? 0);
    synth[s] ??= { sum: 0, n: 0 };
    synth[s].sum += v;
    synth[s].n += 1;
  }
  const synthRate = (name: string): number | null => {
    const e = synth[name];
    return e ? e.sum / e.n : null;
  };

  if (loading) return <Skeleton variant="rectangular" className="h-40" />;
  if (!backtest || backtest.length === 0) return null;

  return (
    <GlassCard className="p-4">
      <SectionHeader title="战法胜率对比" subtitle="真实回测 vs 合成估算（历史统计特征，市场有风险）" />
      <div className="mt-3 overflow-x-auto">
        <table className="w-full text-sm">
          <thead>
            <tr className="text-left text-xs text-muted-foreground">
              <th className="py-1 pr-3">战法</th>
              <th className="py-1 pr-3">回测胜率</th>
              <th className="py-1 pr-3">合成胜率</th>
              <th className="py-1 pr-3">样本</th>
              <th className="py-1">平均收益</th>
            </tr>
          </thead>
          <tbody>
            {backtest.map((b) => {
              const sr = synthRate(b.strategy);
              return (
                <tr key={b.strategy_code} className="border-t border-border/30">
                  <td className="py-1 pr-3">{b.strategy}</td>
                  <td className="py-1 pr-3">
                    {b.sample_size > 0 ? `${(b.win_rate * 100).toFixed(1)}%` : "—"}
                  </td>
                  <td className="py-1 pr-3">
                    {sr != null ? (
                      <>
                        {(sr * 100).toFixed(1)}%<span className="ml-1 text-xs text-muted-foreground">估算</span>
                      </>
                    ) : (
                      "—"
                    )}
                  </td>
                  <td className="py-1 pr-3 text-xs text-muted-foreground">
                    {b.sample_size} / {b.available_days}日
                  </td>
                  <td className="py-1 text-xs">
                    {b.sample_size > 0
                      ? `${b.avg_return >= 0 ? "+" : ""}${b.avg_return}%`
                      : "—"}
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
    </GlassCard>
  );
}
