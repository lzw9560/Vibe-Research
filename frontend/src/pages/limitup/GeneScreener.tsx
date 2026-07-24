import { useState, useEffect, useRef, useCallback, Fragment } from "react";
import { Loader2, RefreshCw, ChevronDown, ChevronUp, Info } from "lucide-react";
import { PageHeader } from "@/components/ui/PageHeader";
import { GlassCard } from "@/components/ui/GlassCard";
import { SectionHeader } from "@/components/ui/SectionHeader";
import { MetricCard } from "@/components/ui/MetricCard";
import { AskAiButton } from "@/components/ui/AskAiButton";
import { Disclaimer } from "@/components/ui/Disclaimer";
import { api, type GeneScore, type ScreenerResult, type LimitUpAnalysis } from "@/lib/api";

// ── 颜色约定 ──────────────────────────────────────────────
const scoreColor = (s: number) =>
  s >= 75 ? "text-primary"
  : s >= 60 ? "text-info"
  : "text-muted-foreground";

const scoreBg = (s: number) =>
  s >= 75 ? "bg-primary/10"
  : s >= 60 ? "bg-info/10"
  : "bg-muted/20";

const fmtPct = (v: number | null | undefined) =>
  v == null ? "—" : `${v.toFixed(1)}%`;

// 五维因子键名（与后端一致）
const FACTOR_KEYS: string[] = ["次日溢价率", "红盘率", "封板率", "炸板后溢价", "涨停频次"];

// 表格显示的因子列（不含涨停频次，因为频次用 zt_count_250d 展示）
const DISPLAY_FACTORS: string[] = ["次日溢价率", "红盘率", "封板率", "炸板后溢价"];

