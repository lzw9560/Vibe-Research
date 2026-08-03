// S025-B1 胜率概览区：6 张 MetricCard 矩阵消费 useWinRateStats。
// 三态：loading→Skeleton；error/empty→EmptyState；success→总交易/胜数/胜率/平均收益/最大回撤/夏普。
import { useWinRateStats } from "@/lib/query";
import { MetricCard } from "@/components/ui/MetricCard";
import { SkeletonMetrics } from "@/components/ui/Skeleton";
import { EmptyState } from "@/components/ui/EmptyState";

interface StatsMetricsProps {
  windowSize: number;
}

// 胜率/收益统一格式化：0.6 → "60.0%"，1.5 → "1.50%"。
const pct = (v: number) => `${(v * 100).toFixed(1)}%`;
const pct2 = (v: number) => `${v.toFixed(2)}%`;

export function StatsMetrics({ windowSize }: StatsMetricsProps) {
  const { data, isLoading, isError } = useWinRateStats(windowSize);

  if (isLoading) {
    return <SkeletonMetrics count={6} />;
  }
  if (isError || !data) {
    return <EmptyState title="暂无胜率统计" description="未加载到统计数据，稍后重试" />;
  }

  return (
    <div className="grid grid-cols-2 gap-3 sm:grid-cols-3 lg:grid-cols-6">
      <MetricCard label="总交易" value={data.total_trades} />
      <MetricCard label="胜数" value={data.win_count} />
      <MetricCard label="胜率" value={pct(data.win_rate)} />
      <MetricCard label="平均收益" value={pct2(data.avg_return)} />
      <MetricCard label="最大回撤" value={pct2(data.max_drawdown)} />
      <MetricCard label="夏普" value={data.sharpe_ratio.toFixed(2)} />
    </div>
  );
}
