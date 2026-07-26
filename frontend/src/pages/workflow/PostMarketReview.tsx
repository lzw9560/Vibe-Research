import { useState, useEffect, useMemo } from "react";
import { BarChart3, TrendingUp, TrendingDown, Calendar, RefreshCw, ChevronDown, ChevronUp, Award, Target } from "lucide-react";
import { PageHeader } from "@/components/ui/PageHeader";
import { GlassCard } from "@/components/ui/GlassCard";
import { Button } from "@/components/ui/Button";
import { Skeleton } from "@/components/ui/Skeleton";
import { Badge } from "@/components/ui/Badge";
import { getPostMarketReview } from "@/lib/api";

// ─── Types ───────────────────────────────────────────────────────────────────

interface SettlementItem {
  code: string;
  name: string;
  buy_price?: number | string;
  sell_price?: number | string;
  entry_price?: number | string;
  exit_price?: number | string;
  hold_days?: number;
  return_pct?: number;
  won?: boolean;
  strategy_used?: string;
  type?: string;
  result?: string;
  [key: string]: unknown;
}

interface AdjustmentItem {
  strategy?: string;
  type?: string;
  action?: string;
  reason?: string;
  [key: string]: unknown;
}

interface PostMarketReport {
  date?: string;
  generated_at?: string;
  total_trades?: number;
  win_count?: number;
  loss_count?: number;
  win_rate?: number;
  total_return?: number;
  avg_return?: number;
  max_drawdown?: number;
  settlements?: SettlementItem[];
  adjustments?: AdjustmentItem[];
  daily_returns?: { date: string; return: number }[];
  updated?: string;
  disclaimer?: string;
}

type SortDirection = "asc" | "desc";

interface SortConfig {
  key: keyof SettlementItem;
  direction: SortDirection;
}

// ─── Helpers ─────────────────────────────────────────────────────────────────

const formatPrice = (v: number | string | undefined): string => {
  if (v == null || v === "") return "-";
  const n = typeof v === "string" ? parseFloat(v) : v;
  if (isNaN(n)) return String(v);
  return n.toLocaleString("zh-CN", { minimumFractionDigits: 2, maximumFractionDigits: 2 });
};

const formatPct = (v: number | undefined, sign = true): string => {
  if (v == null) return "-";
  const s = sign && v >= 0 ? "+" : "";
  return `${s}${v.toFixed(2)}%`;
};

// ─── SVG Circular Progress Ring ──────────────────────────────────────────────

function CircularProgressRing({ value, size = 96, strokeWidth = 8 }: { value: number; size?: number; strokeWidth?: number }) {
  const radius = (size - strokeWidth) / 2;
  const circumference = 2 * Math.PI * radius;
  const offset = circumference - value * circumference;
  const color = value >= 0.5 ? "#22c55e" : value >= 0.3 ? "#eab308" : "#ef4444";

  return (
    <svg width={size} height={size} className="block">
      <circle
        cx={size / 2}
        cy={size / 2}
        r={radius}
        fill="none"
        stroke="rgba(255,255,255,0.08)"
        strokeWidth={strokeWidth}
      />
      <circle
        cx={size / 2}
        cy={size / 2}
        r={radius}
        fill="none"
        stroke={color}
        strokeWidth={strokeWidth}
        strokeDasharray={circumference}
        strokeDashoffset={offset}
        strokeLinecap="round"
        transform={`rotate(-90 ${size / 2} ${size / 2})`}
        className="transition-all duration-700 ease-out"
      />
      <text
        x={size / 2}
        y={size / 2}
        textAnchor="middle"
        dominantBaseline="central"
        className="fill-white text-lg font-bold"
        style={{ fontSize: size * 0.22 }}
      >
        {(value * 100).toFixed(1)}%
      </text>
    </svg>
  );
}

// ─── SVG Mini Sparkline ──────────────────────────────────────────────────────

function MiniSparkline({ positive }: { positive: boolean }) {
  const points = positive
    ? "0,20 10,18 20,15 30,16 40,12 50,10 60,8 70,9 80,5 90,3 100,0"
    : "0,0 10,3 20,2 30,5 40,4 50,8 60,7 70,10 80,12 90,15 100,20";

  return (
    <svg width="100" height="24" className="opacity-40" aria-hidden="true">
      <polyline
        points={points}
        fill="none"
        stroke={positive ? "#22c55e" : "#ef4444"}
        strokeWidth="2"
        strokeLinecap="round"
        strokeLinejoin="round"
      />
    </svg>
  );
}

