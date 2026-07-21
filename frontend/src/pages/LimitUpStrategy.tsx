import { useState, useEffect, useRef, useCallback, Fragment } from "react";
import * as echarts from "echarts";
import { Flame, Loader2, RefreshCw, ChevronDown, ChevronUp, Info } from "lucide-react";
import { PageHeader } from "@/components/ui/PageHeader";
import { GlassCard } from "@/components/ui/GlassCard";
import { AskAiButton } from "@/components/ui/AskAiButton";
import { Disclaimer } from "@/components/ui/Disclaimer";
import { api, type GeneScore, type ScreenerResult, type LimitUpAnalysis, type AuctionScreenerResult, type SeatProfile } from "@/lib/api";
import { cn } from "@/lib/utils";

// ── 颜色约定 ──────────────────────────────────────────────
const scoreColor = (s: number) =>
  s >= 75 ? "text-primary"
  : s >= 60 ? "text-blue-400"
  : "text-gray-400";

const scoreBg = (s: number) =>
  s >= 75 ? "bg-primary/10"
  : s >= 60 ? "bg-blue-400/10"
  : "bg-gray-400/10";

const fmtPct = (v: number | null | undefined) =>
  v == null ? "—" : `${v.toFixed(1)}%`;

// 五维因子键名（与后端一致）
const FACTOR_KEYS: string[] = ["次日溢价率", "红盘率", "封板率", "炸板后溢价", "涨停频次"];

// 表格显示的因子列（不含涨停频次，因为频次用 zt_count_250d 展示）
const DISPLAY_FACTORS: string[] = ["次日溢价率", "红盘率", "封板率", "炸板后溢价"];

// ── 基因得分雷达图 ────────────────────────────────────────
function GeneScoreChart({ factors, wilsonAdjusted }: { factors: Record<string, number>; wilsonAdjusted: number }) {
  const chartRef = useRef<HTMLDivElement>(null);
  const instanceRef = useRef<echarts.ECharts | null>(null);

  useEffect(() => {
    if (!chartRef.current) return;
    instanceRef.current = echarts.init(chartRef.current);
    const indicator = FACTOR_KEYS.map((k) => ({
      name: String(k),
      max: 100,
    }));
    const values = FACTOR_KEYS.map((k) => Number(factors[k]) ?? 0);
    const option: echarts.EChartsOption = {
      tooltip: { trigger: "item" },
      radar: {
        indicator,
        radius: "65%",
        axisName: { color: "#9ca3af", fontSize: 11 },
        splitArea: { areaStyle: { color: ["rgba(251,146,60,0.02)", "rgba(251,146,60,0.05)"] } },
      },
      series: [
        {
          type: "radar",
          data: [
            {
              value: values,
              name: "基因因子",
              areaStyle: { color: "rgba(251, 146, 60, 0.25)" },
              lineStyle: { color: "#fb923c", width: 2 },
              itemStyle: { color: "#fb923c" },
            },
          ],
        },
      ],
    };
    instanceRef.current.setOption(option);
    return () => { instanceRef.current?.dispose(); instanceRef.current = null; };
  }, [factors, wilsonAdjusted]);

  return <div ref={chartRef} className="h-[220px]" />;
}

