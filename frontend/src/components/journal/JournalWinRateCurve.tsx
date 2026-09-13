// S183 模拟盘累积胜率曲线——实时聚合 + Wilson 95% CI 带 + 50% 随机基准 + 双轴诚实标签。
// §44 外推禁令 UI 落地：CI 收窄=更确信真实 edge，真实 edge 可能<50%（负方向），
// 50% markLine + tooltip 方向提示让用户看到"收敛到负 edge"而非误读"在变好"。
import { useRef } from "react";
import { Loader2 } from "lucide-react";
import { useECharts } from "@/hooks/useECharts";
import { useJournalWinRateTrends } from "@/lib/query/journal";
import { Disclaimer } from "@/components/ui/Disclaimer";
import type { JournalWinRateTrendPoint } from "@/lib/journal-contract";

export function JournalWinRateCurve() {
  const chartRef = useRef<HTMLDivElement>(null);
  const { data, isLoading, isError } = useJournalWinRateTrends();
  const trends: JournalWinRateTrendPoint[] = data?.trends ?? [];

  useECharts(
    chartRef,
    () => {
      if (!trends.length) return {};
      const winRate = trends.map((t) => +(t.win_rate * 100).toFixed(2));
      const ciLow = trends.map((t) => +(t.ci_low * 100).toFixed(2));
      // stack 技巧：ci_low 透明垫底 + (ci_high - ci_low) 差值半透明带 + win_rate 独立线
      const ciBand = trends.map((t, i) => +(t.ci_high * 100 - ciLow[i]).toFixed(2));
      return {
        tooltip: {
          trigger: "axis",
          formatter: (params) => {
            const p = Array.isArray(params) ? params[0] : params;
            const t = trends[p?.dataIndex ?? -1];
            if (!t) return "";
            const wr = (t.win_rate * 100).toFixed(1);
            const dir = t.win_rate < 0.5 ? "（低于 50% 基准·负 edge 方向）" : "（≥50%·正方向）";
            return `${t.week_start}<br/>胜率 ${wr}% ${dir}<br/>CI [${(t.ci_low * 100).toFixed(1)}, ${(t.ci_high * 100).toFixed(1)}]%<br/>n=${t.n_decided} · ${t.label}`;
          },
        },
        grid: { left: 40, right: 16, top: 30, bottom: 32 },
        xAxis: { type: "category", data: trends.map((t) => t.week_start) },
        yAxis: { type: "value", name: "胜率(%)", min: 0, max: 100 },
        series: [
          {
            name: "CI 下", type: "line", data: ciLow, stack: "ci",
            areaStyle: { color: "transparent" }, lineStyle: { opacity: 0 }, symbol: "none",
          },
          {
            name: "CI 带", type: "line", data: ciBand, stack: "ci",
            areaStyle: { color: "rgba(251,146,60,0.18)" }, lineStyle: { opacity: 0 }, symbol: "none",
          },
          {
            name: "胜率", type: "line", data: winRate, smooth: true,
            itemStyle: { color: "#fb923c" }, lineStyle: { color: "#fb923c", width: 2 },
            markLine: {
              symbol: "none",
              data: [{
                yAxis: 50,
                label: { formatter: "随机基准 50%" },
                lineStyle: { type: "dashed", color: "#94a3b8", width: 1 },
              }],
            },
          },
        ],
      };
    },
    [data],
    { skip: !trends.length },
  );

  if (isLoading) {
    return (
      <div className="h-[200px] flex items-center justify-center text-muted-foreground text-sm">
        <Loader2 className="animate-spin mr-2 h-4 w-4" />加载胜率曲线...
      </div>
    );
  }
  if (isError) {
    return (
      <div className="h-[100px] flex items-center justify-center text-red-500 text-sm">
        胜率曲线加载失败
      </div>
    );
  }
  if (!trends.length) {
    // R6 空态：当前 42 行全 NULL PnL，需 scheduler 点火攒真实成交
    return (
      <div className="rounded-lg border border-amber-300/60 bg-amber-50/80 p-4 text-sm text-amber-800">
        <Disclaimer compact />
        <p className="mt-2 font-medium">模拟盘积累中</p>
        <p className="text-xs text-amber-700 mt-1">
          需 ≥30 条真实成交（net_pnl 非 NULL）才有统计意义，当前 0 条已结算。scheduler trade_journal_daily 连续跑通后自动积累，曲线将自动显示。
        </p>
      </div>
    );
  }
  const last = trends[trends.length - 1];
  return (
    <div>
      <div className="flex items-center justify-between mb-2">
        <h3 className="text-sm font-medium">模拟盘累积胜率（收敛到真实 edge，可能为负）</h3>
        <span className="text-xs text-muted-foreground">
          Wilson 95% CI · 最新 {last.label} · n={last.n_decided}
        </span>
      </div>
      <Disclaimer compact />
      <div ref={chartRef} className="h-[300px] w-full" />
    </div>
  );
}