// ─── Returns Trend Chart ─────────────────────────────────────────────────────

function ReturnsTrendChart({ data }: { data: { date: string; return: number }[] }) {
  if (!data || data.length === 0) {
    return (
      <div className="flex flex-col items-center justify-center py-12 text-muted-foreground/50">
        <BarChart3 className="mb-3 h-10 w-10 opacity-30" />
        <p className="text-sm">单日数据暂不支持趋势图</p>
        <p className="mt-1 text-xs">多日数据将在此展示累计收益走势</p>
      </div>
    );
  }

  const padding = { top: 20, right: 20, bottom: 36, left: 48 };
  const width = 700;
  const height = 220;
  const chartW = width - padding.left - padding.right;
  const chartH = height - padding.top - padding.bottom;

  // Compute cumulative returns
  const cumulative = data.reduce<{ date: string; val: number }[]>(
    (acc, d) => {
      const prev = acc.length > 0 ? acc[acc.length - 1].val : 0;
      acc.push({ date: d.date, val: prev + d.return });
      return acc;
    },
    []
  );

  const values = cumulative.map((c) => c.val);
  const minVal = Math.min(...values, 0);
  const maxVal = Math.max(...values, 0);
  const range = maxVal - minVal || 1;

  const xStep = chartW / Math.max(cumulative.length - 1, 1);

  const xPos = (i: number) => padding.left + i * xStep;
  const yPos = (v: number) => padding.top + chartH - ((v - minVal) / range) * chartH;

  // Build path
  const linePath = cumulative.map((c, i) => `${i === 0 ? "M" : "L"}${xPos(i)},${yPos(c.val)}`).join(" ");
  const areaPath = `${linePath} L${xPos(cumulative.length - 1)},${padding.top + chartH} L${padding.left},${padding.top + chartH} Z`;

  // Zero line
  const zeroY = yPos(0);

  // Grid lines
  const gridLines = 4;
  const gridValues = Array.from({ length: gridLines + 1 }, (_, i) => minVal + (range * i) / gridLines);

  // X-axis labels (show at most ~8 labels)
  const labelCount = Math.min(cumulative.length, 8);
  const labelStep = Math.max(Math.floor(cumulative.length / labelCount), 1);

  return (
    <div className="w-full overflow-x-auto">
      <svg viewBox={`0 0 ${width} ${height}`} className="w-full min-w-[500px]" role="img" aria-label="累计收益趋势图">
        <defs>
          <linearGradient id="areaGradPositive" x1="0" y1="0" x2="0" y2="1">
            <stop offset="0%" stopColor="#22c55e" stopOpacity="0.25" />
            <stop offset="100%" stopColor="#22c55e" stopOpacity="0.02" />
          </linearGradient>
          <linearGradient id="areaGradNegative" x1="0" y1="0" x2="0" y2="1">
            <stop offset="0%" stopColor="#ef4444" stopOpacity="0.02" />
            <stop offset="100%" stopColor="#ef4444" stopOpacity="0.25" />
          </linearGradient>
        </defs>

        {/* Grid */}
        {gridValues.map((v, i) => (
          <g key={i}>
            <line
              x1={padding.left}
              x2={width - padding.right}
              y1={yPos(v)}
              y2={yPos(v)}
              stroke="rgba(255,255,255,0.06)"
              strokeDasharray="4 4"
            />
            <text
              x={padding.left - 8}
              y={yPos(v)}
              textAnchor="end"
              dominantBaseline="central"
              className="fill-muted-foreground"
              style={{ fontSize: 10 }}
            >
              {v.toFixed(1)}%
            </text>
          </g>
        ))}

        {/* Area fill */}
        <path d={areaPath} fill={cumulative[cumulative.length - 1]?.val >= 0 ? "url(#areaGradPositive)" : "url(#areaGradNegative)"} />

        {/* Zero line */}
        {minVal < 0 && maxVal > 0 && (
          <line
            x1={padding.left}
            x2={width - padding.right}
            y1={zeroY}
            y2={zeroY}
            stroke="rgba(255,255,255,0.15)"
            strokeWidth={1}
          />
        )}

        {/* Line */}
        <path d={linePath} fill="none" stroke={cumulative[cumulative.length - 1]?.val >= 0 ? "#22c55e" : "#ef4444"} strokeWidth={2} strokeLinecap="round" strokeLinejoin="round" />

        {/* Data points */}
        {cumulative.map((c, i) => (
          <g key={i}>
            <circle cx={xPos(i)} cy={yPos(c.val)} r={3.5} fill={c.val >= 0 ? "#22c55e" : "#ef4444"} stroke="rgba(0,0,0,0.4)" strokeWidth={1.5} />
            {i % labelStep === 0 && (
              <text
                x={xPos(i)}
                y={height - 8}
                textAnchor="middle"
                className="fill-muted-foreground"
                style={{ fontSize: 10 }}
              >
                {c.date}
              </text>
            )}
          </g>
        ))}
      </svg>
    </div>
  );
}

