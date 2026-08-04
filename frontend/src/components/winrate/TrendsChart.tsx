// S025-B2 胜率趋势区：echarts 折线（胜率随日期）。
// 复用 useECharts hook（S024-B 抽公共）：init+setOption+resize+dispose 统一管理。
// 消费 useWinRateTrends。
import { useRef } from "react";
import { useECharts } from "@/hooks/useECharts";
import { useWinRateTrends } from "@/lib/query";
import type { WinRateTrendPoint } from "@/lib/api";

interface TrendsChartProps {
  windowSize: number;
}

export function TrendsChart({ windowSize }: TrendsChartProps) {
  const chartRef = useRef<HTMLDivElement>(null);
  const { data, isLoading, isError } = useWinRateTrends(windowSize);

  useECharts(
    chartRef,
    () => {
      const points: WinRateTrendPoint[] = data ?? [];
      return {
        tooltip: { trigger: "axis" },
        grid: { left: 36, right: 16, top: 24, bottom: 28 },
        xAxis: { type: "category", data: points.map((p) => p.date) },
        yAxis: {
          type: "value",
          name: "胜率(%)",
          min: 0,
        },
        series: [
          {
            name: "胜率",
            type: "line",
            smooth: true,
            data: points.map((p) => Math.round(p.win_rate * 100)),
            itemStyle: { color: "#fb923c" },
            lineStyle: { color: "#fb923c", width: 2 },
            areaStyle: { color: "rgba(251,146,60,0.12)" },
          },
        ],
      };
    },
    [data],
    { skip: !data || data.length === 0 },
  );

  if (isLoading) {
    return <div className="h-[300px] w-full animate-pulse rounded-lg bg-muted/20" aria-busy="true" />;
  }
  if (isError || !data || data.length === 0) {
    return (
      <div className="flex h-[300px] items-center justify-center text-sm text-muted-foreground/60">
        暂无趋势数据
      </div>
    );
  }

  return <div ref={chartRef} className="h-[300px] w-full" />;
}