// ── 基因得分回测散点图 ──────────────────────────────────────
function BacktestScatterChart({ points }: {
  points: Array<{ date: string; gene_score: number; actual_next_day: number }>;
}) {
  const chartRef = useRef<HTMLDivElement>(null);
  const instanceRef = useRef<echarts.ECharts | null>(null);

  useEffect(() => {
    if (!chartRef.current || points.length === 0) return;
    instanceRef.current = echarts.init(chartRef.current);

    const lianban = points.filter(p => p.actual_next_day >= 1);
    const no_lianban = points.filter(p => p.actual_next_day < 1);

    const option: echarts.EChartsOption = {
      tooltip: {
        trigger: "item",
        formatter: (p: any) => {
          // p.data 是 scatter 系列传入的完整数组 [gene_score, actual_next_day, date]
          const d = p.data;
          if (!d || !Array.isArray(d)) return "无数据";
          const geneScore = d[0];
          const actualNextDay = d[1];
          const date = d[2] ?? "未知日期";
          return `${date}<br/>基因得分: ${geneScore}<br/>实际表现: ${actualNextDay >= 1 ? "连板 ✓" : "未连板 ✗"}`;
        },
      },
      grid: { left: 45, right: 15, top: 15, bottom: 35 },
      xAxis: {
        name: "基因得分",
        nameLocation: "middle",
        nameGap: 25,
        nameTextStyle: { fontSize: 10, color: "#9ca3af" },
        min: 0,
        max: 100,
        axisLine: { lineStyle: { color: "#4b5563" } },
        splitLine: { lineStyle: { color: "#1f2937" } },
      },
      yAxis: {
        name: "实际表现",
        nameLocation: "middle",
        nameGap: 30,
        nameTextStyle: { fontSize: 10, color: "#9ca3af" },
        min: -0.1,
        max: 1.1,
        axisLabel: {
          formatter: (v: number) => v >= 1 ? "连板" : "未连板",
          fontSize: 10,
          color: "#9ca3af",
        },
        axisLine: { lineStyle: { color: "#4b5563" } },
        splitLine: { show: false },
      },
      series: [
        {
          name: "连板",
          type: "scatter",
          data: lianban.map(p => [p.gene_score, 1, p.date]),
          symbolSize: 8,
          itemStyle: { color: "#f97316", opacity: 0.7 },
        },
        {
          name: "未连板",
          type: "scatter",
          data: no_lianban.map(p => [p.gene_score, 0, p.date]),
          symbolSize: 8,
          itemStyle: { color: "#6b7280", opacity: 0.5 },
        },
      ],
      legend: {
        data: ["连板", "未连板"],
        textStyle: { fontSize: 10, color: "#9ca3af" },
        top: 0,
        right: 0,
      },
    };
    instanceRef.current.setOption(option);
    return () => { instanceRef.current?.dispose(); instanceRef.current = null; };
  }, [points]);

  const total = points.length;
  const lianban_count = points.filter(p => p.actual_next_day >= 1).length;
  const avg_score_lianban = lianban_count > 0
    ? (points.filter(p => p.actual_next_day >= 1).reduce((s, p) => s + p.gene_score, 0) / lianban_count).toFixed(1)
    : "—";
  const avg_score_no = total - lianban_count > 0
    ? (points.filter(p => p.actual_next_day < 1).reduce((s, p) => s + p.gene_score, 0) / (total - lianban_count)).toFixed(1)
    : "—";

  return (
    <GlassCard className="p-3">
      <h4 className="mb-1.5 text-sm font-semibold text-muted-foreground">
        历史回测：基因得分 vs 实际表现
      </h4>
      {total < 3 ? (
        <p className="text-xs text-muted-foreground/60 py-4 text-center">历史数据不足（≥3 条）</p>
      ) : (
        <>
          <div ref={chartRef} className="h-[200px]" />
          <div className="mt-1.5 grid grid-cols-3 gap-2 text-center text-xs">
            <div className="rounded bg-muted/20 p-1.5">
              <div className="text-muted-foreground/60">样本数</div>
              <div className="font-bold text-foreground">{total}</div>
            </div>
            <div className="rounded bg-muted/20 p-1.5">
              <div className="text-muted-foreground/60">连板率</div>
              <div className="font-bold text-primary">{total > 0 ? ((lianban_count / total) * 100).toFixed(0) : 0}%</div>
            </div>
            <div className="rounded bg-muted/20 p-1.5">
              <div className="text-muted-foreground/60">连板均分</div>
              <div className="font-bold text-primary">{avg_score_lianban}</div>
            </div>
          </div>
          <div className="mt-1 text-[10px] text-muted-foreground/50 text-center">
            未连板均分: {avg_score_no}（{total - lianban_count} 只）
          </div>
        </>
      )}
    </GlassCard>
  );
}