// ─── Main Component ──────────────────────────────────────────────────────────

export default function PostMarketReview() {
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [report, setReport] = useState<PostMarketReport | null>(null);
  const [selectedDate, setSelectedDate] = useState(() => new Date().toISOString().slice(0, 10));
  const [sortConfig, setSortConfig] = useState<SortConfig>({ key: "return_pct", direction: "desc" });
  const [adjustmentsOpen, setAdjustmentsOpen] = useState(false);

  const loadData = async () => {
    try {
      setError(null);
      const payload = await getPostMarketReview(selectedDate);
      setReport(payload as PostMarketReport | null);
    } catch (e) {
      setError(e instanceof Error ? e.message : "加载失败");
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    loadData();
  }, [selectedDate]);

  // Sort settlements by return_pct
  const sortedSettlements = useMemo(() => {
    if (!report?.settlements) return [];
    const sorted = [...report.settlements];
    sorted.sort((a, b) => {
      const aVal = a[sortConfig.key] ?? (sortConfig.key === "hold_days" ? 0 : 0);
      const bVal = b[sortConfig.key] ?? (sortConfig.key === "hold_days" ? 0 : 0);
      if (typeof aVal === "number" && typeof bVal === "number") {
        return sortConfig.direction === "desc" ? bVal - aVal : aVal - bVal;
      }
      return 0;
    });
    return sorted;
  }, [report?.settlements, sortConfig]);

  const toggleSort = (key: keyof SettlementItem) => {
    setSortConfig((prev) => ({
      key,
      direction: prev.key === key && prev.direction === "desc" ? "asc" : "desc",
    }));
  };

  const SortIcon = ({ columnKey }: { columnKey: keyof SettlementItem }) => {
    if (sortConfig.key !== columnKey) return null;
    return sortConfig.direction === "desc" ? <ChevronDown className="ml-1 inline h-3 w-3" /> : <ChevronUp className="ml-1 inline h-3 w-3" />;
  };

  if (loading) {
    return (
      <div className="space-y-6">
        <PageHeader title="盘后复盘" subtitle="Post-Market Review" />
        <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
          <Skeleton className="h-32 w-full" />
          <Skeleton className="h-32 w-full" />
          <Skeleton className="h-32 w-full" />
        </div>
        <Skeleton className="h-64 w-full" />
      </div>
    );
  }

  if (error) {
    return (
      <div className="space-y-6">
        <PageHeader title="盘后复盘" subtitle="Post-Market Review" />
        <GlassCard className="p-6">
          <div className="text-center text-red-400">
            <p className="text-lg font-medium">加载失败</p>
            <p className="mt-2 text-sm text-white/60">{error}</p>
            <Button variant="primary" size="md" onClick={loadData} className="mt-4">
              重试
            </Button>
          </div>
        </GlassCard>
      </div>
    );
  }

  if (!report) {
    return (
      <div className="space-y-6">
        <PageHeader title="盘后复盘" subtitle="Post-Market Review" />
        <GlassCard className="p-6">
          <p className="text-white/60">暂无盘后数据</p>
        </GlassCard>
      </div>
    );
  }

  const totalTrades = (report.settlements ?? []).length;
  const winRate = report.win_rate ?? 0;
  const totalReturn = report.total_return ?? 0;
  const profitCount = (report.settlements ?? []).filter((s) => s.won).length;
  const lossCount = totalTrades - profitCount;

  return (
    <div className="space-y-6">
      {/* ── Header ─────────────────────────────────────────────────────── */}
      <PageHeader
        title="盘后复盘"
        subtitle={`${report.date ?? ""} · 生成于 ${report.generated_at ?? ""}`}
        actions={
          <div className="flex items-center gap-2">
            <label className="inline-flex items-center gap-1.5 rounded-lg bg-muted/20 px-3 py-1.5 text-sm text-muted-foreground hover:bg-muted/30 transition-colors cursor-pointer">
              <Calendar className="h-4 w-4" />
              <input
                type="date"
                value={selectedDate}
                onChange={(e) => setSelectedDate(e.target.value)}
                className="bg-transparent outline-none text-sm text-foreground/90 cursor-pointer"
              />
            </label>
            <Button variant="ghost" size="sm" onClick={loadData}>
              <RefreshCw className="mr-1.5 h-4 w-4" />
              刷新
            </Button>
          </div>
        }
      />

      {/* ── KPI Cards ──────────────────────────────────────────────────── */}
      <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
        {/* Total Trades */}
        <GlassCard glow className="p-6">
          <div className="flex items-center justify-between">
            <div>
              <p className="text-sm text-white/60 mb-1">总交易笔数</p>
              <p className="text-4xl font-bold tracking-tight">{totalTrades}</p>
              <p className="mt-1 text-xs text-white/40">
                盈利 {profitCount} · 亏损 {lossCount}
              </p>
            </div>
            <Award className="h-10 w-10 text-primary/40" />
          </div>
        </GlassCard>

        {/* Win Rate */}
        <GlassCard glow className="p-6">
          <div className="flex items-center justify-between">
            <div>
              <p className="text-sm text-white/60 mb-1">胜率</p>
              <p className="text-4xl font-bold tracking-tight">
                {(winRate * 100).toFixed(1)}%
              </p>
              <p className="mt-1 text-xs text-white/40">
                目标胜率 ≥ 50%
              </p>
            </div>
            <CircularProgressRing value={winRate} />
          </div>
        </GlassCard>

        {/* Total Return */}
        <GlassCard glow className="p-6">
          <div className="flex items-center justify-between">
            <div>
              <p className="text-sm text-white/60 mb-1">总收益率</p>
              <p className={`text-4xl font-bold tracking-tight ${totalReturn >= 0 ? "text-green-400" : "text-red-400"}`}>
                {formatPct(totalReturn)}
              </p>
              <p className="mt-1 text-xs text-white/40">
                {totalReturn >= 0 ? "累计正收益" : "累计负收益"}
              </p>
            </div>
            <div className="flex flex-col items-end gap-1">
              <MiniSparkline positive={totalReturn >= 0} />
              {totalReturn >= 0 ? (
                <TrendingUp className="h-5 w-5 text-green-400/60" />
              ) : (
                <TrendingDown className="h-5 w-5 text-red-400/60" />
              )}
            </div>
          </div>
        </GlassCard>
      </div>

      {/* ── Returns Trend ──────────────────────────────────────────────── */}
      <GlassCard glow className="p-6">
        <h3 className="text-base font-semibold mb-4 flex items-center gap-2">
          <BarChart3 className="h-4 w-4 text-primary/60" />
          累计收益趋势
        </h3>
        <ReturnsTrendChart data={report.daily_returns ?? []} />
      </GlassCard>

      {/* ── Settlements Table ──────────────────────────────────────────── */}
      <GlassCard glow className="p-6">
        <h3 className="text-base font-semibold mb-4 flex items-center gap-2">
          <Target className="h-4 w-4 text-primary/60" />
          结算明细
        </h3>
        {sortedSettlements.length === 0 ? (
          <p className="text-white/60 py-8 text-center">暂无结算记录</p>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                <tr className="border-b border-white/10 bg-white/5">
                  <th className="whitespace-nowrap px-3 py-2.5 text-left text-xs font-medium text-white/50">标的</th>
                  <th className="whitespace-nowrap px-3 py-2.5 text-right text-xs font-medium text-white/50">买入价</th>
                  <th className="whitespace-nowrap px-3 py-2.5 text-right text-xs font-medium text-white/50">卖出价</th>
                  <th className="whitespace-nowrap px-3 py-2.5 text-right text-xs font-medium text-white/50">持仓天数</th>
                  <th
                    className="whitespace-nowrap px-3 py-2.5 text-right text-xs font-medium text-white/50 cursor-pointer select-none hover:text-white/80 transition-colors"
                    onClick={() => toggleSort("return_pct")}
                  >
                    <span className="inline-flex items-center">收益率
                      <SortIcon columnKey="return_pct" />
                    </span>
                  </th>
                  <th className="whitespace-nowrap px-3 py-2.5 text-left text-xs font-medium text-white/50">战法</th>
                  <th className="whitespace-nowrap px-3 py-2.5 text-center text-xs font-medium text-white/50">结果</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-white/5">
                {sortedSettlements.map((item) => {
                  const code = item.code ?? "";
                  const name = item.name ?? "";
                  const buyPrice = formatPrice(item.buy_price ?? item.entry_price);
                  const sellPrice = formatPrice(item.sell_price ?? item.exit_price);
                  const holdDays = item.hold_days ?? 0;
                  const returnPct = item.return_pct ?? 0;
                  const isWin = item.won ?? returnPct > 0;
                  const strategy = item.strategy_used ?? "-";

                  return (
                    <tr key={code} className="transition-colors hover:bg-white/5">
                      <td className="px-3 py-2.5">
                        <span className="font-medium text-foreground">{code}</span>
                        <span className="ml-1.5 text-xs text-muted-foreground">{name}</span>
                      </td>
                      <td className="px-3 py-2.5 text-right text-muted-foreground">{buyPrice}</td>
                      <td className="px-3 py-2.5 text-right text-muted-foreground">{sellPrice}</td>
                      <td className="px-3 py-2.5 text-right text-muted-foreground">{holdDays}</td>
                      <td className={`px-3 py-2.5 text-right font-mono font-medium ${isWin ? "text-green-400" : "text-red-400"}`}>
                        {formatPct(returnPct)}
                      </td>
                      <td className="px-3 py-2.5 text-muted-foreground">{strategy}</td>
                      <td className="px-3 py-2.5 text-center">
                        <Badge variant={isWin ? "success" : "danger"}>
                          {isWin ? "盈利" : "亏损"}
                        </Badge>
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        )}
      </GlassCard>

      {/* ── Strategy Adjustments (Collapsible) ─────────────────────────── */}
      {report.adjustments && report.adjustments.length > 0 && (
        <GlassCard glow>
          <button
            onClick={() => setAdjustmentsOpen(!adjustmentsOpen)}
            className="flex w-full items-center justify-between p-6 text-left"
            aria-expanded={adjustmentsOpen}
          >
            <h3 className="text-base font-semibold flex items-center gap-2">
              <Award className="h-4 w-4 text-primary/60" />
              策略调整建议
            </h3>
            {adjustmentsOpen ? (
              <ChevronUp className="h-4 w-4 text-muted-foreground" />
            ) : (
              <ChevronDown className="h-4 w-4 text-muted-foreground" />
            )}
          </button>
          {adjustmentsOpen && (
            <div className="px-6 pb-6 space-y-3">
              {report.adjustments.map((adj, idx) => {
                const strategyLabel = adj.strategy || adj.type || `调整 ${idx + 1}`;
                return (
                  <div key={`${strategyLabel}-${idx}`} className="rounded-lg bg-white/5 border border-white/10 p-4">
                    <div className="flex items-start justify-between gap-3 mb-2">
                      <span className="font-medium text-foreground">{strategyLabel}</span>
                      {adj.action && (
                        <Badge variant="info" className="shrink-0">{adj.action}</Badge>
                      )}
                    </div>
                    <p className="text-sm text-white/70">{adj.reason || "暂无说明"}</p>
                  </div>
                );
              })}
            </div>
          )}
        </GlassCard>
      )}
    </div>
  );
}
