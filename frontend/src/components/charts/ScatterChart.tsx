// S025-D1 散点图：echarts 散点（gene_score vs next_day_return）。
// 复用 TrendsChart 初始化模式：useEffect + echarts.init + setOption + resize 监听 + dispose。
// 空数据显占位。tooltip 展示个股 code / 基因得分 / 次日收益。
import { useEffect, useRef } from "react";
import * as echarts from "echarts";

export interface ScatterPoint {
  gene_score: number;
  next_day_return: number;
  code: string;
  date?: string;
  industry?: string;
}

interface ScatterChartProps {
  points: ScatterPoint[];
  height?: number;
}

interface TooltipData {
  value?: number[];
  code?: string;
}

/**
 * echarts 散点：x=基因得分, y=次日收益。Backtest 散点升级（自纯文本列表）。
 */
export function ScatterChart({ points, height = 360 }: ScatterChartProps) {
  const chartRef = useRef<HTMLDivElement>(null);
  const instanceRef = useRef<echarts.ECharts | null>(null);

  useEffect(() => {
    if (!chartRef.current || points.length === 0) return;
    instanceRef.current = echarts.init(chartRef.current);
    const option: echarts.EChartsOption = {
      tooltip: {
        trigger: "item",
        formatter: (params: unknown) => {
          const p = params as { data?: TooltipData };
          const d = p.data;
          if (!d || !d.value) return "";
          const [gs, ret] = d.value;
          return `${d.code ?? ""}<br/>基因: ${gs.toFixed(1)}<br/>次日: ${(ret * 100).toFixed(2)}%`;
        },
      },
      grid: { left: 56, right: 20, top: 24, bottom: 40 },
      xAxis: {
        type: "value",
        name: "基因得分",
        nameLocation: "middle",
        nameGap: 26,
        scale: true,
      },
      yAxis: {
        type: "value",
        name: "次日收益",
        nameGap: 32,
        axisLabel: {
          formatter: (value: number | string) =>
            `${(Number(value) * 100).toFixed(0)}%`,
        },
      },
      series: [
        {
          type: "scatter",
          data: points.map((p) => ({
            value: [p.gene_score, p.next_day_return],
            code: p.code,
          })),
          symbolSize: 8,
          itemStyle: { color: "#fb923c", opacity: 0.75 },
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
  }, [points]);

  if (points.length === 0) {
    return (
      <div className="flex h-[320px] items-center justify-center text-sm text-muted-foreground/60">
        暂无散点数据
      </div>
    );
  }

  return <div ref={chartRef} className="w-full" style={{ height }} />;
}