// ── 个股策略逻辑分析（展开区） ─────────────────────────────
function GeneScoreDetail({ analysis, loading, error }: {
  analysis: LimitUpAnalysis | null;
  loading: boolean;
  error: string | null;
}) {
  if (loading) {
    return (
      <div className="flex items-center justify-center py-8">
        <Loader2 className="h-5 w-5 animate-spin text-primary" />
        <span className="ml-2 text-sm text-muted-foreground">加载个股策略分析…</span>
      </div>
    );
  }
  if (error || !analysis) {
    return (
      <div className="flex items-center justify-center py-8 text-sm text-muted-foreground">
        <Info className="mr-1.5 h-4 w-4" /> 加载失败：{error ?? "未知错误"}
      </div>
    );
  }

  const { gene_score, strategy_logic, risk_rules, backtest_points } = analysis;
  const btPoints = backtest_points?.filter((p: any) => p.gene_score != null) ?? [];

  return (
    <div className="space-y-3">
      {/* 雷达图 */}
      <GlassCard className="p-3">
        <h4 className="mb-1.5 text-sm font-semibold text-muted-foreground">
          基因五维因子雷达图 · {analysis.name}（{analysis.code}）
        </h4>
        <GeneScoreChart factors={gene_score.factors} wilsonAdjusted={gene_score.wilson_adjusted} />
        <div className="mt-1.5 flex items-center justify-between text-xs text-muted-foreground">
          <span>总分: <b className={scoreColor(gene_score.total_score)}>{gene_score.total_score}</b></span>
          <span>Wilson 校正: <b className="text-primary">{gene_score.wilson_adjusted}</b></span>
          <span>60日涨停: <b>{gene_score.zt_count_250d}</b> 次</span>
        </div>
      </GlassCard>

      {/* 历史回测散点图 */}
      <BacktestScatterChart points={btPoints} />

      {/* 条件匹配（教育性展示） */}
      <GlassCard className="p-3">
        <h4 className="mb-1.5 text-sm font-semibold text-muted-foreground">策略逻辑条件匹配（教育性展示）</h4>
        {strategy_logic.matches.length === 0 ? (
          <p className="text-xs text-muted-foreground/60">该股未匹配到任何预设策略条件</p>
        ) : (
          <div className="space-y-1">
            {strategy_logic.matches.map((m, i) => (
              <div key={i} className="rounded-lg bg-muted/25 p-2 text-xs">
                <div className="flex items-center gap-2">
                  <span className="font-medium text-foreground">{m.condition}</span>
                  <span className="rounded bg-primary/10 px-1.5 py-0.5 text-[10px] text-primary">{m.value}</span>
                </div>
                <p className="mt-0.5 text-muted-foreground/70">{m.description}</p>
              </div>
            ))}
          </div>
        )}
      </GlassCard>

      {/* 风控规则知识展示 */}
      <GlassCard className="p-3">
        <h4 className="mb-1.5 text-sm font-semibold text-muted-foreground">风控规则知识（教育性展示）</h4>
        <div className="space-y-1">
          {risk_rules.map((r, i) => (
            <div key={i} className="rounded-lg bg-muted/25 p-2 text-xs">
              <div className="flex items-center gap-2">
                <span className="font-medium text-foreground">{r.rule_name}</span>
                {r.configurable && <span className="rounded bg-blue-500/10 px-1.5 py-0.5 text-[10px] text-blue-400">可配置</span>}
                <span className="text-muted-foreground">默认: {r.default_value}</span>
              </div>
              <p className="mt-0.5 text-muted-foreground/70">{r.description}</p>
              <p className="mt-0.5 text-muted-foreground/50 italic">示例: {r.example}</p>
            </div>
          ))}
        </div>
      </GlassCard>
    </div>
  );
}

// ── 基因得分表格行展开 ────────────────────────────────────
interface ExpandableTableProps {
  data: GeneScore[];
  expandedCode: string | null;
  expandedData: LimitUpAnalysis | null;
  expandedLoading: boolean;
  expandedError: string | null;
  onToggle: (code: string) => void;
}

