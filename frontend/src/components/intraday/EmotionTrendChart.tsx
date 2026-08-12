// S063 T21：Layer 1 盘中情绪走势图——ECharts 折线+面积图。
// T-1 基线虚线 + 三色区间带 + 当前点高亮 + 趋势箭头；4 维度小折线可折叠。
import { useRef, useState } from "react";
import { TrendingUp, TrendingDown, Minus, ChevronDown } from "lucide-react";
import { useECharts } from "@/hooks/useECharts";
import { useIntradayTimeline } from "@/lib/query";
import { cn } from "@/lib/utils";
import type { IntradaySnapshot } from "@/lib/api";

const ZONE_COLORS = {
  green: "#22c55e",
  yellow: "#f59e0b",
  red: "#ef4444",
} as const;

export function EmotionTrendChart() {
  const chartRef = useRef<HTMLDivElement>(null);
  const [showDetails, setShowDetails] = useState(false);
  const { data, isLoading } = useIntradayTimeline();

  const snapshots: IntradaySnapshot[] = data?.snapshots ?? [];
  const valid = snapshots.filter((s) => s.score != null);
  const latest = valid[valid.length - 1];
  const t1Baseline = latest?.t1_baseline ?? null;
  const trend = latest?.trend ?? "flat";

  useECharts(
    chartRef,
    () => {
      const times = valid.map((s) => s.time);
      const scores = valid.map((s) => s.score);
      const baseline = t1Baseline ?? 50;

      return {
        tooltip: { trigger: "axis" },
        legend: { data: ["盘中分数", "T-1 基线"], top: 4 },
        grid: { left: 40, right: 16, top: 32, bottom: 28 },
        xAxis: { type: "category", data: times },
        yAxis: { type: "value", min: 0, max: 100, name: "分数" },
        series: [
          {
            name: "盘中分数",
            type: "line",
            smooth: true,
            data: scores,
            itemStyle: { color: "#fb923c" },
            lineStyle: { color: "#fb923c", width: 2 },
            areaStyle: { color: "rgba(251,146,60,0.15)" },
            markArea: {
              silent: true,
              itemStyle: { color: "rgba(34,197,94,0.06)" },
              data: [[{ yAxis: baseline - 5 }, { yAxis: baseline + 5 }]],
            },
          },
          {
            name: "T-1 基线",
            type: "line",
            data: times.map(() => baseline),
            lineStyle: { type: "dashed", color: "#94a3b8", width: 1.5 },
            symbol: "none",
            silent: true,
          },
        ],
      };
    },
    [valid, t1Baseline],
    { skip: valid.length === 0 },
  );

  if (isLoading) {
    return <div className="h-[280px] w-full animate-pulse rounded-lg bg-muted/20" aria-busy="true" />;
  }

  if (valid.length === 0) {
    return (
      <div className="flex h-[200px] items-center justify-center rounded-lg bg-muted/10 text-sm text-muted-foreground">
        暂无盘中采样数据（非交易时段或未启动）
      </div>
    );
  }

  const TrendIcon = trend === "up" ? TrendingUp : trend === "down" ? TrendingDown : Minus;
  const trendColor = trend === "up" ? "text-success" : trend === "down" ? "text-destructive" : "text-muted-foreground";

  return (
    <div className="space-y-3">
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-2">
          <span className="text-sm font-medium">盘中情绪走势</span>
          {latest && (
            <span className={cn("flex items-center gap-0.5 text-sm font-bold", trendColor)}>
              {latest.score?.toFixed(1)}
              <TrendIcon className="h-3.5 w-3.5" />
            </span>
          )}
          {latest?.zone && (
            <span
              className="rounded px-1.5 py-0.5 text-[10px] text-white"
              style={{ background: ZONE_COLORS[latest.zone] }}
            >
              {latest.zone === "green" ? "一致" : latest.zone === "yellow" ? "走偏" : "背离"}
            </span>
          )}
        </div>
        <button
          onClick={() => setShowDetails(!showDetails)}
          className="flex items-center gap-1 text-xs text-muted-foreground hover:text-foreground"
        >
          维度明细
          <ChevronDown className={cn("h-3 w-3 transition-transform", showDetails && "rotate-180")} />
        </button>
      </div>

      <div ref={chartRef} className="h-[240px] w-full" />

      {showDetails && <DimensionDetails snapshots={valid} />}
    </div>
  );
}

function DimensionDetails({ snapshots }: { snapshots: IntradaySnapshot[] }) {
  const dims = [
    { key: "zt_count" as const, label: "涨停家数" },
    { key: "seal_rate" as const, label: "封板率" },
    { key: "break_rate" as const, label: "炸板率" },
    { key: "ad_ratio" as const, label: "涨跌比" },
  ];

  return (
    <div className="grid grid-cols-2 gap-2 lg:grid-cols-4">
      {dims.map((d) => {
        const values = snapshots.map((s) => s[d.key]).filter((v): v is number => v != null);
        const latest = values[values.length - 1];
        return (
          <div key={d.key} className="rounded border border-border/40 p-2">
            <p className="text-[10px] text-muted-foreground">{d.label}</p>
            <p className="text-sm font-semibold">{latest != null ? latest.toFixed(2) : "—"}</p>
          </div>
        );
      })}
    </div>
  );
}
