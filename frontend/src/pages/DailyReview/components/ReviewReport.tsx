/** 每日复盘报告（含标签页） */
import { useState } from "react";
import { GlassCard } from "@/components/ui/GlassCard";
import { pctColor, cn } from "@/lib/utils";
import { Loader2, AlertCircle, RefreshCw } from "lucide-react";
import type { DailyReviewReport } from "@/lib/api";

interface Props {
  date: string;
  report: DailyReviewReport | null;
  loading: boolean;
  error: string | null;
  onDateChange: (d: string) => void;
  onRefresh: () => void;
}

export function ReviewReport({ date, report, loading, error, onDateChange, onRefresh }: Props) {
  const [tab, setTab] = useState<"sector" | "zt" | "auction">("sector");
  return (
    <>
      <div className="mb-3 flex items-center justify-between">
        <h3 className="text-sm font-semibold text-muted-foreground">复盘报告</h3>
        <div className="flex items-center gap-2">
          <input type="date" value={date} onChange={(e) => onDateChange(e.target.value)}
            className="rounded-lg border border-border bg-black/20 px-2 py-1 text-xs outline-none focus:border-primary/50" />
          <button onClick={onRefresh} className="text-muted-foreground hover:text-primary" title="刷新">
            {loading ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <RefreshCw className="h-3.5 w-3.5" />}
          </button>
        </div>
      </div>
      <GlassCard className="mb-6">
        {loading ? (
          <div className="flex items-center justify-center py-8"><Loader2 className="h-5 w-5 animate-spin text-primary" /><span className="ml-2 text-sm text-muted-foreground">加载复盘报告…</span></div>
        ) : error ? (
          <div className="flex items-center justify-center py-8 text-sm text-destructive"><AlertCircle className="mr-1.5 h-4 w-4" /> {error}</div>
        ) : !report ? (
          <p className="py-6 text-center text-sm text-muted-foreground/60">暂无复盘数据（可能是非交易时段或数据源暂不可用）</p>
        ) : (
          <>
            <div className="mb-3 grid grid-cols-2 gap-2 rounded-lg bg-muted/20 p-2.5 sm:grid-cols-4 md:grid-cols-7">
              <div><p className="text-[11px] text-muted-foreground">STI 得分</p><p className="font-mono text-lg font-bold text-primary">{report.sti_score ?? "—"}</p></div>
              <div><p className="text-[11px] text-muted-foreground">STI 阶段</p><p className={cn("font-mono text-lg font-bold", report.sti_phase === "高潮" || report.sti_phase === "启动" ? "text-danger" : report.sti_phase === "冰点" || report.sti_phase === "退潮" ? "text-success" : "text-muted-foreground")}>{report.sti_phase ?? "—"}</p></div>
              <div><p className="text-[11px] text-muted-foreground">涨停</p><p className="font-mono text-lg font-bold text-danger">{report.zt_total}</p></div>
              <div><p className="text-[11px] text-muted-foreground">跌停</p><p className="font-mono text-lg font-bold text-success">{report.dt_total}</p></div>
              <div><p className="text-[11px] text-muted-foreground">炸板</p><p className="font-mono text-lg font-bold text-warning">{report.zb_total}</p></div>
              <div><p className="text-[11px] text-muted-foreground">上涨</p><p className="font-mono text-lg font-bold text-danger">{report.advance_count}</p></div>
              <div><p className="text-[11px] text-muted-foreground">下跌</p><p className="font-mono text-lg font-bold text-success">{report.decline_count}</p></div>
            </div>
            <div className="mb-3 flex gap-1 rounded-lg bg-muted/15 p-1">
              {([
                { key: "sector" as const, label: "板块热度" },
                { key: "zt" as const, label: "涨停明细" },
                { key: "auction" as const, label: "竞价回顾" },
              ]).map((t) => (
                <button key={t.key} onClick={() => setTab(t.key)}
                  className={cn("flex-1 rounded-md px-3 py-1.5 text-xs font-medium transition-colors", tab === t.key ? "bg-muted/30 text-foreground shadow-sm" : "text-muted-foreground hover:text-foreground")}>
                  {t.label}
                </button>
              ))}
            </div>
            {tab === "sector" && (
              <div className="overflow-x-auto">
                <table className="w-full text-sm">
                  <thead><tr className="border-b border-border/50 bg-muted/20 text-left text-xs text-muted-foreground">
                    {["#", "板块", "涨停数", "总家数", "涨停率", "均价变动"].map((h) => <th key={h} className="whitespace-nowrap px-3 py-2.5 font-medium">{h}</th>)}
                  </tr></thead>
                  <tbody className="divide-y divide-border/20">
                    {report.sector_heat?.length === 0 ? <tr><td colSpan={6} className="py-6 text-center text-sm text-muted-foreground/60">暂无板块数据</td></tr> :
                      report.sector_heat?.slice(0, 10).map((s, i) => (
                        <tr key={s.sector} className="transition-colors hover:bg-muted/20">
                          <td className="whitespace-nowrap px-3 py-2.5 font-mono text-xs text-muted-foreground/50">{i + 1}</td>
                          <td className="px-3 py-2.5 font-medium">{s.sector}</td>
                          <td className="whitespace-nowrap px-3 py-2.5 font-mono text-xs text-danger">{s.zt_count}</td>
                          <td className="whitespace-nowrap px-3 py-2.5 font-mono text-xs">{s.total_count}</td>
                          <td className="whitespace-nowrap px-3 py-2.5 font-mono text-xs">{s.zt_rate != null ? `${(s.zt_rate * 100).toFixed(1)}%` : "—"}</td>
                          <td className={cn("whitespace-nowrap px-3 py-2.5 font-mono text-xs", pctColor(s.avg_change))}>{s.avg_change != null ? `${s.avg_change > 0 ? "+" : ""}${s.avg_change.toFixed(2)}%` : "—"}</td>
                        </tr>
                      ))}
                  </tbody>
                </table>
              </div>
            )}
            {tab === "zt" && (
              <div className="overflow-x-auto">
                <table className="w-full text-sm">
                  <thead><tr className="border-b border-border/50 bg-muted/20 text-left text-xs text-muted-foreground">
                    {["#", "代码", "名称", "连板数", "封板率", "换手率", "成交额(亿)"].map((h) => <th key={h} className="whitespace-nowrap px-3 py-2.5 font-medium">{h}</th>)}
                  </tr></thead>
                  <tbody className="divide-y divide-border/20">
                    {report.zt_stocks?.length === 0 ? <tr><td colSpan={7} className="py-6 text-center text-sm text-muted-foreground/60">暂无涨停数据</td></tr> :
                      report.zt_stocks?.slice(0, 20).map((s, i) => (
                        <tr key={s.code} className="transition-colors hover:bg-muted/20">
                          <td className="whitespace-nowrap px-3 py-2.5 font-mono text-xs text-muted-foreground/50">{i + 1}</td>
                          <td className="whitespace-nowrap px-3 py-2.5 font-mono text-xs text-muted-foreground/60">{s.code}</td>
                          <td className="px-3 py-2.5 font-medium">{s.name}</td>
                          <td className="whitespace-nowrap px-3 py-2.5 font-mono font-bold text-primary">{s.lbc}</td>
                          <td className="whitespace-nowrap px-3 py-2.5 font-mono text-xs">{s.seal_rate != null ? `${(s.seal_rate * 100).toFixed(1)}%` : "—"}</td>
                          <td className="whitespace-nowrap px-3 py-2.5 font-mono text-xs">{s.fbt != null ? `${s.fbt}%` : "—"}</td>
                          <td className="whitespace-nowrap px-3 py-2.5 font-mono text-xs">{s.zbc != null ? `${(s.zbc / 1e8).toFixed(1)} 亿` : "—"}</td>
                        </tr>
                      ))}
                  </tbody>
                </table>
              </div>
            )}
            {tab === "auction" && (
              <div className="overflow-x-auto">
                <table className="w-full text-sm">
                  <thead><tr className="border-b border-border/50 bg-muted/20 text-left text-xs text-muted-foreground">
                    {["#", "代码", "名称", "评分", "信号"].map((h) => <th key={h} className="whitespace-nowrap px-3 py-2.5 font-medium">{h}</th>)}
                  </tr></thead>
                  <tbody className="divide-y divide-border/20">
                    {report.auction_top?.length === 0 ? <tr><td colSpan={5} className="py-6 text-center text-sm text-muted-foreground/60">暂无竞价数据</td></tr> :
                      report.auction_top?.slice(0, 10).map((a, i) => (
                        <tr key={JSON.stringify(a)} className="transition-colors hover:bg-muted/20">
                          <td className="whitespace-nowrap px-3 py-2.5 font-mono text-xs text-muted-foreground/50">{i + 1}</td>
                          <td className="whitespace-nowrap px-3 py-2.5 font-mono text-xs text-muted-foreground/60">{(a as any).code ?? "—"}</td>
                          <td className="px-3 py-2.5 font-medium">{(a as any).name ?? "—"}</td>
                          <td className="whitespace-nowrap px-3 py-2.5 font-mono text-xs text-primary">{(a as any).score ?? (a as any).rating ?? "—"}</td>
                          <td className="px-3 py-2.5 text-xs text-muted-foreground">{(a as any).signal ?? (a as any).note ?? "—"}</td>
                        </tr>
                      ))}
                  </tbody>
                </table>
              </div>
            )}
            {report.updated && <p className="mt-2 text-[11px] text-muted-foreground/50">更新时间: {report.updated}</p>}
          </>
        )}
      </GlassCard>
    </>
  );
}
