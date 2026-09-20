// Track D M1: 个股席位活动卡——per-stock cross-cutting 席位 view。
// 借后端 dragon_tiger（StockDeep.dragon_tiger / useDragonTiger）→ 龙虎榜记录 + 买卖席位 + 机构净额。
// 显于 /stock/:code（StockCockpit）。无数据 → honest-empty（不臆造）。
import { Building2, Fish } from "lucide-react";
import { GlassCard } from "@/components/ui/GlassCard";
import { HonestEmptyState } from "@/components/intraday/HonestEmptyState";
import type { DragonTiger, DtSeat } from "@/lib/api";
import { cn } from "@/lib/utils";

function fmtAmt(v: number | null | undefined): string {
  if (v == null) return "—";
  const abs = Math.abs(v);
  if (abs >= 1e8) return `${(v / 1e8).toFixed(2)}亿`;
  if (abs >= 1e4) return `${(v / 1e4).toFixed(0)}万`;
  return v.toFixed(0);
}

function SeatRow({ seat, side }: { seat: DtSeat; side: "buy" | "sell" }) {
  const net = seat.net;
  return (
    <tr className="border-b border-border/20">
      <td className="py-1 pr-2 text-xs">{seat.name}</td>
      <td className="py-1 pr-2 text-right font-mono text-xs text-muted-foreground">{fmtAmt(seat.buy_amt)}</td>
      <td className="py-1 pr-2 text-right font-mono text-xs text-muted-foreground">{fmtAmt(seat.sell_amt)}</td>
      <td className={cn("py-1 text-right font-mono text-xs", net >= 0 ? "text-red-500" : "text-green-500")}>
        {side === "buy" ? "+" : ""}{fmtAmt(net)}
      </td>
    </tr>
  );
}

export function StockSeatCard({ dragonTiger, code }: { dragonTiger: DragonTiger | null; code: string }) {
  if (!dragonTiger || (
    (!dragonTiger.records || dragonTiger.records.length === 0) &&
    (!dragonTiger.seats?.buy || dragonTiger.seats.buy.length === 0) &&
    (!dragonTiger.seats?.sell || dragonTiger.seats.sell.length === 0) &&
    !dragonTiger.institution
  )) {
    return (
      <GlassCard className="p-4">
        <h3 className="mb-2 text-sm font-semibold">席位活动</h3>
        <HonestEmptyState
          message={`${code} 近期无龙虎榜记录`}
          hint="未上龙虎榜或数据未更新"
        />
      </GlassCard>
    );
  }

  const inst = dragonTiger.institution;
  const buySeats = dragonTiger.seats?.buy ?? [];
  const sellSeats = dragonTiger.seats?.sell ?? [];

  return (
    <GlassCard className="p-4">
      <h3 className="mb-3 text-sm font-semibold">席位活动 · 龙虎榜</h3>

      {/* 机构净额摘要 */}
      {inst && (
        <div className="mb-3 flex items-center gap-4 rounded-lg bg-muted/20 px-3 py-2">
          <Building2 className="h-4 w-4 text-blue-400" />
          <div className="text-xs">
            <span className="text-muted-foreground">机构 </span>
            <span className={cn("font-mono font-medium", (inst.net_amt ?? 0) >= 0 ? "text-red-500" : "text-green-500")}>
              净{(inst.net_amt ?? 0) >= 0 ? "买入" : "卖出"} {fmtAmt(inst.net_amt)}
            </span>
            <span className="ml-2 text-muted-foreground">
              买 {fmtAmt(inst.buy_amt)} / 卖 {fmtAmt(inst.sell_amt)}
            </span>
          </div>
        </div>
      )}

      {/* 上榜记录 */}
      {dragonTiger.records && dragonTiger.records.length > 0 && (
        <div className="mb-3">
          <p className="mb-1 text-xs font-medium text-muted-foreground">上榜记录</p>
          <div className="space-y-1">
            {dragonTiger.records.slice(0, 5).map((r, i) => (
              <div key={i} className="flex items-center justify-between text-xs">
                <span className="font-mono text-muted-foreground">{r.date.slice(5)}</span>
                <span className="truncate px-2 text-muted-foreground">{r.reason}</span>
                <span className={cn("font-mono", r.net_buy >= 0 ? "text-red-500" : "text-green-500")}>
                  {r.net_buy >= 0 ? "+" : ""}{fmtAmt(r.net_buy)}
                </span>
              </div>
            ))}
          </div>
        </div>
      )}

      {/* 买卖席位 */}
      {(buySeats.length > 0 || sellSeats.length > 0) && (
        <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
          {buySeats.length > 0 && (
            <div>
              <p className="mb-1 flex items-center gap-1 text-xs font-medium text-red-500">
                <Fish className="h-3 w-3" /> 买入席位
              </p>
              <table className="w-full">
                <thead>
                  <tr className="text-left text-xs text-muted-foreground">
                    <th className="py-0.5 pr-2">席位</th>
                    <th className="py-0.5 pr-2 text-right">买</th>
                    <th className="py-0.5 pr-2 text-right">卖</th>
                    <th className="py-0.5 text-right">净</th>
                  </tr>
                </thead>
                <tbody>
                  {buySeats.slice(0, 5).map((s, i) => <SeatRow key={`${i}-${s.name}`} seat={s} side="buy" />)}
                </tbody>
              </table>
            </div>
          )}
          {sellSeats.length > 0 && (
            <div>
              <p className="mb-1 flex items-center gap-1 text-xs font-medium text-green-500">
                <Fish className="h-3 w-3" /> 卖出席位
              </p>
              <table className="w-full">
                <thead>
                  <tr className="text-left text-xs text-muted-foreground">
                    <th className="py-0.5 pr-2">席位</th>
                    <th className="py-0.5 pr-2 text-right">买</th>
                    <th className="py-0.5 pr-2 text-right">卖</th>
                    <th className="py-0.5 text-right">净</th>
                  </tr>
                </thead>
                <tbody>
                  {sellSeats.slice(0, 5).map((s, i) => <SeatRow key={`${i}-${s.name}`} seat={s} side="sell" />)}
                </tbody>
              </table>
            </div>
          )}
        </div>
      )}
    </GlassCard>
  );
}
