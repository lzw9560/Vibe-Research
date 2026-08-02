/** 基因得分雷达图 */
import { useEffect, useRef } from "react";
import * as echarts from "echarts";

const FACTOR_KEYS = ["次日溢价率", "红盘率", "封板率", "炸板后溢价", "涨停频次"];

export function GeneScoreChart({ factors, wilsonAdjusted }: { factors: Record<string, number>; wilsonAdjusted: number }) {
  const chartRef = useRef<HTMLDivElement>(null);
  const instanceRef = useRef<echarts.ECharts | null>(null);

  useEffect(() => {
    if (!chartRef.current) return;
    instanceRef.current = echarts.init(chartRef.current);
    const indicator = FACTOR_KEYS.map((k) => ({ name: String(k), max: 100 }));
    const values = FACTOR_KEYS.map((k) => Number(factors[k]) ?? 0);
    const option: echarts.EChartsOption = {
      tooltip: { trigger: "item" },
      radar: {
        indicator,
        radius: "65%",
        axisName: { color: "#9ca3af", fontSize: 11 },
        splitArea: { areaStyle: { color: ["rgba(251,146,60,0.02)", "rgba(251,146,60,0.05)"] } },
      },
      series: [{
        type: "radar",
        data: [{
          value: values,
          name: "基因因子",
          areaStyle: { color: "rgba(251, 146, 60, 0.25)" },
          lineStyle: { color: "#fb923c", width: 2 },
          itemStyle: { color: "#fb923c" },
        }],
      }],
    };
    instanceRef.current.setOption(option);
    return () => { instanceRef.current?.dispose(); instanceRef.current = null; };
  }, [factors, wilsonAdjusted]);

  return <div ref={chartRef} className="h-[220px]" />;
}
