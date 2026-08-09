import { useState, useEffect } from "react";
import { PageHeader } from "@/components/ui/PageHeader";
import { GlassCard } from "@/components/ui/GlassCard";
import { SectionHeader } from "@/components/ui/SectionHeader";
import { MetricCard } from "@/components/ui/MetricCard";
import { EmptyState } from "@/components/ui/EmptyState";
import { Disclaimer } from "@/components/ui/Disclaimer";
import { TabBar } from "@/components/ui/TabBar";
import { ScatterChart } from "@/components/charts/ScatterChart";
import {
  HitRateChart,
  AvgReturnChart,
  StrategyWinRateChart,
} from "@/components/charts/TrendChart";
import { WinRateView } from "@/components/winrate/WinRateView";
import { Loader2, RefreshCw, AlertCircle, TrendingUp } from "lucide-react";
import { api, type BacktestResult, type BacktestScatterPoint, type BacktestSnapshotRow } from "@/lib/api";

// 页内 Tab key 对齐 nav SUB_TABS["/backtest"]（result / winrate / trend）。
type BacktestTab = "result" | "winrate" | "trend";

const TABS: { key: BacktestTab; label: string }[] = [
  { key: "result", label: "回测结果" },
  { key: "winrate", label: "胜率趋势" },
  { key: "trend", label: "趋势看板" },
];

export default function Backtest() {
  const [activeTab, setActiveTab] = useState<BacktestTab>("result");
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

  // S041 趋势看板态：独立于 result tab 的查询条件——趋势是固定 90 天快照，无日期选择器。
  const [trendRows, setTrendRows] = useState<BacktestSnapshotRow[]>([]);
  const [trendLoading, setTrendLoading] = useState(false);
  const [trendError, setTrendError] = useState<string | null>(null);

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
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : "加载失败");
    } finally {
      setLoading(false);
    }
  };

  const loadTrend = async () => {
    setTrendLoading(true);
    setTrendError(null);
    try {
      const data = await api.backtestTrend(90);
      setTrendRows(Array.isArray(data) ? data : []);
    } catch (e: unknown) {
      setTrendError(e instanceof Error ? e.message : "趋势数据加载失败");
    } finally {
      setTrendLoading(false);
    }
  };

  useEffect(() => {
    load();
  }, []);

  // 切到趋势 tab 时懒加载趋势数据（首次进入才请求，重进不重复请求除非手动刷新）
  useEffect(() => {
    if (activeTab === "trend" && trendRows.length === 0 && !trendLoading && !trendError) {
      loadTrend();
    }
  }, [activeTab]);

  return (
    <div className="space-y-4">
      <PageHeader
        title="简化回测"
        subtitle="基因得分 vs 次日表现（教育性统计，非收益保证）"
        actions={
          <button
            onClick={() => (activeTab === "trend" ? loadTrend() : load())}
            disabled={activeTab === "trend" ? trendLoading : loading}
            className="inline-flex items-center gap-2 rounded-lg bg-primary/90 px-3 py-2 text-sm text-primary-foreground hover:bg-primary disabled:opacity-60"
          >
            {((activeTab === "trend" ? trendLoading : loading))
              ? <Loader2 className="h-4 w-4 animate-spin" />
              : <RefreshCw className="h-4 w-4" />}
            刷新
          </button>
        }
      />

      <Disclaimer compact />

      <TabBar
        tabs={TABS}
        activeKey={activeTab}
        onChange={(k) => setActiveTab(k as BacktestTab)}
      />

      {activeTab === "winrate" ? (
        <WinRateView defaultWindow={30} />
      ) : activeTab === "trend" ? (
        <>
          {trendError && (
            <GlassCard>
              <div className="p-4 text-sm text-red-600 flex items-center gap-2">
                <AlertCircle className="h-4 w-4 shrink-0" /> {trendError}
              </div>
            </GlassCard>
          )}

          {trendLoading && (
            <GlassCard>
              <div className="flex h-[320px] items-center justify-center text-sm text-muted-foreground/60">
                <Loader2 className="mr-2 h-4 w-4 animate-spin" /> 加载趋势数据…
              </div>
            </GlassCard>
          )}

          {!trendLoading && !trendError && trendRows.length === 0 && (
            <EmptyState
              icon={<TrendingUp className="h-8 w-8 text-muted-foreground/40" />}
              title="暂无趋势快照"
              description="每日收盘后定时任务 daily_backtest_run 会落库命中率/收益/战法胜率快照，积累后此处显示趋势。"
            />
          )}

          {!trendLoading && !trendError && trendRows.length > 0 && (
            <>
              <GlassCard>
                <SectionHeader
                  title="命中率趋势"
                  subtitle="backtest_lite · 30 天滚动窗口每日快照"
                />
                <HitRateChart rows={trendRows} />
              </GlassCard>

              <GlassCard>
                <SectionHeader
                  title="平均收益趋势"
                  subtitle="backtest_lite · 30 天滚动窗口每日快照"
                />
                <AvgReturnChart rows={trendRows} />
              </GlassCard>

              <GlassCard>
                <SectionHeader
                  title="战法胜率趋势"
                  subtitle="strategy_backtest · 8 战法每日快照"
                />
                <StrategyWinRateChart rows={trendRows} />
              </GlassCard>
            </>
          )}
        </>
      ) : (
        <>
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
              <SectionHeader title="散点分布" />
              <ScatterChart points={scatter} />
            </GlassCard>
          )}

          {!loading && scatter.length === 0 && !error && (
            <EmptyState
              icon={<RefreshCw className="h-8 w-8 text-muted-foreground/40" />}
              title="暂无回测数据"
              description="选择日期范围后点击查询，查看基因得分与次日表现统计。"
            />
          )}
        </>
      )}
    </div>
  );
}
