import { useRef, useState, useCallback, useEffect } from "react";
import { Loader2, RefreshCw } from "lucide-react";
import * as echarts from "echarts/core";
import { GlassCard } from "@/components/ui/GlassCard";
import { cn } from "@/lib/utils";
import { api, ApiError, type STITimelineItem } from "@/lib/api";
import { useECharts } from "@/hooks/useECharts";

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
  const [data, setData] = useState<STITimelineItem[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  // Defensive: filter out items with missing date or score to prevent ECharts crashes
  const validData = data.filter(
    (d): d is NonNullable<typeof d> & { date: string; score: number } =>
      d != null && d.date != null && d.date !== "" && d.score != null
  );

  const loadData = useCallback(() => {
    setLoading(true);
    api.stiTimeline(60)
      .then(setData)
      .catch((e) => setError(e instanceof ApiError ? e.message : "时间线加载失败"))
      .finally(() => setLoading(false));
  }, []);

  useEffect(() => { loadData(); }, [loadData]);

  useECharts(
    chartRef,
    () => {
      const dates = validData.map((d) => d.date);
      const scores = validData.map((d) => d.score);
      const phases = validData.map((d) => d.phase ?? "");

      const visualMap: Array<{ dataIndex: number; itemStyle: { color: string } }> = [];
      validData.forEach((d, i) => {
        if (d.score != null) {
          visualMap.push({
            dataIndex: i,
            itemStyle: { color: PHASE_LINE_COLOR[d.phase || ""] ?? "#f97316" },
          });
        }
      });

      return {
        tooltip: {
          trigger: "axis",
          backgroundColor: "rgba(20, 20, 25, 0.95)",
          borderColor: "rgba(255,255,255,0.15)",
          textStyle: { color: "#e5e7eb", fontSize: 12 },
          formatter: (params: any) => {
            if (!params || !params.length) return "";
            const p = params[0];
            const idx = p.dataIndex;
            if (idx == null || idx >= validData.length) return "";
            const phase = phases[idx];
            const item = validData[idx];
            let extra = "";
            if (item?.change_from_yesterday != null) {
              extra = `<br/>较昨日: ${(item.change_from_yesterday > 0 ? "+" : "")}${item.change_from_yesterday.toFixed(1)}`;
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
          axisLine: { lineStyle: { color: "rgba(255,255,255,0.3)" } },
          axisLabel: { color: "rgba(255,255,255,0.6)", fontSize: 10, rotate: 45 },
          axisTick: { show: false },
        },
        yAxis: {
          type: "value",
          min: 0,
          max: 100,
          name: "STI 分数",
          nameTextStyle: { fontSize: 10, color: "rgba(255,255,255,0.5)" },
          axisLine: { lineStyle: { color: "rgba(255,255,255,0.3)" } },
          splitLine: { lineStyle: { color: "rgba(255,255,255,0.08)" } },
          axisLabel: { color: "rgba(255,255,255,0.6)", fontSize: 10 },
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
            lineStyle: {
              width: 2.5,
              color: ((params: any) => {
                const idx = params.dataIndex;
                return PHASE_LINE_COLOR[validData[idx]?.phase || ""] ?? "#f97316";
              }) as any,
            },
            itemStyle: {
              color: ((params: any) => {
                const idx = params.dataIndex;
                return PHASE_LINE_COLOR[validData[idx]?.phase || ""] ?? "#f97316";
              }) as any,
            },
            emphasis: {
              focus: "series",
              itemStyle: { borderWidth: 3, shadowBlur: 10, shadowColor: "rgba(249, 115, 22, 0.4)" },
            },
            areaStyle: {
              color: new echarts.graphic.LinearGradient(0, 0, 0, 1, [
                { offset: 0, color: "rgba(249, 115, 22, 0.3)" },
                { offset: 1, color: "rgba(249, 115, 22, 0.02)" },
              ]),
            },
          },
        ],
        // 阶段色带（底部标记）
        graphic: validData.map((d, i) => ({
          type: "text",
          silent: true,
          style: {
            text: d.phase || "",
            fill: PHASE_LINE_COLOR[d.phase || ""] || "#6b7280",
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
    },
    [data],
    {
      skip: validData.length === 0,
      notMerge: true,
      onReady: (instance) => {
        // 确保渲染到正确尺寸 — 双 rAF 等 DOM 布局完成后再 resize
        requestAnimationFrame(() => requestAnimationFrame(() => instance.resize()));
      },
    },
  );

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

  if (validData.length === 0) {
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
          <p className="mt-1 text-[11px] text-muted-foreground/50">最近 60 个交易日的情绪温度走势</p>
        </div>
      </GlassCard>
    );
  }

  const latest = validData[validData.length - 1];
  const phaseColor = PHASE_LINE_COLOR[latest.phase || ""] || "text-muted-foreground";

  return (
    <GlassCard className={cn("mb-6", className)}>
      <div className="mb-3 flex items-center justify-between">
        <div className="flex items-center gap-2">
          <h3 className="text-sm font-semibold text-muted-foreground">情绪温度时间线（60 日）</h3>
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
            {Math.max(...validData.map((d) => d.score ?? 0)).toFixed(1)}
          </p>
        </div>
        <div className="rounded-lg bg-muted/20 p-2 text-center">
          <p className="text-[10px] text-muted-foreground">最低分</p>
          <p className="font-mono text-lg font-bold text-success">
            {Math.min(...validData.map((d) => d.score ?? 100)).toFixed(1)}
          </p>
        </div>
        <div className="rounded-lg bg-muted/20 p-2 text-center">
          <p className="text-[10px] text-muted-foreground">数据天数</p>
          <p className="font-mono text-lg font-bold text-foreground">{validData.length}</p>
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