// ── 基因得分雷达图 ────────────────────────────────────────
function GeneScoreChart({ factors, wilsonAdjusted }: { factors: Record<string, number>; wilsonAdjusted: number }) {
  const chartRef = useRef<HTMLDivElement>(null);
  const instanceRef = useRef<import("echarts").ECharts | null>(null);
  const [echarts, setEcharts] = useState<typeof import("echarts") | null>(null);

  useEffect(() => {
    import("echarts").then((module) => {
      setEcharts(() => module);
    });
  }, []);

  useEffect(() => {
    if (!chartRef.current || !echarts) return;
    instanceRef.current = echarts.init(chartRef.current);
    const indicator = FACTOR_KEYS.map((k) => ({
      name: String(k),
      max: 100,
    }));
    const values = FACTOR_KEYS.map((k) => Number(factors[k]) ?? 0);
    const option: import("echarts").EChartsOption = {
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
  }, [factors, wilsonAdjusted, echarts]);

  return <div ref={chartRef} className="h-[220px]" />;
}

// ── 基因得分回测散点图 ──────────────────────────────────────
function BacktestScatterChart({ points }: {
  points: Array<{ date: string; gene_score: number; actual_next_day: number }>;
}) {
  const chartRef = useRef<HTMLDivElement>(null);
  const instanceRef = useRef<import("echarts").ECharts | null>(null);
  const [echarts, setEcharts] = useState<typeof import("echarts") | null>(null);

  useEffect(() => {
    import("echarts").then((module) => {
      setEcharts(() => module);
    });
  }, []);

  useEffect(() => {
    if (!chartRef.current || !echarts || points.length === 0) return;
    instanceRef.current = echarts.init(chartRef.current);

    const lianban = points.filter(p => p.actual_next_day >= 1);
    const no_lianban = points.filter(p => p.actual_next_day < 1);

    const option: import("echarts").EChartsOption = {
      tooltip: {
        trigger: "item",
        formatter: (p: any) => {
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
  }, [points, echarts]);

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

  const { gene_score, strategy_logic, risk, risk_rules, backtest_points } = analysis;
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
                {r.configurable && <span className="rounded bg-info/10 px-1.5 py-0.5 text-[10px] text-info">可配置</span>}
                <span className="text-muted-foreground">默认: {r.default_value}</span>
              </div>
              <p className="mt-0.5 text-muted-foreground/70">{r.description}</p>
              <p className="mt-0.5 text-muted-foreground/50 italic">示例: {r.example}</p>
            </div>
          ))}
        </div>
      </GlassCard>

      {/* 封单额/流通盘 + 涨跌停价 */}
      <GlassCard className="p-3">
        <h4 className="mb-1.5 text-sm font-semibold text-muted-foreground">封单与涨跌停（客观数据）</h4>
        <div className="grid grid-cols-2 gap-2 text-xs">
          <div className="rounded-lg bg-muted/25 p-2">
            <div className="text-muted-foreground">封单额</div>
            <div className="mt-0.5 text-base font-bold">{(analysis.seal_amount / 10000).toFixed(1)}万</div>
          </div>
          <div className="rounded-lg bg-muted/25 p-2">
            <div className="text-muted-foreground">流通盘</div>
            <div className="mt-0.5 text-base font-bold">{(analysis.float_shares / 100000000).toFixed(2)}亿股</div>
          </div>
          <div className="rounded-lg bg-muted/25 p-2">
            <div className="text-muted-foreground">封单/流通盘比</div>
            <div className="mt-0.5 text-base font-bold">{(analysis.seal_to_float_ratio * 100).toFixed(2)}%</div>
          </div>
          <div className="rounded-lg bg-muted/25 p-2">
            <div className="text-muted-foreground">涨跌停价</div>
            <div className="mt-0.5 text-base font-bold">
              {analysis.limit_up_price > 0 ? (
                <span>
                  <span className="text-primary">↑{analysis.limit_up_price.toFixed(2)}</span>
                  <span className="text-muted-foreground mx-1">/</span>
                  <span className="text-destructive">↓{analysis.limit_down_price.toFixed(2)}</span>
                </span>
              ) : "—"}
            </div>
          </div>
        </div>
      </GlassCard>

      {/* 动态一日游风险评估（V2.0.2） */}
      {risk && (
        <GlassCard className="p-3">
          <h4 className="mb-1.5 text-sm font-semibold text-muted-foreground">动态一日游风险评估（教育性展示）</h4>
          <div className="grid grid-cols-2 gap-2 text-xs">
            <div className="rounded-lg bg-muted/25 p-2">
              <div className="text-muted-foreground">风险评分</div>
              <div className="mt-0.5 text-base font-bold">{risk.risk_score}</div>
            </div>
            <div className="rounded-lg bg-muted/25 p-2">
              <div className="text-muted-foreground">风险等级</div>
              <div className="mt-0.5 text-base font-bold">{risk.risk_level}</div>
            </div>
            <div className="rounded-lg bg-muted/25 p-2">
              <div className="text-muted-foreground">资金流信号</div>
              <div className="mt-0.5 text-base font-bold">{risk.capital_flow_signal}</div>
            </div>
            <div className="rounded-lg bg-muted/25 p-2">
              <div className="text-muted-foreground">资金流趋势</div>
              <div className="mt-0.5 text-base font-bold">{risk.capital_flow_trend}</div>
            </div>
          </div>
          {risk.recommendation && (
            <div className="mt-2 rounded-lg bg-muted/25 p-2 text-xs text-muted-foreground/80">
              {risk.recommendation}
            </div>
          )}
          {risk.risk_factors && risk.risk_factors.length > 0 && (
            <div className="mt-2 text-xs text-muted-foreground/70">
              风险因子: {risk.risk_factors.join("、")}
            </div>
          )}
        </GlassCard>
      )}
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

// ── 主页面：基因选股 ────────────────────────────────────────
export function GeneScreener() {
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
        title="基因选股"
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
        <MetricCard label="基因合格" value={screener?.qualified.length ?? "—"} valueClassName="text-primary" />
        <MetricCard label="高基因股票" value={screener?.high_gene.length ?? "—"} valueClassName="text-primary" />
        {screener?.data_freshness && (
          <GlassCard className="sm:col-span-2">
            <div className="flex items-center gap-2 text-xs">
              <span className={`inline-block rounded px-1.5 py-0.5 ${
                screener.data_freshness === "fresh" ? "bg-green-500/10 text-green-600" :
                screener.data_freshness === "stale" ? "bg-yellow-500/10 text-yellow-600" :
                "bg-red-500/10 text-red-600"
              }`}>
                {screener.data_freshness === "fresh" ? "数据新鲜" :
                 screener.data_freshness === "stale" ? "数据较旧" : "数据过期"}
              </span>
              <span className="text-muted-foreground">
                数据年龄: {screener.data_age_seconds < 60 ? `${Math.round(screener.data_age_seconds)}秒` :
                           screener.data_age_seconds < 3600 ? `${Math.round(screener.data_age_seconds / 60)}分钟` :
                           `${(screener.data_age_seconds / 3600).toFixed(1)}小时`}
              </span>
              <span className="text-muted-foreground/50">更新时间: {screener.updated}</span>
            </div>
          </GlassCard>
        )}
      </div>

      {/* 基因得分清单表格 */}
      <GlassCard className="mb-6">
        <SectionHeader title="涨停股基因得分清单" subtitle="客观数据，非推荐" />
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
