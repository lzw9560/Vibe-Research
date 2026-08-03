// S025-B4 调整建议区：GlassCard 呈现 useWinRateAdjustments。
// 后端 generate_strategy_adjustments 返回 [{type, reason, action}] 列表。
import { useWinRateAdjustments } from "@/lib/query";
import { GlassCard } from "@/components/ui/GlassCard";
import { Skeleton } from "@/components/ui/Skeleton";
import { EmptyState } from "@/components/ui/EmptyState";

interface AdjustmentsCardProps {
  windowSize: number;
}

interface Adjustment {
  type: string;
  reason: string;
  action: string;
}

export function AdjustmentsCard({ windowSize }: AdjustmentsCardProps) {
  const { data, isLoading, isError } = useWinRateAdjustments(windowSize);

  if (isLoading) {
    return (
      <GlassCard>
        <Skeleton variant="text" className="w-1/4" />
        <Skeleton variant="rounded" />
      </GlassCard>
    );
  }
  if (isError || !data || (data as Adjustment[]).length === 0) {
    return <EmptyState title="暂无调整建议" description="当前窗口内胜率稳定，无需调整" />;
  }

  const items = data as Adjustment[];
  return (
    <GlassCard>
      <h3 className="mb-3 text-sm font-semibold text-foreground">调整建议</h3>
      <ul className="space-y-3">
        {items.map((a, i) => (
          <li key={`${a.type}-${i}`} className="border-l-2 border-primary/40 pl-3">
            <span className="mb-1 inline-block rounded bg-primary/10 px-2 py-0.5 text-[11px] font-medium text-primary">
              {a.type}
            </span>
            <p className="text-sm text-foreground">{a.reason}</p>
            <p className="mt-0.5 text-xs text-muted-foreground">{a.action}</p>
          </li>
        ))}
      </ul>
    </GlassCard>
  );
}
