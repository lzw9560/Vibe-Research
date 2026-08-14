// S066 §5 板块周期面板——3 日时序阶段 + 强度排名 + 轮动 + 广度。
// spec §11.2：板块周期面板（阶段 + 强度排名 + 轮动 + 广度）。
import { TrendingUp, TrendingDown, Minus } from "lucide-react";
import { cn } from "@/lib/utils";
import { useSectorCycle } from "@/lib/query/strategy";
import { Skeleton } from "@/components/ui/Skeleton";
import { GlassCard } from "@/components/ui/GlassCard";

const PHASE_META: Record<string, { icon: typeof TrendingUp; color: string; label: string }> = {
  启动: { icon: TrendingUp, color: "text-success", label: "启动期" },
  发酵: { icon: TrendingUp, color: "text-primary", label: "发酵期" },
  高潮: { icon: TrendingUp, color: "text-warning", label: "高潮期·注意退潮" },
  退潮: { icon: TrendingDown, color: "text-destructive", label: "退潮期·追入即套" },
  冷门: { icon: Minus, color: "text-muted-foreground", label: "冷门" },
  无历史: { icon: Minus, color: "text-muted-foreground", label: "无历史数据" },
};

interface Props {
  date: string;
  industry: string;
}

/** S066 §5 板块周期面板。
 * 显示板块在周期中的位置（启动/发酵/高潮/退潮/冷门）+ 3 日时序动量。
 */
export function SectorCyclePanel({ date, industry }: Props) {
  const { data, isLoading } = useSectorCycle(date, industry);

  if (isLoading) {
    return <Skeleton className="h-24 w-full" />;
  }

  if (!data) {
    return (
      <GlassCard className="p-3">
        <p className="text-sm text-muted-foreground">板块周期：无历史数据</p>
      </GlassCard>
    );
  }

  const meta = PHASE_META[data.phase] ?? PHASE_META.无历史;
  const PhaseIcon = meta.icon;
  const momentumPositive = data.momentum > 0;
  const momentumNegative = data.momentum < 0;

  return (
    <GlassCard className="p-3">
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-2">
          <PhaseIcon className={cn("h-4 w-4", meta.color)} />
          <span className="text-sm font-medium">{industry}</span>
        </div>
        <span className={cn("text-sm font-bold", meta.color)}>{meta.label}</span>
      </div>
      <div className="mt-2 grid grid-cols-3 gap-2 text-xs">
        <div>
          <p className="text-muted-foreground">今日涨停</p>
          <p className="font-mono font-bold">{data.count_today}</p>
        </div>
        <div>
          <p className="text-muted-foreground">3 日均值</p>
          <p className="font-mono">{data.count_avg_3d.toFixed(1)}</p>
        </div>
        <div>
          <p className="text-muted-foreground">动量</p>
          <p className={cn(
            "font-mono font-bold",
            momentumPositive ? "text-success" : momentumNegative ? "text-destructive" : "",
          )}>
            {data.momentum > 0 ? "+" : ""}{data.momentum.toFixed(1)}
          </p>
        </div>
      </div>
      {data.phase_note && (
        <p className="mt-2 text-xs text-muted-foreground">{data.phase_note}</p>
      )}
      {data.modifier !== 1.0 && (
        <p className="mt-1 text-xs text-primary">策略分修饰 ×{data.modifier.toFixed(2)}</p>
      )}
    </GlassCard>
  );
}
