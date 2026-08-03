// S025-B2 胜率趋势区：echarts 折线（胜率随日期）。
// 复用 GeneScoreChart 初始化模式：useEffect + echarts.init + setOption + dispose；
// 增 resize 监听（窗口缩放自适应）。消费 useWinRateTrends。
import { useEffect, useRef } from "react";
import * as echarts from "echarts";
import { useWinRateTrends } from "@/lib/query";
import type { WinRateTrendPoint } from "@/lib/api";

interface TrendsChartProps {
  windowSize: number;
}

export function TrendsChart({ windowSize }: TrendsChartProps) {
  const chartRef = useRef<HTMLDivElement>(null);
  const instanceRef = useRef<echarts.ECharts | null>(null);
  const { data, isLoading, isError } = useWinRateTrends(windowSize);

  useEffect(() => {
    if (!chartRef.current || !data || data.length === 0) return;
    instanceRef.current = echarts.init(chartRef.current);
    const points: WinRateTrendPoint[] = data;
    const option: echarts.EChartsOption = {
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
    instanceRef.current.setOption(option);

    const onResize = () => instanceRef.current?.resize();
    window.addEventListener("resize", onResize);
    return () => {
      window.removeEventListener("resize", onResize);
      instanceRef.current?.dispose();
      instanceRef.current = null;
    };
  }, [data]);

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
