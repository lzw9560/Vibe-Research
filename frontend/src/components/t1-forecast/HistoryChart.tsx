// components/t1-forecast/HistoryChart.tsx — S232 T+1 信号历史命中率趋势图。
// daily 命中率（波动）+ 累积命中率（收敛到预期 4.34%）+ 预期基准线。
import { useRef } from "react";
import type { EChartsOption } from "echarts";
import { GlassCard } from "@/components/ui/GlassCard";
import { useECharts } from "@/hooks/useECharts";
import { useT1History, type T1HistoryData } from "@/lib/query/t1_forecast";

function buildOption(data: T1HistoryData): EChartsOption {
  const daily = data.daily;
  // 累积命中率逐日计算
  let cumH = 0;
  let cumS = 0;
  const cumRates = daily.map((d) => {
    cumH += d.hit;
    cumS += d.total;
    return cumS ? (cumH / cumS) * 100 : 0;
  });
  return {
    tooltip: { trigger: "axis", formatter: (p: unknown) => {
      const params = p as Array<{ name: string; value: number; seriesName: string }>;
      if (!params.length) return "";
      return `${params[0].name}<br/>${params.map(p => `${p.seriesName}: ${p.value}%`).join("<br/>")}`;
    }},
    legend: { data: ["单日命中率%", "累积命中率%", "预期 4.34%"], top: 0 },
    grid: { left: 40, right: 20, top: 40, bottom: 50 },
    xAxis: {
      type: "category",
      data: daily.map((d) => d.date),
      axisLabel: { rotate: 45, fontSize: 10 },
    },
    yAxis: { type: "value", axisLabel: { formatter: "{value}%" }, max: 20 },
    series: [
      {
        name: "单日命中率%",
        type: "line",
        data: daily.map((d) => +(d.rate * 100).toFixed(2)),
        itemStyle: { color: "#3b82f6" },
        symbol: "circle",
        symbolSize: 4,
      },
      {
        name: "累积命中率%",
        type: "line",
        data: cumRates.map((r) => +r.toFixed(2)),
        itemStyle: { color: "#10b981" },
        smooth: true,
        symbol: "none",
      },
      {
        name: "预期 4.34%",
        type: "line",
        data: daily.map(() => 4.34),
        itemStyle: { color: "#ef4444" },
        symbol: "none",
        lineStyle: { type: "dashed" },
      },
    ],
  };
}

export function HistoryChart() {
  const { data, isLoading, error } = useT1History();
  const ref = useRef<HTMLDivElement>(null);

  useECharts(ref, () => (data ? buildOption(data) : {}), [data], { skip: !data });

  if (isLoading) {
    return (
      <GlassCard className="p-4">
        <p className="text-sm text-muted-foreground">加载历史命中率...</p>
      </GlassCard>
    );
  }
  if (error) {
    return (
      <GlassCard className="p-4">
        <p className="text-sm text-red-500">加载失败：{String(error)}</p>
      </GlassCard>
    );
  }
  if (!data || data.daily.length === 0) return null;

  const cum = data.cumulative;
  const dev = cum.deviation_pct;
  const devColor = dev != null && Math.abs(dev) > 30 ? "text-red-500" : "text-green-500";

  return (
    <GlassCard className="p-4">
      <div className="mb-2">
        <h3 className="text-lg font-semibold">📈 T+1 信号历史命中率趋势</h3>
        <p className="text-sm text-muted-foreground mt-1">
          {cum.days} 天 · {cum.total} 信号股 · {cum.hit} 命中 · 累积命中率{" "}
          <span className="font-semibold">{(cum.rate * 100).toFixed(2)}%</span>
          （预期 {(cum.expected_rate * 100).toFixed(2)}%，偏差{" "}
          <span className={devColor}>{dev != null ? `${dev > 0 ? "+" : ""}${dev}%` : "N/A"}</span>）
        </p>
      </div>
      <div ref={ref} style={{ width: "100%", height: 300 }} />
      <p className="text-xs text-muted-foreground mt-2">
        蓝线=单日命中率（小样本波动大）· 绿线=累积命中率（收敛到预期）· 红虚线=预期 4.34%
      </p>
    </GlassCard>
  );
}