function ExpandableTable({ data, expandedCode, expandedData, expandedLoading, expandedError, onToggle }: ExpandableTableProps) {
  if (data.length === 0) {
    return <p className="py-6 text-center text-sm text-muted-foreground/60">暂无涨停股数据（可能是非交易时段或数据源暂不可用）</p>;
  }

  return (
    <div className="overflow-x-auto rounded-lg border border-border/30">
      <table className="w-full text-sm">
        <thead>
          <tr className="border-b border-border/50 bg-muted/20 text-left text-xs text-muted-foreground">
            <th className="w-8 px-2 py-2.5"></th>
            <th className="whitespace-nowrap px-3 py-2.5 font-medium">代码</th>
            <th className="whitespace-nowrap px-3 py-2.5 font-medium">名称</th>
            <th className="w-20 whitespace-nowrap px-3 py-2.5 text-center font-medium">基因分</th>
            <th className="w-20 whitespace-nowrap px-3 py-2.5 text-center font-medium">溢价率</th>
            <th className="w-20 whitespace-nowrap px-3 py-2.5 text-center font-medium">红盘率</th>
            <th className="w-20 whitespace-nowrap px-3 py-2.5 text-center font-medium">封板率</th>
            <th className="w-20 whitespace-nowrap px-3 py-2.5 text-center font-medium">炸板后溢价</th>
            <th className="w-16 whitespace-nowrap px-3 py-2.5 text-center font-medium">涨停次</th>
            <th className="w-20 whitespace-nowrap px-3 py-2.5 text-center font-medium">回测连板率</th>
          </tr>
        </thead>
        <tbody className="divide-y divide-border/20">
          {data.map((row) => {
            const expanded = expandedCode === row.code;
            return (
              <Fragment key={row.code}>
                <RowElement
                  row={row}
                  expanded={expanded}
                  onToggle={onToggle}
                  displayFactors={DISPLAY_FACTORS}
                  scoreColor={scoreColor}
                  fmtPct={fmtPct}
                />
                {/* 在当前行下方展开个股详情 */}
                {expanded && (
                  <tr className="bg-muted/10">
                    <td colSpan={10} className="p-0">
                      <div className="border-t border-border/30 px-4 py-3">
                        <GeneScoreDetail
                          analysis={expandedData}
                          loading={expandedLoading}
                          error={expandedError}
                        />
                      </div>
                    </td>
                  </tr>
                )}
              </Fragment>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}

// 提取为独立组件避免 TS 闭包问题
function RowElement({ row, expanded, onToggle, displayFactors, scoreColor, fmtPct }: {
  row: GeneScore;
  expanded: boolean;
  onToggle: (code: string) => void;
  displayFactors: string[];
  scoreColor: (s: number) => string;
  fmtPct: (v: number | null | undefined) => string;
}) {
  return (
    <tr
      onClick={() => onToggle(row.code)}
      className="cursor-pointer transition-colors hover:bg-muted/20"
    >
      <td className="px-2 py-2.5 text-center">
        {expanded ? <ChevronUp className="mx-auto h-3.5 w-3.5 text-muted-foreground" /> : <ChevronDown className="mx-auto h-3.5 w-3.5 text-muted-foreground" />}
      </td>
      <td className="whitespace-nowrap px-3 py-2.5 font-mono text-xs text-muted-foreground/60">{row.code}</td>
      <td className="px-3 py-2.5 font-medium">{row.name}</td>
      <td className="px-3 py-2.5 text-center">
        <span className={`inline-block rounded-md px-2 py-0.5 font-mono text-base font-bold ${scoreBg(row.total_score)} ${scoreColor(row.total_score)}`}>
          {row.total_score}
        </span>
      </td>
      {displayFactors.map((k) => (
        <td key={k} className="whitespace-nowrap px-3 py-2.5 text-center font-mono text-xs">
          {fmtPct(row.factors[k] as number)}
        </td>
      ))}
      <td className="whitespace-nowrap px-3 py-2.5 text-center font-mono text-xs">
        {row.zt_count_250d}
      </td>
      <td className="whitespace-nowrap px-3 py-2.5 text-center font-mono text-xs">
        {row.backtest_summary?.samples ? `${row.backtest_summary.samples}只 ${row.backtest_summary.lianban_rate}%` : "—"}
      </td>
    </tr>
  );
}

// ── 竞价选股 TOP N 组件 ────────────────────────────────────────
function AuctionScreenerSection() {
  const [result, setResult] = useState<AuctionScreenerResult | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [selectedDate, setSelectedDate] = useState(new Date().toISOString().slice(0, 10));

  const loadAuction = useCallback((date: string) => {
    setLoading(true);
    setError(null);
    api.auctionTop(date)
      .then(setResult)
      .catch((e) => setError(e instanceof Error ? e.message : "加载失败"))
      .finally(() => setLoading(false));
  }, []);

  useEffect(() => {
    loadAuction(selectedDate);
  }, [loadAuction, selectedDate]);

  const stiColor = (phase: string | null) => {
    if (!phase) return "text-muted-foreground";
    if (phase === "高潮" || phase === "启动") return "text-danger";
    if (phase === "冰点" || phase === "退潮") return "text-success";
    return "text-muted-foreground";
  };

  if (loading) {
    return (
      <GlassCard className="mb-6">
        <div className="flex items-center justify-center py-8">
          <Loader2 className="h-5 w-5 animate-spin text-primary" />
          <span className="ml-2 text-sm text-muted-foreground">加载竞价选股数据…</span>
        </div>
      </GlassCard>
    );
  }

  return (
    <GlassCard className="mb-6">
      <div className="mb-3 flex items-center gap-2">
        <h3 className="text-sm font-semibold text-muted-foreground">竞价预案 TOP N</h3>
        <input
          type="date"
          value={selectedDate}
          onChange={(e) => setSelectedDate(e.target.value)}
          className="rounded-lg border border-border bg-black/20 px-2 py-1 text-xs outline-none focus:border-primary/50"
        />
        {result?.disclaimer && (
          <span className="ml-auto text-[11px] text-muted-foreground/50">{result.disclaimer}</span>
        )}
        <button
          onClick={() => loadAuction(selectedDate)}
          className="text-muted-foreground hover:text-primary"
          title="刷新"
        >
          <RefreshCw className="h-3.5 w-3.5" />
        </button>
      </div>

      {/* STI 摘要栏 */}
      {result && result.sti_score != null && (
        <div className="mb-3 grid grid-cols-2 gap-2 rounded-lg bg-muted/20 p-2.5 sm:grid-cols-4">
          <div>
            <p className="text-[11px] text-muted-foreground">STI 得分</p>
            <p className="font-mono text-lg font-bold text-primary">{result.sti_score}</p>
          </div>
          <div>
            <p className="text-[11px] text-muted-foreground">STI 阶段</p>
            <p className={cn("font-mono text-lg font-bold", stiColor(result.sti_phase))}>{result.sti_phase ?? "—"}</p>
          </div>
          <div>
            <p className="text-[11px] text-muted-foreground">分析总数</p>
            <p className="font-mono text-lg font-bold text-foreground">{result.total_analyzed}</p>
          </div>
          <div>
            <p className="text-[11px] text-muted-foreground">候选数</p>
            <p className="font-mono text-lg font-bold text-primary">{result.candidates?.length ?? 0}</p>
          </div>
        </div>
      )}

      {error ? (
        <div className="flex items-center justify-center py-8 text-sm text-destructive">
          <Info className="mr-1.5 h-4 w-4" /> {error}
        </div>
      ) : (
        <div className="overflow-x-auto">
          <table className="w-full text-sm">
            <thead>
              <tr className="border-b border-border/50 bg-muted/20 text-left text-xs text-muted-foreground">
                <th className="w-8 px-2 py-2.5">#</th>
                <th className="whitespace-nowrap px-3 py-2.5 font-medium">代码</th>
                <th className="whitespace-nowrap px-3 py-2.5 font-medium">名称</th>
                <th className="w-16 whitespace-nowrap px-3 py-2.5 text-center font-medium">竞价得分</th>
                <th className="w-16 whitespace-nowrap px-3 py-2.5 text-center font-medium">基因得分</th>
                <th className="w-14 whitespace-nowrap px-3 py-2.5 text-center font-medium">连板数</th>
                <th className="w-16 whitespace-nowrap px-3 py-2.5 text-center font-medium">封板率</th>
                <th className="whitespace-nowrap px-3 py-2.5 font-medium">战法标签</th>
                <th className="w-16 whitespace-nowrap px-3 py-2.5 text-center font-medium">信号强度</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-border/20">
              {result?.candidates?.length === 0 ? (
                <tr>
                  <td colSpan={9} className="py-6 text-center text-sm text-muted-foreground/60">
                    今日无符合条件的竞价选股标的
                  </td>
                </tr>
              ) : (
                result?.candidates?.map((c, i) => (
                  <tr key={c.code} className="transition-colors hover:bg-muted/20">
                    <td className="whitespace-nowrap px-2 py-2.5 font-mono text-xs text-muted-foreground/50">{i + 1}</td>
                    <td className="whitespace-nowrap px-3 py-2.5 font-mono text-xs text-muted-foreground/60">{c.code}</td>
                    <td className="px-3 py-2.5 font-medium">{c.name}</td>
                    <td className="px-3 py-2.5 text-center">
                      <span className={`inline-block rounded-md px-2 py-0.5 font-mono text-sm font-bold ${
                        c.score >= 75 ? "bg-primary/10 text-primary"
                        : c.score >= 60 ? "bg-blue-400/10 text-blue-400"
                        : "bg-gray-400/10 text-gray-400"
                      }`}>
                        {c.score}
                      </span>
                    </td>
                    <td className="whitespace-nowrap px-3 py-2.5 text-center font-mono text-xs">
                      {c.gene_score}
                    </td>
                    <td className="whitespace-nowrap px-3 py-2.5 text-center font-mono text-xs">
                      {c.zt_count_30d}
                    </td>
                    <td className="whitespace-nowrap px-3 py-2.5 text-center font-mono text-xs">
                      {c.seal_rate != null ? `${(c.seal_rate * 100).toFixed(1)}%` : "—"}
                    </td>
                    <td className="px-3 py-2.5">
                      <div className="flex flex-wrap gap-1">
                        {c.strategy_tags?.length > 0
                          ? c.strategy_tags.map((tag, j) => (
                              <span key={j} className="rounded bg-primary/10 px-1.5 py-0.5 text-[10px] text-primary">{tag}</span>
                            ))
                          : "—"}
                      </div>
                    </td>
                    <td className="whitespace-nowrap px-3 py-2.5 text-center font-mono text-xs">
                      {c.signal_strength != null ? `${(c.signal_strength * 100).toFixed(1)}%` : "—"}
                    </td>
                  </tr>
                ))
              )}
            </tbody>
          </table>
        </div>
      )}

      {result?.updated && (
        <p className="mt-2 text-[11px] text-muted-foreground/50">更新时间: {result.updated}</p>
      )}
    </GlassCard>
  );
}

// ── 席位引擎 ────────────────────────────────────────────────
function SeatEngineSection() {
  const [profiles, setProfiles] = useState<Record<string, SeatProfile>>({});
  const [loading, setLoading] = useState(true);
  const [building, setBuilding] = useState(false);
  const [buildDone, setBuildDone] = useState(false);

  const loadProfiles = useCallback(() => {
    setLoading(true);
    api.seatProfiles()
      .then((raw) => {
        // Handle both old format (Record<string, SeatProfile>) and new format ({profiles: [...], total: N})
        if (Array.isArray(raw)) {
          // New format: {profiles: [...]}
          const arr = (raw as any).profiles || raw;
          const dict: Record<string, SeatProfile> = {};
          for (const p of arr) {
            if (p.name) dict[p.name] = p;
          }
          setProfiles(dict);
        } else {
          // Old format: Record<string, SeatProfile>
          setProfiles(raw as Record<string, SeatProfile>);
        }
      })
      .catch(() => {})
      .finally(() => setLoading(false));
  }, []);

  useEffect(() => {
    loadProfiles();
  }, [loadProfiles]);

  const handleBuild = useCallback(async () => {
    setBuilding(true);
    try {
      await api.seatBuildProfiles(180);
      setBuildDone(true);
      loadProfiles();
    } catch {
      // ignore
    } finally {
      setBuilding(false);
    }
  }, [loadProfiles]);

  // 按类型分组
  const grouped: Record<string, SeatProfile[]> = {};
  for (const [, p] of Object.entries(profiles)) {
    if (!grouped[p.seat_type]) grouped[p.seat_type] = [];
    grouped[p.seat_type].push(p);
  }
  // 按数量降序
  const groups = Object.entries(grouped).sort((a, b) => b[1].length - a[1].length);

  const typeColors: Record<string, string> = {
    "活跃游资": "text-primary",
    "量化席位": "text-blue-400",
    "跟风席位": "text-muted-foreground",
    "机构专用": "text-purple-400",
    "inactive": "text-muted-foreground/40",
  };

  return (
    <GlassCard className="mb-6">
      <div className="mb-3 flex items-center justify-between">
        <div className="flex items-center gap-2">
          <h3 className="text-sm font-semibold text-muted-foreground">席位引擎</h3>
          <span className="text-[11px] text-muted-foreground/50">龙虎榜席位统计特征</span>
        </div>
        <div className="flex items-center gap-2">
          <button
            onClick={handleBuild}
            disabled={building}
            className="inline-flex items-center gap-1.5 rounded-lg bg-primary/15 px-3 py-1.5 text-xs font-medium text-primary shadow-glow transition-colors hover:bg-primary/25 disabled:opacity-50"
            title="构建席位画像（需数分钟）"
          >
            {building ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <RefreshCw className="h-3.5 w-3.5" />}
            {building ? "构建中…" : "构建画像"}
          </button>
          <button
            onClick={loadProfiles}
            className="text-muted-foreground hover:text-primary"
            title="刷新"
          >
            <RefreshCw className="h-3.5 w-3.5" />
          </button>
        </div>
      </div>

      {loading && !buildDone ? (
        <p className="py-4 text-center text-sm text-muted-foreground/60">加载中…</p>
      ) : groups.length === 0 ? (
        <div className="py-4 text-center">
          <p className="text-sm text-muted-foreground">暂无席位数据</p>
          <p className="mt-1 text-xs text-muted-foreground/50">点击「构建画像」拉取历史龙虎榜数据</p>
        </div>
      ) : (
        <div className="space-y-4">
          {groups.map(([type, seats]) => (
            <div key={type}>
              <div className="mb-1.5 flex items-center gap-2">
                <span className={cn("text-xs font-medium", typeColors[type] || "text-muted-foreground")}>
                  {type}
                </span>
                <span className="text-[11px] text-muted-foreground/50">({seats.length})</span>
              </div>
              <div className="grid gap-2 sm:grid-cols-2 lg:grid-cols-3">
                {seats.slice(0, 12).map((s) => (
                  <div key={s.seat_name} className="rounded-lg bg-muted/20 p-2.5">
                    <p className="truncate text-xs font-medium">{s.seat_name}</p>
                    <div className="mt-1 flex items-center justify-between text-[11px]">
                      <span className="text-muted-foreground">出现 {s.total_appearances} 次</span>
                      <span className={cn("font-mono", s.net_amt >= 0 ? "text-danger" : "text-success")}>
                        净{s.net_amt >= 0 ? "+" : ""}{(s.net_amt / 10000).toFixed(0)}万
                      </span>
                    </div>
                    <p className="mt-0.5 text-[10px] text-muted-foreground/50">
                      交易 {s.stock_cooldown} 只 · 最后 {s.last_seen || "未知"}
                    </p>
                  </div>
                ))}
              </div>
              {seats.length > 12 && (
                <p className="mt-1 text-[11px] text-muted-foreground/50">… 还有 {seats.length - 12} 个席位</p>
              )}
            </div>
          ))}
          <p className="text-[11px] text-muted-foreground/50">
            免责声明：席位标签基于龙虎榜历史数据统计特征，不代表对未来行为的预测，不构成投资建议。
          </p>
        </div>
      )}
    </GlassCard>
  );
}

// ── 主页面 ────────────────────────────────────────────────
export function LimitUpStrategy() {
  const [screener, setScreener] = useState<ScreenerResult | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  // 展开的个股
  const [expandedCode, setExpandedCode] = useState<string | null>(null);
  const [expandedData, setExpandedData] = useState<LimitUpAnalysis | null>(null);
  const [expandedLoading, setExpandedLoading] = useState(false);
  const [expandedError, setExpandedError] = useState<string | null>(null);

  const loadScreener = useCallback(() => {
    setLoading(true);
    setError(null);
    api.limitupScreener()
      .then(setScreener)
      .catch((e) => setError(e instanceof Error ? e.message : "加载失败"))
      .finally(() => setLoading(false));
  }, []);

  useEffect(() => {
    loadScreener();
  }, [loadScreener]);

  // 点击行展开个股分析
  const handleToggle = useCallback((code: string) => {
    setExpandedCode((prev) => {
      if (prev === code) {
        setExpandedData(null);
        setExpandedError(null);
        return null;
      }
      // 切换新行：先加载
      setExpandedLoading(true);
      setExpandedError(null);
      setExpandedData(null);
      api.limitupAnalysis(code)
        .then(setExpandedData)
        .catch((e) => setExpandedError(e instanceof Error ? e.message : "加载失败"))
        .finally(() => setExpandedLoading(false));
      return code;
    });
  }, []);

  // 构建 AI 上下文
  const aiContext = screener
    ? `【打板策略 - 基因得分清单】\n日期: ${screener.date}\n更新时间: ${screener.updated}\n\n`
    + `基因合格 (SCORE≥60): ${screener.qualified.length} 只\n高基因 (SCORE≥75): ${screener.high_gene.length} 只\n\n`
    + `涨停股基因得分:\n`
    + screener.gene_scores
        .map((g) => `  ${g.code} ${g.name}: 总分${g.total_score} | 溢价率${fmtPct(g.factors["次日溢价率"])} | 红盘率${fmtPct(g.factors["红盘率"])} | 封板率${fmtPct(g.factors["封板率"])}`)
        .join("\n")
    : "";

  const today = new Date().toLocaleDateString("zh-CN", { year: "numeric", month: "2-digit", day: "2-digit" });

  return (
    <div>
      <PageHeader
        title="打板策略"
        subtitle={`${today} · 涨停基因选股 · 策略逻辑教育 · 历史统计特征`}
        actions={
          <div className="flex items-center gap-2">
            <AskAiButton
              context={aiContext}
              label="问 AI"
              suggestions={[
                "这些高基因股的历史统计特征是什么？",
                "基因得分和次日表现有什么关系？",
                "哪些风控规则适用于打板策略？",
              ]}
            />
            <button
              onClick={loadScreener}
              className="inline-flex items-center gap-1.5 rounded-lg bg-primary/15 px-3 py-1.5 text-sm font-medium text-primary shadow-glow transition-colors hover:bg-primary/25"
              title="刷新数据"
            >
              {loading ? <Loader2 className="h-4 w-4 animate-spin" /> : <RefreshCw className="h-4 w-4" />}
              刷新
            </button>
          </div>
        }
      />

      {/* 统计摘要 */}
      <div className="mb-6 grid gap-4 sm:grid-cols-2">
        <GlassCard>
          <div className="flex items-center gap-2">
            <Flame className="h-5 w-5 text-primary" />
            <h3 className="text-sm font-semibold text-muted-foreground">基因合格</h3>
          </div>
          <p className="mt-2 text-3xl font-bold text-primary">
            {loading ? <Loader2 className="h-6 w-6 animate-spin" /> : screener?.qualified.length ?? "—"}
          </p>
          <p className="mt-1 text-xs text-muted-foreground">SCORE ≥ 60（合格线）</p>
        </GlassCard>
        <GlassCard>
          <div className="flex items-center gap-2">
            <Flame className="h-5 w-5 text-primary" />
            <h3 className="text-sm font-semibold text-muted-foreground">高基因股票</h3>
          </div>
          <p className="mt-2 text-3xl font-bold text-primary">
            {loading ? <Loader2 className="h-6 w-6 animate-spin" /> : screener?.high_gene.length ?? "—"}
          </p>
          <p className="mt-1 text-xs text-muted-foreground">SCORE ≥ 75（高基因线）</p>
        </GlassCard>
      </div>

      {/* 基因得分清单表格 */}
      <GlassCard className="mb-6">
        <div className="mb-3 flex items-center gap-2">
          <h3 className="text-sm font-semibold text-muted-foreground">涨停股基因得分清单</h3>
          <span className="text-[11px] text-muted-foreground/50">客观数据，非推荐</span>
          {screener?.disclaimer && (
            <span className="ml-auto text-[11px] text-muted-foreground/50">{screener.disclaimer}</span>
          )}
        </div>
        {error ? (
          <div className="flex items-center justify-center py-8 text-sm text-destructive">
            <Info className="mr-1.5 h-4 w-4" /> {error}
          </div>
        ) : (
          <ExpandableTable
            data={screener?.gene_scores ?? []}
            expandedCode={expandedCode}
            expandedData={expandedData}
            expandedLoading={expandedLoading}
            expandedError={expandedError}
            onToggle={handleToggle}
          />
        )}
      </GlassCard>

      {/* 竞价预案 TOP N */}
      <AuctionScreenerSection />

      {/* 席位引擎 */}
      <SeatEngineSection />

      {/* 免责声明 */}
      <div className="flex items-start gap-2 rounded-lg border border-border/40 bg-muted/10 p-2.5 text-[11px] leading-relaxed text-muted-foreground/60">
        <Info className="mt-0.5 h-3 w-3 shrink-0" />
        <span>
          本页面所有数据基于<strong>历史统计特征</strong>，不代表未来行为，<strong>不构成投资建议</strong>。
          基因得分反映的是个股涨停后的历史表现统计，策略逻辑条件匹配仅做教育性展示。
          股市有风险，投资需谨慎。
        </span>
      </div>
      <Disclaimer />
    </div>
  );
}
