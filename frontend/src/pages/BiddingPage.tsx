import { useState, useEffect, useCallback } from "react";
import { RefreshCw, Loader2, AlertCircle, Eye } from "lucide-react";
import { PageHeader } from "@/components/ui/PageHeader";
import { GlassCard } from "@/components/ui/GlassCard";
import { Disclaimer } from "@/components/ui/Disclaimer";
import { api } from "@/lib/api";
import type { AuctionSignal } from "@/lib/api/types";

// FE-4（backlog）：集合竞价监控页——/api/auction/monitor + watchlist 前端独立页。
// 盘前 9:15-9:25 竞价阶段最有用（竞价信号 + 候选池），盘后/非竞价期 data 多为空（诚实展示）。
export default function BiddingPage() {
  const [signals, setSignals] = useState<AuctionSignal[]>([]);
  const [watchlist, setWatchlist] = useState<string[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [autoRefresh, setAutoRefresh] = useState(false);

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const [s, w] = await Promise.all([
        api.auctionMonitor().catch((e: unknown) => {
          setError(e instanceof Error ? e.message : "竞价监控拉取失败");
          return [] as AuctionSignal[];
        }),
        api.auctionWatchlist().catch(() => [] as string[]),
      ]);
      setSignals(s);
      setWatchlist(w);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    load();
  }, [load]);

  // 自动刷新（5s）——竞价阶段开
  useEffect(() => {
    if (!autoRefresh) return;
    const t = setInterval(load, 5000);
    return () => clearInterval(t);
  }, [autoRefresh, load]);

  return (
    <div className="flex flex-col gap-4">
      <PageHeader
        title="集合竞价监控"
        subtitle="盘前 9:15-9:25 竞价信号 + 候选池（/api/auction/monitor + watchlist）"
      />
      <div className="flex items-center gap-3">
        <button
          onClick={load}
          disabled={loading}
          className="rounded-lg bg-primary px-3 py-1.5 text-sm text-white hover:bg-primary disabled:opacity-50"
        >
          {loading ? <Loader2 className="h-4 w-4 animate-spin" /> : <RefreshCw className="h-4 w-4" />}
          <span className="ml-1">刷新</span>
        </button>
        <label className="flex items-center gap-1 text-sm text-gray-600 dark:text-gray-300">
          <input
            type="checkbox"
            checked={autoRefresh}
            onChange={(e) => setAutoRefresh(e.target.checked)}
          />
          自动刷新（5s，竞价阶段开）
        </label>
      </div>

      {error && (
        <GlassCard className="p-3 text-sm text-amber-600">
          <AlertCircle className="mr-2 inline h-4 w-4" />{error}（非竞价时段/盘后 data 多为空，正常）
        </GlassCard>
      )}

      <GlassCard className="p-4">
        <div className="mb-2 flex items-center gap-2 text-sm font-medium">
          <Eye className="h-4 w-4" />候选池（{watchlist.length} 只）
        </div>
        <div className="flex flex-wrap gap-1.5 text-xs">
          {watchlist.length === 0 ? (
            <span className="text-muted-foreground">空（非竞价时段或无候选）</span>
          ) : (
            watchlist.map((c) => (
              <span key={c} className="rounded bg-muted/30 px-1.5 py-0.5 dark:bg-gray-800">{c}</span>
            ))
          )}
        </div>
      </GlassCard>

      <GlassCard className="overflow-hidden">
        <div className="border-b px-4 py-2 text-sm font-medium">竞价信号（{signals.length} 条）</div>
        {signals.length === 0 ? (
          <div className="p-8 text-center text-sm text-muted-foreground">
            无信号（非竞价时段 9:15-9:25 / 盘后 / 停牌）
          </div>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead className="bg-muted/30 text-xs dark:bg-gray-900">
                <tr>
                  <th className="px-3 py-2 text-left">代码</th>
                  <th className="px-3 py-2 text-left">名称</th>
                  <th className="px-3 py-2 text-left">信号</th>
                  <th className="px-3 py-2 text-right">置信度</th>
                  <th className="px-3 py-2 text-right">开盘溢价%</th>
                  <th className="px-3 py-2 text-right">量比</th>
                  <th className="px-3 py-2 text-left">依据</th>
                </tr>
              </thead>
              <tbody>
                {signals.map((s) => (
                  <tr key={s.code} className="border-t dark:border-gray-800">
                    <td className="px-3 py-2 font-mono">{s.code}</td>
                    <td className="px-3 py-2">{s.name}</td>
                    <td className="px-3 py-2">{s.signal_type}</td>
                    <td className="px-3 py-2 text-right">{(s.confidence * 100).toFixed(0)}%</td>
                    <td className="px-3 py-2 text-right">{(s.open_premium * 100).toFixed(2)}</td>
                    <td className="px-3 py-2 text-right">{s.volume_ratio.toFixed(2)}</td>
                    <td className="px-3 py-2 text-xs text-muted-foreground">{s.reasoning.join("；")}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </GlassCard>
      <Disclaimer />
    </div>
  );
}
