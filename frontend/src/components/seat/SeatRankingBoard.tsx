// Track D M1: 盘后榜——今日龙虎榜净买入席位排名（cross-cutting 席位 view）。
// 借后端 GET /api/limitup/seats/profiles（useSeatProfiles）→ SeatProfile[] 按 net_amt 降序 top N。
// 显于今日 hub 盘后 phase。无数据 → honest-empty（不臆造）。
import { Loader2, Trophy } from "lucide-react";
import { GlassCard } from "@/components/ui/GlassCard";
import { HonestEmptyState } from "@/components/intraday/HonestEmptyState";
import { useSeatProfiles } from "@/lib/query";
import type { SeatProfile } from "@/lib/api";
import { cn } from "@/lib/utils";

// 金额格式化：元 → 万/亿
function fmtAmt(v: number | null | undefined): string {
  if (v == null) return "—";
  const abs = Math.abs(v);
  if (abs >= 1e8) return `${(v / 1e8).toFixed(2)}亿`;
  if (abs >= 1e4) return `${(v / 1e4).toFixed(0)}万`;
  return v.toFixed(0);
}

function seatTypeStyle(t: string): string {
  if (t.includes("机构")) return "text-blue-400";
  if (t.includes("量化")) return "text-purple-400";
  if (t.includes("游资") || t.includes("活跃")) return "text-orange-400";
  return "text-muted-foreground";
}

export function SeatRankingBoard({ limit = 10 }: { limit?: number }) {
  const { data, isLoading, isError } = useSeatProfiles();

  if (isLoading) {
    return (
      <GlassCard className="flex items-center gap-2 py-4">
        <Loader2 className="h-4 w-4 animate-spin text-muted-foreground" />
        <span className="text-sm text-muted-foreground">加载席位排名…</span>
      </GlassCard>
    );
  }

  if (isError || !data || !data.profiles || data.profiles.length === 0) {
    return (
      <GlassCard>
        <HonestEmptyState
          message="今日无龙虎榜席位数据"
          hint={<span>盘后更新 · <code>/api/limitup/seats/profiles</code> 待数据</span>}
        />
      </GlassCard>
    );
  }

  // 按净额降序取 top N（正净额=净买入前排）
  const ranked: SeatProfile[] = [...data.profiles]
    .sort((a, b) => (b.net_amt ?? 0) - (a.net_amt ?? 0))
    .slice(0, limit);

  return (
    <GlassCard>
      <div className="mb-3 flex items-center justify-between">
        <h3 className="flex items-center gap-1.5 text-sm font-semibold">
          <Trophy className="h-4 w-4 text-amber-500" />
          盘后龙虎榜·席位净买入排名
        </h3>
        <span className="text-xs text-muted-foreground">共 {data.total} 席位 · top {ranked.length}</span>
      </div>
      <div className="overflow-x-auto">
        <table className="w-full text-sm">
          <thead>
            <tr className="border-b border-border/50 text-left text-xs text-muted-foreground">
              <th className="py-1.5 pr-3">#</th>
              <th className="py-1.5 pr-3">席位</th>
              <th className="py-1.5 pr-3">类型</th>
              <th className="py-1.5 pr-3 text-right">净额</th>
              <th className="py-1.5 pr-3 text-right">出现</th>
              <th className="py-1.5 text-right">最近</th>
            </tr>
          </thead>
          <tbody>
            {ranked.map((s, i) => (
              <tr key={s.seat_name} className="border-b border-border/30">
                <td className="py-1.5 pr-3 font-mono text-xs text-muted-foreground">{i + 1}</td>
                <td className="py-1.5 pr-3 text-xs font-medium">{s.seat_name}</td>
                <td className={cn("py-1.5 pr-3 text-xs", seatTypeStyle(s.seat_type))}>{s.seat_type}</td>
                <td className={cn("py-1.5 pr-3 text-right font-mono text-xs", (s.net_amt ?? 0) >= 0 ? "text-red-500" : "text-green-500")}>
                  {fmtAmt(s.net_amt)}
                </td>
                <td className="py-1.5 pr-3 text-right font-mono text-xs text-muted-foreground">{s.total_appearances}</td>
                <td className="py-1.5 text-right font-mono text-xs text-muted-foreground">{s.last_seen?.slice(5) ?? "—"}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </GlassCard>
  );
}
