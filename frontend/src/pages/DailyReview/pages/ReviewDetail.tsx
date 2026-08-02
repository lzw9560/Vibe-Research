/** 复盘报告详情页 - 下沉子页 */
import { useState } from "react";
import { useDailyReview } from "@/lib/query";
import { GlassCard } from "@/components/ui/GlassCard";
import { pctColor, cn } from "@/lib/utils";
import { Loader2, RefreshCw } from "lucide-react";
import { ApiError } from "@/lib/api";

const errMsg = (e: unknown, fallback: string) => (e instanceof ApiError ? e.message : fallback);

export function ReviewDetail() {
  const [date, setDate] = useState(new Date().toISOString().slice(0, 10));
  const [tab, setTab] = useState<"sector" | "zt" | "auction">("sector");
  const { data: report, isLoading, error, refetch } = useDailyReview(date);
  
  return (
    <div>
      <div className="mb-4 flex items-center justify-between">
        <h2 className="text-lg font-semibold">复盘报告详情</h2>
        <div className="flex items-center gap-2">
          <input 
            type="date" 
            value={date} 
            onChange={(e) => setDate(e.target.value)}
            className="rounded-lg border border-border bg-black/20 px-2 py-1 text-sm outline-none focus:border-primary/50"
          />
          <button 
            onClick={() => refetch()} 
            className="rounded-lg border border-border bg-black/20 px-2 py-1 text-sm hover:bg-muted/20"
            title="刷新"
          >
            {isLoading ? <Loader2 className="h-4 w-4 animate-spin" /> : <RefreshCw className="h-4 w-4" />}
          </button>
        </div>
      </div>
      
      {isLoading && (
        <div className="py-8 text-center text-sm text-muted-foreground">加载中…</div>
      )}
      
      {error && (
        <div className="py-8 text-center text-sm text-destructive">{errMsg(error, "加载失败")}</div>
      )}
      
      {!report && !isLoading && !error && (
        <div className="py-8 text-center text-sm text-muted-foreground">暂无复盘数据</div>
      )}
      
      {report && (
        <div className="space-y-4">
          {/* 概览 */}
          <GlassCard className="p-4">
            <div className="grid grid-cols-2 gap-3 sm:grid-cols-4 md:grid-cols-7">
              <div>
                <p className="text-[11px] text-muted-foreground">STI 得分</p>
                <p className="font-mono text-lg font-bold text-primary">{report.sti_score ?? "—"}</p>
              </div>
              <div>
                <p className="text-[11px] text-muted-foreground">STI 阶段</p>
                <p className={cn("font-mono text-lg font-bold", 
                  report.sti_phase === "高潮" || report.sti_phase === "启动" ? "text-danger"
                  : report.sti_phase === "冰点" || report.sti_phase === "退潮" ? "text-success"
                  : "text-muted-foreground"
                )}>{report.sti_phase ?? "—"}</p>
              </div>
              <div>
                <p className="text-[11px] text-muted-foreground">涨停</p>
                <p className="font-mono text-lg font-bold text-danger">{report.zt_total}</p>
              </div>
              <div>
                <p className="text-[11px] text-muted-foreground">跌停</p>
                <p className="font-mono text-lg font-bold text-success">{report.dt_total}</p>
              </div>
              <div>
                <p className="text-[11px] text-muted-foreground">炸板</p>
                <p className="font-mono text-lg font-bold text-warning">{report.zb_total}</p>
              </div>
              <div>
                <p className="text-[11px] text-muted-foreground">上涨</p>
                <p className="font-mono text-lg font-bold text-danger">{report.advance_count}</p>
              </div>
              <div>
                <p className="text-[11px] text-muted-foreground">下跌</p>
                <p className="font-mono text-lg font-bold text-success">{report.decline_count}</p>
              </div>
            </div>
          </GlassCard>
          
          {/* 标签页 */}
          <div className="flex gap-1 rounded-lg bg-muted/15 p-1">
            {([
              { key: "sector" as const, label: "板块热度" },
              { key: "zt" as const, label: "涨停明细" },
              { key: "auction" as const, label: "竞价回顾" },
            ]).map((t) => (
              <button 
                key={t.key} 
                onClick={() => setTab(t.key)}
                className={cn(
                  "flex-1 rounded-md px-3 py-1.5 text-sm font-medium transition-colors",
                  tab === t.key ? "bg-muted/30 text-foreground shadow-sm" : "text-muted-foreground hover:text-foreground"
                )}
              >
                {t.label}
              </button>
            ))}
          </div>
          
          {/* 板块热度 */}
          {tab === "sector" && report.sector_heat && (
            <GlassCard className="p-4">
              <h3 className="mb-3 text-sm font-semibold">板块热度榜</h3>
              <div className="overflow-x-auto">
                <table className="w-full text-sm">
                  <thead>
                    <tr className="border-b border-border/50 text-left text-xs text-muted-foreground">
                      <th className="px-2 py-2">#</th>
                      <th className="px-2 py-2">板块</th>
                      <th className="px-2 py-2">涨停数</th>
                      <th className="px-2 py-2">总家数</th>
                      <th className="px-2 py-2">涨停率</th>
                      <th className="px-2 py-2">均价变动</th>
                    </tr>
                  </thead>
                  <tbody>
                    {report.sector_heat.slice(0, 20).map((s, i) => (
                      <tr key={s.sector} className="border-b border-border/30">
                        <td className="px-2 py-2 font-mono text-xs text-muted-foreground/50">{i + 1}</td>
                        <td className="px-2 py-2 font-medium">{s.sector}</td>
                        <td className="px-2 py-2 font-mono text-xs text-danger">{s.zt_count}</td>
                        <td className="px-2 py-2 font-mono text-xs">{s.total_count}</td>
                        <td className="px-2 py-2 font-mono text-xs">{s.zt_rate != null ? `${(s.zt_rate * 100).toFixed(1)}%` : "—"}</td>
                        <td className={cn("px-2 py-2 font-mono text-xs", pctColor(s.avg_change))}>
                          {s.avg_change != null ? `${s.avg_change > 0 ? "+" : ""}${s.avg_change.toFixed(2)}%` : "—"}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </GlassCard>
          )}
          
          {/* 涨停明细 */}
          {tab === "zt" && report.zt_stocks && (
            <GlassCard className="p-4">
              <h3 className="mb-3 text-sm font-semibold">涨停明细</h3>
              <div className="overflow-x-auto">
                <table className="w-full text-sm">
                  <thead>
                    <tr className="border-b border-border/50 text-left text-xs text-muted-foreground">
                      <th className="px-2 py-2">#</th>
                      <th className="px-2 py-2">代码</th>
                      <th className="px-2 py-2">名称</th>
                      <th className="px-2 py-2">连板数</th>
                      <th className="px-2 py-2">封板率</th>
                      <th className="px-2 py-2">换手率</th>
                      <th className="px-2 py-2">成交额(亿)</th>
                    </tr>
                  </thead>
                  <tbody>
                    {report.zt_stocks.slice(0, 30).map((s, i) => (
                      <tr key={s.code} className="border-b border-border/30">
                        <td className="px-2 py-2 font-mono text-xs text-muted-foreground/50">{i + 1}</td>
                        <td className="px-2 py-2 font-mono text-xs text-muted-foreground/60">{s.code}</td>
                        <td className="px-2 py-2 font-medium">{s.name}</td>
                        <td className="px-2 py-2 font-mono font-bold text-primary">{s.lbc}</td>
                        <td className="px-2 py-2 font-mono text-xs">{s.seal_rate != null ? `${(s.seal_rate * 100).toFixed(1)}%` : "—"}</td>
                        <td className="px-2 py-2 font-mono text-xs">{s.fbt != null ? `${s.fbt}%` : "—"}</td>
                        <td className="px-2 py-2 font-mono text-xs">{s.zbc != null ? `${(s.zbc / 1e8).toFixed(1)} 亿` : "—"}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </GlassCard>
          )}
          
          {/* 竞价回顾 */}
          {tab === "auction" && report.auction_top && (
            <GlassCard className="p-4">
              <h3 className="mb-3 text-sm font-semibold">竞价回顾</h3>
              <div className="overflow-x-auto">
                <table className="w-full text-sm">
                  <thead>
                    <tr className="border-b border-border/50 text-left text-xs text-muted-foreground">
                      <th className="px-2 py-2">#</th>
                      <th className="px-2 py-2">代码</th>
                      <th className="px-2 py-2">名称</th>
                      <th className="px-2 py-2">评分</th>
                      <th className="px-2 py-2">信号</th>
                    </tr>
                  </thead>
                  <tbody>
                    {report.auction_top.slice(0, 20).map((a: any, i) => (
                      <tr key={i} className="border-b border-border/30">
                        <td className="px-2 py-2 font-mono text-xs text-muted-foreground/50">{i + 1}</td>
                        <td className="px-2 py-2 font-mono text-xs text-muted-foreground/60">{a.code ?? "—"}</td>
                        <td className="px-2 py-2 font-medium">{a.name ?? "—"}</td>
                        <td className="px-2 py-2 font-mono text-xs text-primary">{a.score ?? a.rating ?? "—"}</td>
                        <td className="px-2 py-2 text-xs text-muted-foreground">{a.signal ?? a.note ?? "—"}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </GlassCard>
          )}
        </div>
      )}
    </div>
  );
}
