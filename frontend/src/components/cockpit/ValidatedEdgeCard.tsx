// S218 C4: ValidatedEdgeCard——诚实呈现唯一 validated edge 的衰减状态。
// 复用 JournalWinRateCurve 的 useECharts + GlassCard + Disclaimer pattern，
// 数据源新写（衰减轨迹二点 bar + provisional labels + paper P&L tag）。
import { useRef, useMemo } from "react";
import { Loader2, AlertTriangle, TrendingDown } from "lucide-react";
import { useECharts } from "@/hooks/useECharts";
import { GlassCard } from "@/components/ui/GlassCard";
import { Disclaimer } from "@/components/ui/Disclaimer";
import { useSignalsStatus } from "@/lib/query/signals";
import type { EChartsOption } from "echarts";

// 静态衰减轨迹数据（§44 chrono forward-OOS，train→test）
const DECAY_TRAIN = 1.57;
const DECAY_TEST = 1.04;
const DECAY_PCT = 34;
const DECAY_P = 0.0054;
const DECAY_WR = 52.7;

/** 根据 regime 返回有效 cap 显示值 */
function effectiveCap(regime: string | null, stale: boolean): number {
  if (stale || !regime) return 0.5;
  return regime === "bull" ? 0.75 : 0.5;
}

/** 返回人话状态标签 */
function statusLabel(regime: string | null, stale: boolean): { text: string; tone: "amber" | "red" | "emerald" } {
  if (stale) return { text: "provisional", tone: "red" };
  if (!regime || regime === "bear" || regime === "range") return { text: "within-regime only", tone: "amber" };
  return { text: "衰减中", tone: "amber" };
}

