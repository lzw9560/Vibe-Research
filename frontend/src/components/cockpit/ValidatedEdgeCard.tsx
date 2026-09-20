// S218 C4: ValidatedEdgeCard——诚实呈现唯一 validated edge 的衰减状态。
// 复用 JournalWinRateCurve 的 useECharts + GlassCard + Disclaimer pattern，
// 数据源改读 useSignalsDaily（cap.effective + verified_numbers.chrono_*），
// 与 TodaySignalsPanel 同源——不再硬编码 effectiveCap() + DECAY_* 常量。
import { useRef, useMemo } from "react";
import { Loader2, AlertTriangle, TrendingDown } from "lucide-react";
import { useECharts } from "@/hooks/useECharts";
import { GlassCard } from "@/components/ui/GlassCard";
import { Disclaimer } from "@/components/ui/Disclaimer";
import { useSignalsDaily } from "@/lib/query/signals";
import type { EChartsOption } from "echarts";

/** 返回人话状态标签（基于 regime + staleness，与后端 cap 一致） */
function statusLabel(
  regime: string | null,
  stale: boolean,
): { text: string; tone: "amber" | "red" | "emerald" } {
  if (stale) return { text: "provisional", tone: "red" };
  if (!regime || regime === "bear" || regime === "range")
    return { text: "within-regime only", tone: "amber" };
  return { text: "衰减中", tone: "amber" };
}

/** cap 格式化：整数（如 1.0）补 .0，避免 ×1；非整数原样（0.75/0.5）。 */
function formatCap(cap: number): string {
  return Number.isInteger(cap) ? cap.toFixed(1) : String(cap);
}

export function ValidatedEdgeCard() {
  const chartRef = useRef<HTMLDivElement>(null);
  const { data, isLoading, isError } = useSignalsDaily();

  const regime = data?.regime?.current ?? null;
  const freshness = data?.regime?.freshness;
  const stale = freshness?.stale ?? false;
  const daysSince = freshness?.days_since ?? 0;
  // cap 单源：读后端 cap.effective（同 TodaySignalsPanel），不再 effectiveCap() 硬编码。
  const cap = data?.cap?.effective ?? 1.0;
  const verified = data?.verified_numbers;
  const label = statusLabel(regime, stale);

  // 衰减轨迹数值（后端 verified_numbers.chrono_*，禁臆造常量）
  const train = verified?.chrono_train;
  const testVal = verified?.chrono_test;
  const decayPct = verified?.chrono_decay_pct;
  const pVal = verified?.chrono_p;
  const wr = verified?.chrono_wr;

  const capDisplay = formatCap(cap);
  const capText = `×${capDisplay}`;
  const capLabel = regime ?? "unknown";

  // 衰减轨迹图表 option（train vs test 二柱）
  const chartOption = useMemo<EChartsOption>(() => {
    return {
      tooltip: {
        trigger: "axis",
        formatter: () =>
          `train ${train ?? "N/A"}% → test ${testVal ?? "N/A"}%<br/>` +
          `衰减 ${decayPct ?? "N/A"}% · p=${pVal ?? "N/A"} · WR ${wr ?? "N/A"}%`,
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
            { value: train ?? 0, itemStyle: { color: "#fb923c" } },
            { value: testVal ?? 0, itemStyle: { color: "#f59e0b" } },
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
  }, [train, testVal, decayPct, pVal, wr]);

  useECharts(chartRef, () => chartOption, [chartOption], {
    skip: isLoading || isError || !data,
  });

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
            ×{capDisplay}=研究诚实性标注，非资金保护。真钱仓位/止损由你自己定。
          </p>

          {/* 衰减轨迹图表 */}
          <div ref={chartRef} className="h-[200px] w-full mb-3" />

          {/* 衰减数据行（后端 verified_numbers.chrono_*） */}
          <div className="grid grid-cols-4 gap-2 mb-3">
            <div className="rounded bg-muted/30 px-2 py-1.5 text-center">
              <p className="text-[10px] text-muted-foreground">train</p>
              <p className="text-sm font-bold text-amber-600">{train ?? "—"}%</p>
            </div>
            <div className="rounded bg-muted/30 px-2 py-1.5 text-center">
              <p className="text-[10px] text-muted-foreground">test</p>
              <p className="text-sm font-bold text-amber-600">{testVal ?? "—"}%</p>
            </div>
            <div className="rounded bg-muted/30 px-2 py-1.5 text-center">
              <p className="text-[10px] text-muted-foreground">衰减</p>
              <p className="text-sm font-bold text-red-500">-{decayPct ?? "—"}%</p>
            </div>
            <div className="rounded bg-muted/30 px-2 py-1.5 text-center">
              <p className="text-[10px] text-muted-foreground">WR</p>
              <p className="text-sm font-bold">{wr ?? "—"}%</p>
            </div>
          </div>

          {/* Regime 新鲜度 */}
          <div
            className={`mb-3 rounded border px-3 py-2 text-xs ${stale ? "border-red-200 bg-red-50 text-red-700" : "border-emerald-200 bg-emerald-50 text-emerald-700"}`}
          >
            {stale ? (
              <span>
                <strong>实际 ×{capDisplay}（cache 滞后 {daysSince} 天）</strong>：
                regime cache 到 {freshness?.last_cache_date ?? "未知"}，当前按保守计算。
              </span>
            ) : (
              <span>
                regime cache 新鲜（{freshness?.last_cache_date ?? "未知"}），当前 ×{capDisplay}。
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
