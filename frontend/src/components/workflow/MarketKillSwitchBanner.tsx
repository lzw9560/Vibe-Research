// S066 §16.4 市场级熔断横幅——指数跌幅 > 3% 时全宽警告。
// spec §11.3 盘中：市场熔断提示（指数跌幅 > 3%）。
import { AlertOctagon } from "lucide-react";
import { cn } from "@/lib/utils";
import { useMarketKillSwitch } from "@/lib/query/strategy";

/** S066 §16.4 市场级熔断横幅。
 * 上证跌幅 > 3% / 创业板跌幅 > 4% → 触发，全宽红色横幅提示不开新仓。
 * 不触发时不渲染（不占位）。
 */
export function MarketKillSwitchBanner() {
  const { data } = useMarketKillSwitch();

  if (!data?.triggered) {
    return null;
  }

  const shPct = data.sh_change_pct;
  const gemPct = data.gem_change_pct;

  return (
    <div
      className={cn(
        "flex items-center gap-3 rounded-lg border border-destructive/40",
        "bg-destructive/10 px-4 py-3 text-destructive",
      )}
    >
      <AlertOctagon className="h-5 w-5 shrink-0" />
      <div className="flex-1">
        <p className="text-sm font-bold">市场熔断 · 不开新仓</p>
        <p className="text-xs text-destructive/80">{data.reason}</p>
      </div>
      <div className="flex gap-3 text-xs">
        {shPct != null && (
          <div className="text-right">
            <p className="text-muted-foreground">上证</p>
            <p className="font-mono font-bold">{shPct.toFixed(2)}%</p>
          </div>
        )}
        {gemPct != null && (
          <div className="text-right">
            <p className="text-muted-foreground">创业板</p>
            <p className="font-mono font-bold">{gemPct.toFixed(2)}%</p>
          </div>
        )}
      </div>
    </div>
  );
}
