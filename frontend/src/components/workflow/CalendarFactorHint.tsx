// S066 §6 日历因子提示——显示仓位乘数 + 原因。
// spec §11.2 顶部导航条：天气状态 + 当前策略组 + 日历因子提示。
import { Calendar, AlertTriangle } from "lucide-react";
import { cn } from "@/lib/utils";
import { useCalendarFactor } from "@/lib/query/strategy";
import { Skeleton } from "@/components/ui/Skeleton";

interface Props {
  date: string;
}

/** S066 §6 日历因子仓位乘数提示条。
 * 周五 ×0.7 / 节前末日 ×0.3 / 节前3日 ×0.5 / 周四 ×1.0。
 * 乘数 < 1.0 时高亮提示降仓。
 */
export function CalendarFactorHint({ date }: Props) {
  const { data, isLoading } = useCalendarFactor(date);

  if (isLoading) {
    return <Skeleton className="h-8 w-full" />;
  }

  if (!data) {
    return null;
  }

  const mult = data.position_multiplier;
  const isReduced = mult < 1.0;
  const isSevere = mult <= 0.3;

  return (
    <div
      className={cn(
        "flex items-center gap-2 rounded-lg border px-3 py-2 text-sm",
        isSevere
          ? "border-destructive/30 bg-destructive/5 text-destructive"
          : isReduced
            ? "border-warning/30 bg-warning/5 text-warning"
            : "border-border/50 bg-muted/10 text-muted-foreground",
      )}
    >
      {isReduced ? <AlertTriangle className="h-4 w-4 shrink-0" /> : <Calendar className="h-4 w-4 shrink-0" />}
      <span className="font-medium">
        日历因子：仓位 ×{mult.toFixed(1)}
      </span>
      {data.reason && (
        <span className="text-muted-foreground">— {data.reason}</span>
      )}
    </div>
  );
}
