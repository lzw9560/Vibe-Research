import { useEffect, useRef, useState, useCallback } from "react";
import { Loader2, RefreshCw } from "lucide-react";
import { GlassCard } from "@/components/ui/GlassCard";
import { cn } from "@/lib/utils";
import { api, ApiError, type STITimelineItem } from "@/lib/api";

// 阶段 → 图表色
const PHASE_LINE_COLOR: Record<string, string> = {
  "高潮": "#ef4444",
  "启动": "#f97316",
  "分歧": "#eab308",
  "冰点": "#6b7280",
  "退潮": "#a855f7",
};

interface Props {
  className?: string;
}

export function STITimelineChart({ className }: Props) {
  const chartRef = useRef<HTMLDivElement>(null);
  const instanceRef = useRef<any>(null);
  const [data, setData] = useState<STITimelineItem[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [echarts, setEcharts] = useState<typeof import("echarts") | null>(null);

  const loadData = useCallback(() => {
    setLoading(true);
    api.stiTimeline(30)
      .then(setData)
      .catch((e) => setError(e instanceof ApiError ? e.message : "时间线加载失败"))
      .finally(() => setLoading(false));
  }, []);

  useEffect(() => { loadData(); }, [loadData]);

  // 动态加载 echarts
  useEffect(() => {
    import("echarts").then((module) => {
      setEcharts(() => module);
    });
  }, []);

  // ECharts 渲染
  useEffect(() => {
    if (!chartRef.current || !echarts) return;
    instanceRef.current = echarts.init(chartRef.current);

    const dates = data.map((d) => d.date);
    const scores = data.map((d) => d.score ?? null);
    const phases = data.map((d) => d.phase ?? "");

    const visualMap: Array<{ dataIndex: number; itemStyle: { color: string } }> = [];
    scores.forEach((s, i) => {
      if (s != null) {
        visualMap.push({
          dataIndex: i,
          itemStyle: { color: PHASE_LINE_COLOR[phases[i]] ?? "#f97316" },
        });
      }
    });

    const option: import("echarts").EChartsOption = {
      tooltip: {
        trigger: "axis",
        backgroundColor: "hsl(var(--card))",
        borderColor: "hsl(var(--border))",
        textStyle: { color: "hsl(var(--foreground))", fontSize: 12 },
        formatter: (params: any) => {
          if (!params || !params.length) return "";
          const p = params[0];
          const idx = p.dataIndex;
          const phase = phases[idx];
          const change = data[idx]?.change_from_yesterday;
          let extra = "";
          if (change != null) {
            extra = `<br/>较昨日: ${change > 0 ? "+" : ""}${change.toFixed(1)}`;
          }
          return `<b>${dates[idx]}</b><br/>
            分数: <b style="color:${PHASE_LINE_COLOR[phase] || '#f97316'}">${scores[idx]}</b><br/>
            阶段: ${phase || "—"}${extra}`;
        },
      },
      grid: { left: 45, right: 15, top: 15, bottom: 35 },
      xAxis: {
        type: "category",
        data: dates,
        axisLine: { lineStyle: { color: "hsl(var(--chart-axis))" } },
        axisLabel: { color: "hsl(var(--chart-text))", fontSize: 10, rotate: 45 },
        axisTick: { show: false },
      },
      yAxis: {
        type: "value",
        min: 0,
        max: 100,
        name: "STI 分数",
        nameTextStyle: { fontSize: 10, color: "hsl(var(--chart-text))" },
        axisLine: { lineStyle: { color: "hsl(var(--chart-axis))" } },
        splitLine: { lineStyle: { color: "hsl(var(--chart-grid))" } },
        axisLabel: { color: "hsl(var(--chart-text))", fontSize: 10 },
      },
      series: [
        {
          name: "STI 分数",
          type: "line",
          data: scores,
          smooth: 0.35,
          symbol: "circle",
          symbolSize: 8,
          connectNulls: false,
          lineStyle: { width: 2.5 },
          itemStyle: {
            color: (params: any) => {
              const idx = params.dataIndex;
              return PHASE_LINE_COLOR[phases[idx]] ?? "#f97316";
            },
          },
          emphasis: {
            focus: "series",
            itemStyle: { borderWidth: 3, shadowBlur: 10, shadowColor: "hsl(var(--primary) / 0.4)" },
          },
          areaStyle: {
            color: new echarts.graphic.LinearGradient(0, 0, 0, 1, [
              { offset: 0, color: "hsl(var(--primary) / 0.25)" },
              { offset: 1, color: "hsl(var(--primary) / 0.02)" },
            ]),
          },
        },
      ],
      // 阶段色带（底部标记）
      graphic: phases.map((p, i) => ({
        type: "text",
        silent: true,
        style: {
          text: p || "",
          fill: PHASE_LINE_COLOR[p] || "#6b7280",
          fontSize: 9,
          textAlign: "center",
          textBaseline: "top",
        },
        position: [
          (i / Math.max(dates.length - 1, 1)) * 100 + "%",
          38,
        ],
      })),
    };

    instanceRef.current.setOption(option);

    const onResize = () => instanceRef.current?.resize();
    window.addEventListener("resize", onResize);
    return () => {
      window.removeEventListener("resize", onResize);
      instanceRef.current?.dispose();
      instanceRef.current = null;
    };
  }, [data, echarts]);

  if (loading) {
    return (
      <GlassCard className={cn("mb-6", className)}>
        <div className="flex items-center justify-center py-10">
          <Loader2 className="h-5 w-5 animate-spin text-primary" />
          <span className="ml-2 text-sm text-muted-foreground">加载 STI 时间线…</span>
        </div>
      </GlassCard>
    );
  }

  if (error) {
    return (
      <GlassCard className={cn("mb-6", className)}>
        <div className="flex items-center justify-between">
          <h3 className="text-sm font-semibold text-muted-foreground">情绪温度时间线</h3>
          <button onClick={loadData} className="text-muted-foreground hover:text-primary">
            <RefreshCw className="h-3.5 w-3.5" />
          </button>
        </div>
        <p className="mt-3 text-sm text-destructive/80">{error}</p>
      </GlassCard>
    );
  }

  if (data.length === 0) {
    return (
      <GlassCard className={cn("mb-6", className)}>
        <div className="flex items-center justify-between">
          <h3 className="text-sm font-semibold text-muted-foreground">情绪温度时间线</h3>
          <button onClick={loadData} className="text-muted-foreground hover:text-primary">
            <RefreshCw className="h-3.5 w-3.5" />
          </button>
        </div>
        <div className="mt-3 rounded-lg border border-border/40 bg-muted/15 p-4 text-center">
          <p className="text-sm text-muted-foreground">暂无时间线数据</p>
          <p className="mt-1 text-[11px] text-muted-foreground/50">最近 30 个交易日的情绪温度走势</p>
        </div>
      </GlassCard>
    );
  }

  const latest = data[data.length - 1];
  const phaseColor = PHASE_LINE_COLOR[latest.phase || ""] || "text-muted-foreground";

  return (
    <GlassCard className={cn("mb-6", className)}>
      <div className="mb-3 flex items-center justify-between">
        <div className="flex items-center gap-2">
          <h3 className="text-sm font-semibold text-muted-foreground">情绪温度时间线（30 日）</h3>
          <span className={cn("text-xs font-medium", phaseColor)}>{latest.phase}</span>
        </div>
        <button onClick={loadData} className="text-muted-foreground hover:text-primary" title="刷新">
          <RefreshCw className="h-3.5 w-3.5" />
        </button>
      </div>

      {/* 摘要 */}
      <div className="mb-3 grid grid-cols-3 gap-2 sm:grid-cols-4">
        <div className="rounded-lg bg-muted/20 p-2 text-center">
          <p className="text-[10px] text-muted-foreground">最新分数</p>
          <p className={cn("font-mono text-lg font-bold", phaseColor)}>
            {latest.score?.toFixed(1) ?? "—"}
          </p>
        </div>
        <div className="rounded-lg bg-muted/20 p-2 text-center">
          <p className="text-[10px] text-muted-foreground">最高分</p>
          <p className="font-mono text-lg font-bold text-danger">
            {Math.max(...data.map((d) => d.score ?? 0)).toFixed(1)}
          </p>
        </div>
        <div className="rounded-lg bg-muted/20 p-2 text-center">
          <p className="text-[10px] text-muted-foreground">最低分</p>
          <p className="font-mono text-lg font-bold text-success">
            {Math.min(...data.map((d) => d.score ?? 100)).toFixed(1)}
          </p>
        </div>
        <div className="rounded-lg bg-muted/20 p-2 text-center">
          <p className="text-[10px] text-muted-foreground">数据天数</p>
          <p className="font-mono text-lg font-bold text-foreground">{data.length}</p>
        </div>
      </div>

      <div ref={chartRef} className="h-[220px]" />

      {/* 图例 */}
      <div className="mt-2 flex flex-wrap gap-3 text-[10px] text-muted-foreground">
        {Object.entries(PHASE_LINE_COLOR).map(([phase, color]) => (
          <span key={phase} className="flex items-center gap-1">
            <span className="h-2 w-2 rounded-full" style={{ backgroundColor: color }} />
            {phase}
          </span>
        ))}
      </div>
    </GlassCard>
  );
}