export function ValidatedEdgeCard() {
  const chartRef = useRef<HTMLDivElement>(null);
  const { data, isLoading, isError } = useSignalsStatus();

  const regime = data?.regime?.current ?? null;
  const freshness = data?.regime?.freshness;
  const stale = freshness?.stale ?? false;
  const daysSince = freshness?.days_since ?? 0;
  const cap = effectiveCap(regime, stale);
  const label = statusLabel(regime, stale);

  // 衰减轨迹图表 option（train vs test 二柱）
  const chartOption = useMemo<EChartsOption>(() => {
    return {
      tooltip: {
        trigger: "axis",
        formatter: () =>
          `train ${DECAY_TRAIN}% → test ${DECAY_TEST}%<br/>` +
          `衰减 ${DECAY_PCT}% · p=${DECAY_P} · WR ${DECAY_WR}%`,
      },
      grid: { left: 40, right: 16, top: 10, bottom: 24 },
      xAxis: {
        type: "category",
        data: ["train (bull)", "test (bull)"],
        axisLabel: { fontSize: 11, color: "#64748b" },
      },
      yAxis: {
        type: "value",
        name: "均值收益(%)",
        nameTextStyle: { fontSize: 10, color: "#94a3b8" },
        axisLabel: { fontSize: 10, color: "#64748b" },
        splitLine: { lineStyle: { color: "#e2e8f0", type: "dashed" } },
      },
      series: [
        {
          name: "均值收益",
          type: "bar",
          data: [
            { value: DECAY_TRAIN, itemStyle: { color: "#fb923c" } },
            { value: DECAY_TEST, itemStyle: { color: "#f59e0b" } },
          ],
          barWidth: "40%",
          label: {
            show: true,
            position: "top",
            formatter: (p: any) => `${p.value}%`,
            fontSize: 12,
            fontWeight: "bold",
            color: "#475569",
          },
        },
      ],
    };
  }, []);

  useECharts(
    chartRef,
    () => chartOption,
    [chartOption],
    { skip: isLoading || isError || !data },
  );

  const capText = `×${cap}`;
  const capLabel = cap === 0.75 ? "bull" : cap === 0.5 ? "bear/range/stale" : "";

  return (
    <GlassCard className="p-4">
      {/* Header */}
      <div className="mb-3 flex items-center justify-between">
        <h3 className="text-sm font-semibold">唯一 validated edge（统计验证非已实现收益）</h3>
        <span className="text-xs text-muted-foreground">consecutive_relay</span>
      </div>

      {/* Loading */}
      {isLoading && (
        <div className="h-[180px] flex items-center justify-center text-muted-foreground text-sm">
          <Loader2 className="animate-spin mr-2 h-4 w-4" />加载信号状态...
        </div>
      )}

      {/* Error */}
      {isError && (
        <div className="h-[120px] flex items-center justify-center text-red-500 text-sm">
          信号状态加载失败
        </div>
      )}

      {/* Content */}
      {!isLoading && !isError && (
        <>
          {/* 状态标签行 */}
          <div className="mb-3 flex flex-wrap items-center gap-2">
            <span
              className={`inline-flex items-center gap-1 rounded px-2 py-0.5 text-xs font-medium ${
                label.tone === "red"
                  ? "bg-red-50 text-red-700"
                  : label.tone === "amber"
                    ? "bg-amber-50 text-amber-700"
                    : "bg-emerald-50 text-emerald-700"
              }`}
            >
              {label.tone === "red" && <AlertTriangle className="h-3 w-3" />}
              {label.tone === "amber" && <TrendingDown className="h-3 w-3" />}
              {label.text}
            </span>
            <span className="text-xs text-muted-foreground">（edge 衰减中，照做有风险）</span>
          </div>

          {/* Cap 显示 */}
          <div className="mb-3 flex items-baseline gap-2">
            <span className="text-2xl font-bold font-mono text-amber-600">{capText}</span>
            <span className="text-xs text-muted-foreground">{capLabel}</span>
          </div>
          <p className="mb-3 text-xs text-muted-foreground leading-relaxed">
            ×{cap}=研究诚实性标注，非资金保护。真钱仓位/止损由你自己定。
          </p>

          {/* 衰减轨迹图表 */}
          <div ref={chartRef} className="h-[200px] w-full mb-3" />

          {/* 衰减数据行 */}
          <div className="grid grid-cols-4 gap-2 mb-3">
            <div className="rounded bg-muted/30 px-2 py-1.5 text-center">
              <p className="text-[10px] text-muted-foreground">train</p>
              <p className="text-sm font-bold text-amber-600">{DECAY_TRAIN}%</p>
            </div>
            <div className="rounded bg-muted/30 px-2 py-1.5 text-center">
              <p className="text-[10px] text-muted-foreground">test</p>
              <p className="text-sm font-bold text-amber-600">{DECAY_TEST}%</p>
            </div>
            <div className="rounded bg-muted/30 px-2 py-1.5 text-center">
              <p className="text-[10px] text-muted-foreground">衰减</p>
              <p className="text-sm font-bold text-red-500">-{DECAY_PCT}%</p>
            </div>
            <div className="rounded bg-muted/30 px-2 py-1.5 text-center">
              <p className="text-[10px] text-muted-foreground">WR</p>
              <p className="text-sm font-bold">{DECAY_WR}%</p>
            </div>
          </div>

          {/* Regime 新鲜度 */}
          <div className={`mb-3 rounded border px-3 py-2 text-xs ${stale ? "border-red-200 bg-red-50 text-red-700" : "border-emerald-200 bg-emerald-50 text-emerald-700"}`}>
            {stale ? (
              <span>
                <strong>实际 ×0.5（cache 滞后 {daysSince} 天）</strong>：
                regime cache 到 {freshness?.last_cache_date ?? "未知"}，当前按保守 ×0.5 计算。
              </span>
            ) : (
              <span>
                regime cache 新鲜（{freshness?.last_cache_date ?? "未知"}），当前 ×{cap}。
              </span>
            )}
          </div>

          {/* Paper P&L tag */}
          <div className="mb-2 rounded border border-amber-200 bg-amber-50 px-3 py-2 text-xs text-amber-800">
            <strong>模拟盘名义额，非真钱。</strong>
            接券商前所有战绩 paper。本系统不自动下单——产投研参考非自动交易。
          </div>

          <Disclaimer compact />
        </>
      )}
    </GlassCard>
  );
}
