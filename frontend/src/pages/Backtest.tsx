import { useState, useEffect } from "react";
import { Loader2, RefreshCw } from "lucide-react";
import { PageHeader } from "@/components/ui/PageHeader";
import { GlassCard } from "@/components/ui/GlassCard";
import { Disclaimer } from "@/components/ui/Disclaimer";
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
          <div className="p-4 text-sm text-red-600">加载失败：{error}</div>
        </GlassCard>
      )}

      <GlassCard>
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
          <GlassCard>
            <div className="text-xs text-muted-foreground">总信号数</div>
            <div className="mt-1 text-2xl font-bold">{result.total_signals}</div>
          </GlassCard>
          <GlassCard>
            <div className="text-xs text-muted-foreground">命中率</div>
            <div className="mt-1 text-2xl font-bold">{(result.hit_rate * 100).toFixed(1)}%</div>
          </GlassCard>
          <GlassCard>
            <div className="text-xs text-muted-foreground">平均收益</div>
            <div className="mt-1 text-2xl font-bold">{(result.avg_return * 100).toFixed(2)}%</div>
          </GlassCard>
          <GlassCard>
            <div className="text-xs text-muted-foreground">最大回撤</div>
            <div className="mt-1 text-2xl font-bold">{(result.max_drawdown * 100).toFixed(2)}%</div>
          </GlassCard>
          <GlassCard>
            <div className="text-xs text-muted-foreground">夏普比率</div>
            <div className="mt-1 text-2xl font-bold">{result.sharpe_ratio.toFixed(2)}</div>
          </GlassCard>
          <GlassCard>
            <div className="text-xs text-muted-foreground">统计区间</div>
            <div className="mt-1 text-sm font-medium">{result.period}</div>
          </GlassCard>
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
        <GlassCard>
          <div className="p-6 text-center text-sm text-muted-foreground">暂无回测数据</div>
        </GlassCard>
      )}
    </div>
  );
}
