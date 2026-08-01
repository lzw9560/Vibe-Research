import { useState, useEffect, useCallback } from "react";
import { RefreshCw, Info } from "lucide-react";
import { GlassCard } from "@/components/ui/GlassCard";
import { PageHeader } from "@/components/ui/PageHeader";
import { SectionHeader } from "@/components/ui/SectionHeader";
import { MetricCard } from "@/components/ui/MetricCard";
import { EmptyState } from "@/components/ui/EmptyState";
import { Skeleton } from "@/components/ui/Skeleton";
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
      <div className="space-y-4">
        <PageHeader title="竞价预案 TOP N" subtitle="基于 STI 情绪温度计的竞价选股模型" />
        <GlassCard>
          <div className="py-8">
            <Skeleton className="mx-auto h-6 w-48" />
          </div>
        </GlassCard>
      </div>
    );
  }

  return (
    <div className="space-y-4">
      <PageHeader
        title="竞价预案 TOP N"
        subtitle="基于 STI 情绪温度计的竞价选股模型"
        actions={
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
        }
      />

      {/* STI 摘要栏 */}
      {result && result.sti_score != null && (
        <div className="mb-4 grid grid-cols-2 gap-3 rounded-lg bg-muted/20 p-4 sm:grid-cols-4">
          <MetricCard label="STI 得分" value={result.sti_score} valueClassName="text-primary" />
          <MetricCard label="STI 阶段" value={result.sti_phase ?? "—"} valueClassName={cn(stiColor(result.sti_phase))} />
          <MetricCard label="分析总数" value={result.total_analyzed} />
          <MetricCard label="候选数" value={result.candidates?.length ?? 0} valueClassName="text-primary" />
        </div>
      )}

      {error ? (
        <EmptyState
          icon={<Info className="h-8 w-8 text-destructive/40" />}
          title="加载失败"
          description={error}
        />
      ) : (
        <GlassCard>
          <SectionHeader title="候选标的" />
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
                  <th className="w-20 whitespace-nowrap px-3 py-2.5 text-center font-medium">封单额(万)</th>
                  <th className="w-20 whitespace-nowrap px-3 py-2.5 text-center font-medium">流通盘(亿)</th>
                  <th className="w-20 whitespace-nowrap px-3 py-2.5 text-center font-medium">封单/流通</th>
                  <th className="whitespace-nowrap px-3 py-2.5 font-medium">战法标签</th>
                  <th className="w-16 whitespace-nowrap px-3 py-2.5 text-center font-medium">信号强度</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-border/20">
                {result?.candidates?.length === 0 ? (
                  <tr>
                    <td colSpan={9} className="py-8">
                      <EmptyState
                        icon={<Info className="h-8 w-8 text-muted-foreground/40" />}
                        title="今日无符合条件的竞价选股标的"
                      />
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
                        <td className="whitespace-nowrap px-3 py-2.5 text-center font-mono text-xs">
                          {c.seal_amount > 0 ? `${(c.seal_amount / 10000).toFixed(1)}` : "—"}
                        </td>
                        <td className="whitespace-nowrap px-3 py-2.5 text-center font-mono text-xs">
                          {c.float_shares > 0 ? `${(c.float_shares / 100000000).toFixed(2)}` : "—"}
                        </td>
                        <td className="whitespace-nowrap px-3 py-2.5 text-center font-mono text-xs">
                          {c.seal_to_float_ratio > 0 ? `${(c.seal_to_float_ratio * 100).toFixed(2)}%` : "—"}
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
