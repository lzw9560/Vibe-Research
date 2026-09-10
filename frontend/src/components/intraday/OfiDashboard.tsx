// S178: OFI 盘中数据只读看板组件（read-only，非信号）。
// 仿 JournalLedger 范式：GlassCard + useQuery hook + honest banner + 空态 + ApiError。
import { useState } from "react";
import { GlassCard } from "@/components/ui/GlassCard";
import { useIntradayOfi } from "@/lib/query";
import type { OfiSnapshot } from "@/lib/intraday-ofi-contract";

const REGIME_STYLES: Record<string, string> = {
  strong_trend: "text-[hsl(145_62%_47%)]",
  weak: "text-[hsl(38_92%_50%)]",
  bear: "text-[hsl(0_74%_60%)]",
};

function ofiColor(ofi: number): string {
  if (ofi > 0.3) return "text-[hsl(145_62%_47%)]"; // 买压强 绿
  if (ofi < -0.3) return "text-[hsl(0_74%_60%)]"; // 卖压强 红
  return "text-muted-foreground";
}

export function OfiDashboard() {
  const [date, setDate] = useState(() => new Date().toISOString().slice(0, 10));
  const [code, setCode] = useState("");
  const { data, isLoading, error } = useIntradayOfi(date, code || undefined);

  return (
    <GlassCard className="mb-3">
      {/* honest banner */}
      <div className="mb-3 rounded-md bg-muted/30 px-3 py-2 text-[12px] text-muted-foreground">
        conditioning 数据收集 · 非交易信号（read-only 看板，数据来自 S176 采集器）
      </div>

      {/* date + code filter */}
      <div className="mb-3 flex items-center gap-2">
        <input
          type="date"
          value={date}
          onChange={(e) => setDate(e.target.value)}
          className="rounded border border-border bg-background px-2 py-1 text-sm"
        />
        <input
          type="text"
          value={code}
          onChange={(e) => setCode(e.target.value)}
          placeholder="可选 code 过滤（6 位裸 code）"
          className="flex-1 rounded border border-border bg-background px-2 py-1 text-sm"
        />
      </div>

      {error ? (
        <div className="rounded bg-[hsl(0_74%_60%/0.12)] px-3 py-2 text-[13px] text-[hsl(0_74%_60%)]">
          OFI 数据加载失败
        </div>
      ) : isLoading ? (
        <div className="py-4 text-center text-sm text-muted-foreground">加载中…</div>
      ) : !data || data.count === 0 ? (
        <div className="py-4 text-center text-sm text-muted-foreground">
          暂无 OFI 快照（盘中采集后显示）
        </div>
      ) : (
        <>
          {data.truncated && (
            <div className="mb-2 rounded bg-[hsl(38_92%_50%/0.12)] px-2 py-1 text-[11px] text-[hsl(38_92%_50%)]">
              结果截断至 {data.count} 行（单日上界，调高 limit 或缩小 code）
            </div>
          )}
          <div className="overflow-x-auto">
            <table className="w-full text-[12px]">
              <thead>
                <tr className="border-b border-border text-left text-muted-foreground">
                  <th className="py-1 pr-2">时间</th>
                  <th className="py-1 pr-2">code</th>
                  <th className="py-1 pr-2">OFI</th>
                  <th className="py-1 pr-2">买压</th>
                  <th className="py-1 pr-2">封单</th>
                  <th className="py-1 pr-2">regime</th>
                </tr>
              </thead>
              <tbody>
                {data.snapshots.map((s: OfiSnapshot, i: number) => (
                  <tr key={`${s.code}-${s.ts}-${i}`} className="border-b border-border/50">
                    <td className="py-1 pr-2 font-mono">{s.ts}</td>
                    <td className="py-1 pr-2 font-mono">{s.code}</td>
                    <td className={`py-1 pr-2 font-mono ${ofiColor(s.ofi)}`}>
                      {s.ofi.toFixed(3)}
                    </td>
                    <td className="py-1 pr-2 font-mono">
                      {s.bid_ask_pressure >= 999 ? "≥999" : s.bid_ask_pressure.toFixed(2)}
                    </td>
                    <td className="py-1 pr-2 font-mono">
                      {s.seal_amount != null ? (s.seal_amount / 1e4).toFixed(0) + "万" : "—"}
                    </td>
                    <td
                      className={`py-1 pr-2 ${REGIME_STYLES[s.regime ?? ""] ?? "text-muted-foreground"}`}
                    >
                      {s.regime ?? "—"}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          <div className="mt-2 text-[11px] text-muted-foreground">
            共 {data.count} 条 · {data.date}
          </div>
        </>
      )}
    </GlassCard>
  );
}
