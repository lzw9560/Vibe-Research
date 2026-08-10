import type { StrategyBacktestItem } from "@/lib/query/strategy";
import { syntheticWinRate } from "@/lib/query/strategy";
import type { PassedItem } from "@/lib/candidates";
import { useState } from "react";
import { GlassCard } from "@/components/ui/GlassCard";
import { SectionHeader } from "@/components/ui/SectionHeader";
import { Skeleton } from "@/components/ui/Skeleton";

interface Props {
  backtest?: StrategyBacktestItem[];
  /** L2 战法层 passed（携 best_strategy + confidence_value）——供合成胜率重算。 */
  l2Passed?: PassedItem[];
  loading?: boolean;
  /** S049 D8：战法行展开——当日命中（未持仓标的）点击回调。 */
  onPickCandidate?: (code: string) => void;
}

/** S031 R22：战法胜率对比——左列真实回测（R20）/ 右列合成 historical_win_rate（标注"估算"）。
 * 合成公式 min(confidence_value*0.8+0.2, 0.95)（limitup_strategy.py:685），按战法取均值，
 * 与真实回测并列对比，让用户看清合成 vs 真实差异。
 * S049 D8：战法行可展开——当日命中（l2Passed 按 best_strategy 分组，限未持仓态=建仓语义）。 */
export function WinRateComparePanel({ backtest, l2Passed, loading, onPickCandidate }: Props) {
  const [expanded, setExpanded] = useState<string | null>(null);
  // 合成胜率按战法聚合（当日命中各股的 confidence_value → 公式 → 均值）
  const synth: Record<string, { sum: number; n: number }> = {};
  // S049 D8：当日命中按 best_strategy 分组（未持仓标的=建仓语义）
  const hitsByStrategy: Record<string, PassedItem[]> = {};
  for (const p of l2Passed ?? []) {
    const s = p.best_strategy;
    if (!s) continue;
    const v = syntheticWinRate(p.confidence_value ?? 0);
    synth[s] ??= { sum: 0, n: 0 };
    synth[s].sum += v;
    synth[s].n += 1;
    hitsByStrategy[s] ??= [];
    hitsByStrategy[s].push(p);
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
              <th className="py-1 pr-3">平均收益</th>
              <th className="py-1 pr-3">当日命中</th>
            </tr>
          </thead>
          <tbody>
            {backtest.map((b) => {
              const sr = synthRate(b.strategy);
              const hits = hitsByStrategy[b.strategy] ?? [];
              const isOpen = expanded === b.strategy_code;
              return (
                <>
                  <tr
                    key={b.strategy_code}
                    className="border-t border-border/30 cursor-pointer hover:bg-accent/30"
                    onClick={() => hits.length > 0 && setExpanded(isOpen ? null : b.strategy_code)}
                  >
                    <td className="py-1 pr-3">{b.strategy}{hits.length > 0 && (isOpen ? " ▼" : " ▶")}</td>
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
                    <td className="py-1 pr-3 text-xs">
                      {hits.length > 0 ? `${hits.length} 标的` : "—"}
                    </td>
                  </tr>
                  {isOpen && hits.length > 0 && (
                    <tr key={`${b.strategy_code}-hits`} className="bg-accent/10">
                      <td colSpan={6} className="px-4 py-2">
                        <p className="mb-1 text-xs text-muted-foreground">未持仓 · 命中战法（建仓语义，用户决策）</p>
                        <div className="flex flex-wrap gap-2">
                          {hits.map((h) => (
                            <button
                              key={h.code}
                              type="button"
                              className="rounded border border-border/40 px-2 py-0.5 text-xs hover:bg-accent/40"
                              onClick={(e) => { e.stopPropagation(); onPickCandidate?.(h.code); }}
                            >
                              {h.code} {h.name}
                            </button>
                          ))}
                        </div>
                      </td>
                    </tr>
                  )}
                </>
              );
            })}
          </tbody>
        </table>
      </div>
    </GlassCard>
  );
}
