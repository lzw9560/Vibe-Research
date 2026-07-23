import { useState, useEffect, useCallback } from "react";
import { Loader2, RefreshCw, Info } from "lucide-react";
import { GlassCard } from "@/components/ui/GlassCard";
import { api, type AuctionScreenerResult } from "@/lib/api";
import { cn } from "@/lib/utils";

function stiColor(phase: string | null) {
  if (!phase) return "text-muted-foreground";
  if (phase === "高潮" || phase === "启动") return "text-danger";
  if (phase === "冰点" || phase === "退潮") return "text-success";
  return "text-muted-foreground";
}

// ── 主页面：竞价预案 ────────────────────────────────────────
export function AuctionScreener() {
  const [result, setResult] = useState<AuctionScreenerResult | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [selectedDate, setSelectedDate] = useState(new Date().toISOString().slice(0, 10));

  const loadAuction = useCallback((date: string) => {
    setLoading(true);
    setError(null);
    api.auctionTop(date)
      .then(setResult)
      .catch((e) => setError(e instanceof Error ? e.message : "加载失败"))
      .finally(() => setLoading(false));
  }, []);

  useEffect(() => {
    loadAuction(selectedDate);
  }, [loadAuction, selectedDate]);

  if (loading) {
    return (
      <GlassCard>
        <div className="flex items-center justify-center py-8">
          <Loader2 className="h-5 w-5 animate-spin text-primary" />
          <span className="ml-2 text-sm text-muted-foreground">加载竞价选股数据…</span>
        </div>
      </GlassCard>
    );
  }

  return (
    <div>
      <div className="mb-6 flex items-center justify-between">
        <div>
          <h2 className="text-xl font-bold text-foreground">竞价预案 TOP N</h2>
          <p className="mt-1 text-xs text-muted-foreground">基于 STI 情绪温度计的竞价选股模型</p>
        </div>
        <div className="flex items-center gap-2">
          <input
            type="date"
            value={selectedDate}
            onChange={(e) => setSelectedDate(e.target.value)}
            className="rounded-lg border border-border bg-black/20 px-2 py-1 text-xs outline-none focus:border-primary/50"
          />
          <button
            onClick={() => loadAuction(selectedDate)}
            className="text-muted-foreground hover:text-primary"
            title="刷新"
          >
            <RefreshCw className="h-3.5 w-3.5" />
          </button>
        </div>
      </div>

      {/* STI 摘要栏 */}
      {result && result.sti_score != null && (
        <div className="mb-4 grid grid-cols-2 gap-3 rounded-lg bg-muted/20 p-4 sm:grid-cols-4">
          <div>
            <p className="text-[11px] text-muted-foreground">STI 得分</p>
            <p className="font-mono text-2xl font-bold text-primary">{result.sti_score}</p>
          </div>
          <div>
            <p className="text-[11px] text-muted-foreground">STI 阶段</p>
            <p className={cn("font-mono text-2xl font-bold", stiColor(result.sti_phase))}>{result.sti_phase ?? "—"}</p>
          </div>
          <div>
            <p className="text-[11px] text-muted-foreground">分析总数</p>
            <p className="font-mono text-2xl font-bold text-foreground">{result.total_analyzed}</p>
          </div>
          <div>
            <p className="text-[11px] text-muted-foreground">候选数</p>
            <p className="font-mono text-2xl font-bold text-primary">{result.candidates?.length ?? 0}</p>
          </div>
        </div>
      )}

      {error ? (
        <GlassCard>
          <div className="flex items-center justify-center py-8 text-sm text-destructive">
            <Info className="mr-1.5 h-4 w-4" /> {error}
          </div>
        </GlassCard>
      ) : (
        <GlassCard>
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                <tr className="border-b border-border/50 bg-muted/20 text-left text-xs text-muted-foreground">
                  <th className="w-8 px-2 py-2.5">#</th>
                  <th className="whitespace-nowrap px-3 py-2.5 font-medium">代码</th>
                  <th className="whitespace-nowrap px-3 py-2.5 font-medium">名称</th>
                  <th className="w-16 whitespace-nowrap px-3 py-2.5 text-center font-medium">竞价得分</th>
                  <th className="w-16 whitespace-nowrap px-3 py-2.5 text-center font-medium">基因得分</th>
                  <th className="w-14 whitespace-nowrap px-3 py-2.5 text-center font-medium">连板数</th>
                  <th className="w-16 whitespace-nowrap px-3 py-2.5 text-center font-medium">封板率</th>
                  <th className="whitespace-nowrap px-3 py-2.5 font-medium">战法标签</th>
                  <th className="w-16 whitespace-nowrap px-3 py-2.5 text-center font-medium">信号强度</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-border/20">
                {result?.candidates?.length === 0 ? (
                  <tr>
                    <td colSpan={9} className="py-6 text-center text-sm text-muted-foreground/60">
                      今日无符合条件的竞价选股标的
                    </td>
                  </tr>
                ) : (
                  result?.candidates?.map((c, i) => (
                    <tr key={c.code} className="transition-colors hover:bg-muted/20">
                      <td className="whitespace-nowrap px-2 py-2.5 font-mono text-xs text-muted-foreground/50">{i + 1}</td>
                      <td className="whitespace-nowrap px-3 py-2.5 font-mono text-xs text-muted-foreground/60">{c.code}</td>
                      <td className="px-3 py-2.5 font-medium">{c.name}</td>
                      <td className="px-3 py-2.5 text-center">
                         <span className={`inline-block rounded-md px-2 py-0.5 font-mono text-sm font-bold ${
                           c.score >= 75 ? "bg-primary/10 text-primary"
                           : c.score >= 60 ? "bg-info/10 text-info"
                           : "bg-muted/20 text-muted-foreground"
                         }`}>
                          {c.score}
                        </span>
                      </td>
                      <td className="whitespace-nowrap px-3 py-2.5 text-center font-mono text-xs">
                        {c.gene_score}
                      </td>
                      <td className="whitespace-nowrap px-3 py-2.5 text-center font-mono text-xs">
                        {c.zt_count_30d}
                      </td>
                      <td className="whitespace-nowrap px-3 py-2.5 text-center font-mono text-xs">
                        {c.seal_rate != null ? `${(c.seal_rate * 100).toFixed(1)}%` : "—"}
                      </td>
                      <td className="px-3 py-2.5">
                        <div className="flex flex-wrap gap-1">
                          {c.strategy_tags?.length > 0
                            ? c.strategy_tags.map((tag, j) => (
                                <span key={j} className="rounded bg-primary/10 px-1.5 py-0.5 text-[10px] text-primary">{tag}</span>
                              ))
                            : "—"}
                        </div>
                      </td>
                      <td className="whitespace-nowrap px-3 py-2.5 text-center font-mono text-xs">
                        {c.signal_strength != null ? `${(c.signal_strength * 100).toFixed(1)}%` : "—"}
                      </td>
                    </tr>
                  ))
                )}
              </tbody>
            </table>
          </div>
        </GlassCard>
      )}

      {result?.updated && (
        <p className="mt-2 text-[11px] text-muted-foreground/50">更新时间: {result.updated}</p>
      )}
    </div>
  );
}
