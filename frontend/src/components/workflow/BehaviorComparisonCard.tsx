// S093 T18：行为对照卡——三桶 follow/feeling/missed 完整对照（spec R14）。
// 从 PreMarketBehaviorBlock 抽出，移入复盘 Tab。含独立性指标 + 研判 tips + disclaimer。
// 工程底线：不臆造——三桶数据来自 useShadowComparison；缺数据标"—"；历史统计特征标注。
import { Link } from "react-router-dom";
import { useShadowComparison } from "@/lib/query";
import { deriveAssessmentTips } from "@/lib/winrate-assessment";
import { GlassCard } from "@/components/ui/GlassCard";
import { SectionHeader } from "@/components/ui/SectionHeader";
import { Skeleton } from "@/components/ui/Skeleton";

function fmtPct(v: number | null | undefined): string {
  if (v == null) return "—";
  return `${(v * 100).toFixed(1)}%`;
}

function fmtRet(v: number | null | undefined): string {
  if (v == null) return "—";
  return `${v >= 0 ? "+" : ""}${v.toFixed(2)}%`;
}

/** 行为对照卡——28 天 follow/feeling/missed 三桶 + 独立性 + 研判 + disclaimer。
 * 数据源 useShadowComparison(28)，TanStack Query 按 queryKey 去重（复盘页已有同 key 调用）。 */
export function BehaviorComparisonCard() {
  const { data, isLoading } = useShadowComparison(28);

  if (isLoading) {
    return (
      <div className="mb-6">
        <SectionHeader title="行为对照" subtitle="follow / feeling / missed 三桶 + 独立性" />
        <GlassCard className="p-4">
          <Skeleton variant="rounded" className="h-24" />
        </GlassCard>
      </div>
    );
  }

  if (!data) return null;

  const tips = deriveAssessmentTips(data);

  return (
    <div className="mb-6">
      <SectionHeader title="行为对照" subtitle="决策前先看自己的行为账单" />
      <GlassCard className="p-4">
        <div className="grid gap-3 sm:grid-cols-3">
          <div>
            <p className="text-xs text-muted-foreground">跟随单 follow</p>
            <p className="mt-1 text-sm font-medium">
              n={data.follow.n} · 胜率 {fmtPct(data.follow.win_rate)} · 均收益{" "}
              {fmtRet(data.follow.avg_return)}
            </p>
          </div>
          <div>
            <p className="text-xs text-muted-foreground">感觉单 feeling</p>
            <p className="mt-1 text-sm font-medium">
              n={data.feeling.n} · 胜率 {fmtPct(data.feeling.win_rate)} · 均收益{" "}
              {fmtRet(data.feeling.avg_return)}
            </p>
          </div>
          <div>
            <p className="text-xs text-muted-foreground">漏单 missed</p>
            <p className="mt-1 text-sm font-medium">
              n={data.missed.n} · 胜率 {fmtPct(data.missed.win_rate)} · 均收益{" "}
              {fmtRet(data.missed.avg_return)}
            </p>
          </div>
        </div>

        <div className="mt-3 flex flex-wrap gap-3 text-xs text-muted-foreground">
          <span>一致率 {fmtPct(data.independence.agreement_rate)}</span>
          <span>感觉单胜率 {fmtPct(data.independence.feeling_win_rate)}</span>
          {!data.sufficient && (
            <span className="text-warning">样本不足（任一桶 n&lt;5），参考价值低</span>
          )}
        </div>

        {tips.length > 0 && (
          <div className="mt-3 border-t border-border/30 pt-3">
            <p className="mb-1 text-xs font-medium">行为研判</p>
            <ul className="space-y-1">
              {tips.map((t) => (
                <li key={t.slice(0, 20)} className="text-xs text-foreground/90">
                  · {t}
                </li>
              ))}
            </ul>
          </div>
        )}

        <div className="mt-3 flex items-center justify-between">
          <p className="text-[10px] text-muted-foreground/60">{data.disclaimer}</p>
          <Link to="/behavior-loop" className="text-xs text-primary hover:underline">
            深看 →
          </Link>
        </div>
      </GlassCard>
    </div>
  );
}
