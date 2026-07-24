import { useState, useEffect } from "react";
import { PageHeader } from "@/components/ui/PageHeader";
import { GlassCard } from "@/components/ui/GlassCard";
import { SectionHeader } from "@/components/ui/SectionHeader";
import { MetricCard } from "@/components/ui/MetricCard";
import { EmptyState } from "@/components/ui/EmptyState";
import { Disclaimer } from "@/components/ui/Disclaimer";
import { Loader2, RefreshCw, AlertCircle } from "lucide-react";
import { api } from "@/lib/api";

interface BacktestScatterPoint {
  gene_score: number;
  next_day_return: number;
  code: string;
  date: string;
  industry: string;
}

interface BacktestResult {
  period: string;
  total_signals: number;
  hit_count: number;
  hit_rate: number;
  avg_return: number;
  max_drawdown: number;
  sharpe_ratio: number;
  percentile_analysis: Record<string, any>;
}

export default function Backtest() {
  const [startDate, setStartDate] = useState(() => {
    const d = new Date();
    d.setMonth(d.getMonth() - 1);
    return d.toISOString().slice(0, 10);
  });
  const [endDate, setEndDate] = useState(() => new Date().toISOString().slice(0, 10));
  const [scatter, setScatter] = useState<BacktestScatterPoint[]>([]);
  const [result, setResult] = useState<BacktestResult | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const load = async () => {
    setLoading(true);
    setError(null);
    try {
      const [scatterData, resultData] = await Promise.all([
        api.backtestScatter(startDate, endDate).catch(() => []),
        api.backtestResult(startDate, endDate).catch(() => null),
      ]);
      setScatter(Array.isArray(scatterData) ? scatterData : []);
      setResult(resultData);
    } catch (e: any) {
      setError(e?.message ?? "加载失败");
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    load();
  }, []);

  return (
    <div className="space-y-4">
      <PageHeader
        title="简化回测"
        subtitle="基因得分 vs 次日表现（教育性统计，非收益保证）"
        actions={
          <button
            onClick={load}
            disabled={loading}
            className="inline-flex items-center gap-2 rounded-lg bg-primary/90 px-3 py-2 text-sm text-primary-foreground hover:bg-primary disabled:opacity-60"
          >
            {loading ? <Loader2 className="h-4 w-4 animate-spin" /> : <RefreshCw className="h-4 w-4" />}
            刷新
          </button>
        }
      />

      <Disclaimer compact />

      {error && (
        <GlassCard>
          <div className="p-4 text-sm text-red-600 flex items-center gap-2">
            <AlertCircle className="h-4 w-4 shrink-0" /> {error}
          </div>
        </GlassCard>
      )}

      <GlassCard>
        <SectionHeader title="查询条件" />
        <div className="flex flex-wrap items-end gap-3">
          <div className="flex flex-col gap-1">
            <label className="text-xs text-muted-foreground">开始日期</label>
            <input
              type="date"
              value={startDate}
              onChange={(e) => setStartDate(e.target.value)}
              className="rounded-lg border border-border bg-background px-3 py-1.5 text-sm"
            />
          </div>
          <div className="flex flex-col gap-1">
            <label className="text-xs text-muted-foreground">结束日期</label>
            <input
              type="date"
              value={endDate}
              onChange={(e) => setEndDate(e.target.value)}
              className="rounded-lg border border-border bg-background px-3 py-1.5 text-sm"
            />
          </div>
          <button
            onClick={load}
            disabled={loading}
            className="rounded-lg bg-primary/90 px-4 py-1.5 text-sm text-primary-foreground hover:bg-primary disabled:opacity-60"
          >
            查询
          </button>
        </div>
      </GlassCard>

      {result && (
        <div className="grid gap-3 md:grid-cols-3">
          <MetricCard label="总信号数" value={result.total_signals} />
          <MetricCard label="命中率" value={`${(result.hit_rate * 100).toFixed(1)}%`} />
          <MetricCard label="平均收益" value={`${(result.avg_return * 100).toFixed(2)}%`} />
          <MetricCard label="最大回撤" value={`${(result.max_drawdown * 100).toFixed(2)}%`} />
          <MetricCard label="夏普比率" value={result.sharpe_ratio.toFixed(2)} />
          <MetricCard label="统计区间" value={result.period} />
        </div>
      )}

      {scatter.length > 0 && (
        <GlassCard>
          <h3 className="mb-3 text-sm font-semibold">散点数据（近 {scatter.length} 条）</h3>
          <div className="max-h-96 space-y-1 overflow-y-auto">
            {scatter.slice(0, 100).map((p, idx) => (
              <div key={idx} className="flex items-center justify-between text-xs">
                <span className="text-muted-foreground">{p.date} · {p.code}</span>
                <span className="font-medium">
                  基因 {p.gene_score.toFixed(1)} · 次日 {(p.next_day_return * 100).toFixed(2)}%
                </span>
              </div>
            ))}
          </div>
          {scatter.length > 100 && (
            <div className="mt-2 text-xs text-muted-foreground">仅展示前 100 条</div>
          )}
        </GlassCard>
      )}

      {!loading && scatter.length === 0 && !error && (
        <EmptyState
          icon={<RefreshCw className="h-8 w-8 text-muted-foreground/40" />}
          title="暂无回测数据"
          description="选择日期范围后点击查询，查看基因得分与次日表现统计。"
        />
      )}
    </div>
  );
}
