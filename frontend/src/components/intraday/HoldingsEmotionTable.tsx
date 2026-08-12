// S063 T22：Layer 2 持仓×情绪联动表——紧凑表格。
// 双重压力行（个股炸板未回封 + 红色区）置顶高亮；行可点击跳详情。
import { AlertTriangle } from "lucide-react";
import { useIntradayHoldings } from "@/lib/query";
import { cn } from "@/lib/utils";
import { Skeleton } from "@/components/ui/Skeleton";

const ZONE_BG = {
  green: "bg-emerald-500/10 text-emerald-600",
  yellow: "bg-amber-500/10 text-amber-600",
  red: "bg-red-500/10 text-red-600",
} as const;

export function HoldingsEmotionTable() {
  const { data, isLoading } = useIntradayHoldings();

  if (isLoading) {
    return <Skeleton className="h-[160px] w-full" />;
  }

  const holdings = data?.holdings ?? [];
  if (holdings.length === 0) {
    return (
      <div className="rounded-lg bg-muted/10 p-4 text-sm text-muted-foreground">
        {data?.message ?? "当前无持仓"}
      </div>
    );
  }

  return (
    <div className="overflow-x-auto">
      <table className="w-full text-sm">
        <thead>
          <tr className="border-b border-border/40 text-left text-xs text-muted-foreground">
            <th className="px-2 py-1.5">持仓</th>
            <th className="px-2 py-1.5">状态</th>
            <th className="px-2 py-1.5">现价</th>
            <th className="px-2 py-1.5">盈亏</th>
            <th className="px-2 py-1.5">封板</th>
            <th className="px-2 py-1.5">情绪色带</th>
          </tr>
        </thead>
        <tbody>
          {holdings.map((h) => (
            <tr
              key={h.code}
              className={cn(
                "border-b border-border/20",
                h.dual_pressure && "bg-red-500/10",
              )}
            >
              <td className="px-2 py-1.5">
                <div className="flex items-center gap-1">
                  {h.dual_pressure && <AlertTriangle className="h-3 w-3 text-red-600" />}
                  <span className="font-medium">{h.name}</span>
                  <span className="text-[10px] text-muted-foreground">{h.code}</span>
                </div>
              </td>
              <td className="px-2 py-1.5 text-xs text-muted-foreground">{h.status}</td>
              <td className="px-2 py-1.5">
                {h.current_price != null ? h.current_price.toFixed(2) : "—"}
              </td>
              <td
                className={cn(
                  "px-2 py-1.5",
                  h.pnl_pct == null
                    ? "text-muted-foreground"
                    : h.pnl_pct >= 0
                      ? "text-success"
                      : "text-destructive",
                )}
              >
                {h.pnl_pct != null ? `${h.pnl_pct >= 0 ? "+" : ""}${h.pnl_pct.toFixed(2)}%` : "—"}
              </td>
              <td className="px-2 py-1.5 text-xs">{h.seal_status}</td>
              <td className="px-2 py-1.5">
                <span
                  className={cn(
                    "rounded px-1.5 py-0.5 text-[10px]",
                    ZONE_BG[h.current_zone as keyof typeof ZONE_BG] ?? ZONE_BG.yellow,
                  )}
                >
                  {h.current_zone === "green" ? "一致" : h.current_zone === "yellow" ? "走偏" : "背离"}
                </span>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
      {data && data.dual_pressure_count > 0 && (
        <p className="mt-2 text-xs text-red-600">
          {data.dual_pressure_count} 只双重压力（炸板未回封 + 红色区）已置顶
        </p>
      )}
    </div>
  );
}
