import { useState, useEffect, useMemo, useCallback } from "react";
import { Activity, TrendingUp, ShieldAlert, RefreshCw, Star, ChevronDown, ChevronUp } from "lucide-react";
import { PageHeader } from "@/components/ui/PageHeader";
import { GlassCard } from "@/components/ui/GlassCard";
import { Button } from "@/components/ui/Button";
import { Skeleton } from "@/components/ui/Skeleton";
import { Badge } from "@/components/ui/Badge";
import { Input } from "@/components/ui/Input";

// ─── TypeScript Interfaces ───────────────────────────────────────────────────

interface Candidate {
  code: string;
  name: string;
  price?: number;
  change_pct?: number;
  score?: number;
  [key: string]: unknown;
}

interface StrategyMatch {
  strategy_name?: string;
  style?: string;
  match_score?: number;
  confidence?: number;
  description?: string;
  entry_condition?: string;
  [key: string]: unknown;
}

interface PositionSuggestion {
  code: string;
  name: string;
  suggested_weight?: number;
  weight?: number;
  reason?: string;
  action?: string;
  [key: string]: unknown;
}

interface PreMarketReport {
  date: string;
  generated_at: string;
  sentiment_index: number;
  sentiment_phase: string;
  candidates: Candidate[];
  strong_candidates: Candidate[];
  filtered_out: Candidate[];
  strategy_matches: StrategyMatch[];
  position_suggestions: PositionSuggestion[];
  total_suggested_position: number;
  warnings: string[];
}

// ─── Helpers ─────────────────────────────────────────────────────────────────

const STRONG_CODES = new Set<string>();

function getStrongCodeSet(report: PreMarketReport): Set<string> {
  if (STRONG_CODES.size === 0) {
    for (const c of report.strong_candidates) {
      if (c.code) STRONG_CODES.add(String(c.code));
    }
  }
  return STRONG_CODES;
}

function isStrong(code: string, strongSet: Set<string>): boolean {
  return strongSet.has(code);
}

function formatRelativeTime(generatedAt: string): string {
  try {
    const gen = new Date(generatedAt).getTime();
    const now = Date.now();
    const diffMin = Math.floor((now - gen) / 60000);
    if (diffMin < 1) return "刚刚";
    if (diffMin < 60) return `${diffMin} 分钟前`;
    const diffHr = Math.floor(diffMin / 60);
    return `${diffHr} 小时前`;
  } catch {
    return generatedAt;
  }
}

function sentimentColor(value: number): string {
  if (value >= 70) return "#22c55e";
  if (value >= 40) return "#eab308";
  return "#ef4444";
}


function sentimentPhaseLabel(phase: string): string {
  const map: Record<string, string> = {
    bullish: "强势",
    bearish: "弱势",
    neutral: "中性",
    turning: "转折",
    accumulation: "蓄势",
    distribution: "派发",
  };
  return map[phase.toLowerCase()] ?? phase;
}

type SortField = "score" | "change_pct" | "price" | "code" | "name";
type SortDir = "asc" | "desc";

// ─── Component ───────────────────────────────────────────────────────────────

export default function PreMarketBriefing() {
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [report, setReport] = useState<PreMarketReport | null>(null);
  const [search, setSearch] = useState("");
  const [sortField, setSortField] = useState<SortField>("score");
  const [sortDir, setSortDir] = useState<SortDir>("desc");
  const [lastRefreshed, setLastRefreshed] = useState<Date>(new Date());
  const [refreshing, setRefreshing] = useState(false);

  // Fetch data
  const loadData = useCallback(async () => {
    try {
      setError(null);
      const resp = await fetch("/api/workflow/pre-market");
      const data = await resp.json();
      const payload = data?.data ?? data;
      setReport(payload as PreMarketReport);
      setLastRefreshed(new Date());
    } catch (e) {
      setError(e instanceof Error ? e.message : "加载失败");
    } finally {
      setLoading(false);
      setRefreshing(false);
    }
  }, []);

  const handleRefresh = useCallback(() => {
    setRefreshing(true);
    loadData();
  }, [loadData]);

  // Initial load + auto-refresh every 60s during trading hours (9:00–15:00)
  useEffect(() => {
    loadData();
  }, [loadData]);

  useEffect(() => {
    const interval = setInterval(() => {
      const hour = new Date().getHours();
      if (hour >= 9 && hour < 15) {
        loadData();
      }
    }, 60_000);
    return () => clearInterval(interval);
  }, [loadData]);

  // Sorted + filtered candidate pool
  const strongSet = useMemo(
    () => (report ? getStrongCodeSet(report) : new Set<string>()),
    [report],
  );

  const sortedCandidates = useMemo(() => {
    let list = [...(report?.candidates ?? [])];
    if (search.trim()) {
      const q = search.trim().toLowerCase();
      list = list.filter(
        (c) =>
          String(c.code ?? "").toLowerCase().includes(q) ||
          String(c.name ?? "").toLowerCase().includes(q),
      );
    }
    list.sort((a, b) => {
      const av = a[sortField];
      const bv = b[sortField];
      if (typeof av === "number" && typeof bv === "number") {
        return sortDir === "asc" ? av - bv : bv - av;
      }
      return sortDir === "asc"
        ? String(av ?? "").localeCompare(String(bv ?? ""))
        : String(bv ?? "").localeCompare(String(av ?? ""));
    });
    return list;
  }, [report, search, sortField, sortDir]);

  const toggleSort = (field: SortField) => {
    if (sortField === field) {
      setSortDir((d) => (d === "asc" ? "desc" : "asc"));
    } else {
      setSortField(field);
      setSortDir("desc");
    }
  };

  const SortIcon = ({ field }: { field: SortField }) => {
    if (sortField !== field) return null;
    return sortDir === "asc" ? (
      <ChevronUp className="ml-1 h-3 w-3" />
    ) : (
      <ChevronDown className="ml-1 h-3 w-3" />
    );
  };

  if (loading) {
    return (
      <div className="space-y-6">
        <PageHeader title="盘前简报" subtitle="Pre-Market Briefing" />
        <Skeleton variant="rectangular" lines={3} />
        <Skeleton variant="rounded" />
        <Skeleton variant="rounded" />
      </div>
    );
  }

  if (error) {
    return (
      <div className="space-y-6">
        <PageHeader title="盘前简报" subtitle="Pre-Market Briefing" />
        <GlassCard className="p-6">
          <div className="text-center text-destructive">
            <ShieldAlert className="mx-auto mb-3 h-10 w-10 text-destructive/60" />
            <p className="text-lg font-medium">加载失败</p>
            <p className="mt-2 text-sm text-muted-foreground">{error}</p>
            <Button variant="primary" size="md" onClick={handleRefresh} className="mt-4">
              <RefreshCw className="mr-1.5 h-4 w-4" />
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
        <PageHeader title="盘前简报" subtitle="Pre-Market Briefing" />
        <GlassCard className="p-6">
          <p className="text-muted-foreground">暂无盘前数据</p>
        </GlassCard>
      </div>
    );
  }

  const sentimentVal = report.sentiment_index;
  const phaseLabel = sentimentPhaseLabel(report.sentiment_phase);
  const phaseBadgeVariant =
    sentimentVal >= 70
      ? ("success" as const)
      : sentimentVal >= 40
        ? ("warning" as const)
        : ("danger" as const);

  const gaugeGradient = `linear-gradient(90deg, #ef4444 0%, #eab308 ${Math.max(0, (sentimentVal - 40) * 3.33)}%, #22c55e 100%)`;

  return (
    <div className="space-y-6">
      {/* ── Header ───────────────────────────────────────────────────── */}
      <PageHeader
        title="盘前简报"
        subtitle={`${report.date} · 更新于 ${formatRelativeTime(report.generated_at)}`}
        actions={
          <Button variant="ghost" size="sm" onClick={handleRefresh} disabled={refreshing}>
            <RefreshCw className={`mr-1.5 h-4 w-4 ${refreshing ? "animate-spin" : ""}`} />
            {refreshing ? "刷新中…" : "刷新"}
          </Button>
        }
      />

      {/* ── Sentiment Gauge ──────────────────────────────────────────── */}
      <GlassCard glow className="p-6">
        <div className="flex items-center justify-between">
          <h3 className="flex items-center gap-2 text-lg font-semibold">
            <Activity className="h-5 w-5 text-primary" />
            市场情绪
          </h3>
          <Badge variant={phaseBadgeVariant}>{phaseLabel}</Badge>
        </div>

        {/* CSS gradient arc gauge */}
        <div className="relative mt-4">
          <div className="flex items-end justify-between text-xs text-muted-foreground">
            <span>0</span>
            <span>40</span>
            <span>70</span>
            <span>100</span>
          </div>
          <div className="relative mt-2 h-4 w-full overflow-hidden rounded-full bg-white/10">
            <div
              className="absolute inset-y-0 left-0 rounded-full transition-all duration-700 ease-out"
              style={{
                width: `${Math.min(100, Math.max(0, sentimentVal))}%`,
                background: gaugeGradient,
              }}
            />
          </div>
          {/* Needle indicator */}
          <div
            className="absolute top-[-4px] transition-all duration-700"
            style={{
              left: `calc(${Math.min(100, Math.max(0, sentimentVal))}% - 6px)`,
            }}
          >
            <div className="h-6 w-1.5 rounded-full" style={{ backgroundColor: sentimentColor(sentimentVal) }} />
          </div>
        </div>

        <div className="mt-3 flex items-center justify-between">
          <div className="text-3xl font-extrabold" style={{ color: sentimentColor(sentimentVal) }}>
            {sentimentVal.toFixed(1)}
          </div>
          <span className="text-xs text-muted-foreground">
            上次刷新: {lastRefreshed.toLocaleTimeString("zh-CN")}
          </span>
        </div>
      </GlassCard>

      {/* ── Quick Stats Row ──────────────────────────────────────────── */}
      <div className="grid grid-cols-2 gap-3 lg:grid-cols-4">
        {[
          {
            label: "候选池",
            value: report.candidates.length,
            icon: <Activity className="h-4 w-4 text-blue-400" />,
          },
          {
            label: "强候选",
            value: report.strong_candidates.length,
            icon: <Star className="h-4 w-4 text-yellow-400" />,
          },
          {
            label: "建议仓位",
            value: `${(report.total_suggested_position * 100).toFixed(0)}%`,
            icon: <TrendingUp className="h-4 w-4 text-green-400" />,
          },
          {
            label: "风险警告",
            value: report.warnings.length,
            icon: <ShieldAlert className="h-4 w-4 text-orange-400" />,
          },
        ].map((stat) => (
          <GlassCard key={stat.label} className="flex items-center gap-3 p-4">
            <div className="flex h-10 w-10 shrink-0 items-center justify-center rounded-full bg-white/5">
              {stat.icon}
            </div>
            <div>
              <p className="text-xs text-muted-foreground">{stat.label}</p>
              <p className="text-xl font-bold leading-tight">{stat.value}</p>
            </div>
          </GlassCard>
        ))}
      </div>

      {/* ── Risk Warnings Banner ─────────────────────────────────────── */}
      {report.warnings.length > 0 && (
        <GlassCard className="border-l-4 border-l-yellow-500 p-5">
          <div className="flex items-start gap-3">
            <ShieldAlert className="mt-0.5 h-5 w-5 shrink-0 text-yellow-500" />
            <div>
              <h4 className="font-semibold text-yellow-400">风险提示</h4>
              <ul className="mt-1 space-y-1">
                {report.warnings.map((w, i) => (
                  <li key={i} className="text-sm text-yellow-200/80">
                    • {w}
                  </li>
                ))}
              </ul>
            </div>
          </div>
        </GlassCard>
      )}

      {/* ── Candidate Pool Table ─────────────────────────────────────── */}
      <GlassCard glow className="p-5">
        <div className="mb-4 flex flex-wrap items-center justify-between gap-3">
          <h3 className="flex items-center gap-2 text-lg font-semibold">
            <TrendingUp className="h-5 w-5 text-primary" />
            候选池
          </h3>
          <Input
            placeholder="搜索代码或名称…"
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            className="max-w-[280px]"
          />
        </div>

        <div className="overflow-x-auto">
          <table className="w-full text-sm">
            <thead>
              <tr className="border-b border-border/40 text-left text-xs uppercase tracking-wider text-muted-foreground">
                <th className="pb-2 pr-4 pl-2">
                  <button
                    className="inline-flex items-center hover:text-foreground"
                    onClick={() => toggleSort("code")}
                  >
                    代码
                    <SortIcon field="code" />
                  </button>
                </th>
                <th className="pb-2 pr-4">
                  <button
                    className="inline-flex items-center hover:text-foreground"
                    onClick={() => toggleSort("name")}
                  >
                    名称
                    <SortIcon field="name" />
                  </button>
                </th>
                <th className="pb-2 pr-4 text-right">
                  <button
                    className="inline-flex items-center justify-end hover:text-foreground"
                    onClick={() => toggleSort("price")}
                  >
                    价格
                    <SortIcon field="price" />
                  </button>
                </th>
                <th className="pb-2 pr-4 text-right">
                  <button
                    className="inline-flex items-center justify-end hover:text-foreground"
                    onClick={() => toggleSort("change_pct")}
                  >
                    涨跌幅
                    <SortIcon field="change_pct" />
                  </button>
                </th>
                <th className="pb-2 pr-4 text-right">
                  <button
                    className="inline-flex items-center justify-end hover:text-foreground"
                    onClick={() => toggleSort("score")}
                  >
                    评分
                    <SortIcon field="score" />
                  </button>
                </th>
                <th className="pb-2 pr-2 w-10"></th>
              </tr>
            </thead>
            <tbody>
              {sortedCandidates.length === 0 ? (
                <tr>
                  <td colSpan={6} className="py-8 text-center text-muted-foreground">
                    无匹配结果
                  </td>
                </tr>
              ) : (
                sortedCandidates.map((c) => {
                  const strong = isStrong(String(c.code ?? ""), strongSet);
                  const changeColor =
                    (c.change_pct as number) >= 0 ? "text-green-400" : "text-red-400";
                  return (
                    <tr
                      key={String(c.code)}
                      className={`border-b border-border/20 transition-colors hover:bg-white/5 ${
                        strong ? "bg-yellow-500/5" : ""
                      }`}
                    >
                      <td className="pr-4 pl-2 py-2.5 font-mono text-xs text-primary">{c.code}</td>
                      <td className="pr-4 py-2.5 font-medium">{c.name}</td>
                      <td className="pr-4 py-2.5 text-right tabular-nums">
                        {c.price != null ? c.price.toFixed(2) : "-"}
                      </td>
                      <td className={`pr-4 py-2.5 text-right tabular-nums ${changeColor}`}>
                        {c.change_pct != null ? `${c.change_pct >= 0 ? "+" : ""}${c.change_pct.toFixed(2)}%` : "-"}
                      </td>
                      <td className="pr-4 py-2.5 text-right tabular-nums font-semibold">
                        {c.score != null ? c.score.toFixed(1) : "-"}
                      </td>
                      <td className="pr-2 py-2.5 text-right">
                        {strong && <Star className="ml-auto h-4 w-4 text-yellow-400 fill-yellow-400" />}
                      </td>
                    </tr>
                  );
                })
              )}
            </tbody>
          </table>
        </div>
        <p className="mt-2 text-xs text-muted-foreground">
          共 {sortedCandidates.length} 只（候选池 {report.candidates.length} 只，强候选 {report.strong_candidates.length} 只）
        </p>
      </GlassCard>

      {/* ── Strategy Matches ─────────────────────────────────────────── */}
      <GlassCard glow className="p-5">
        <h3 className="mb-4 flex items-center gap-2 text-lg font-semibold">
          <Activity className="h-5 w-5 text-primary" />
          战法匹配
        </h3>
        {report.strategy_matches.length === 0 ? (
          <p className="text-sm text-muted-foreground">暂无匹配战法</p>
        ) : (
          <div className="grid gap-3 sm:grid-cols-2">
            {report.strategy_matches.map((match, idx) => {
              const score = match.match_score ?? match.confidence ?? 0;
              const name = match.strategy_name || match.style || `战法 ${idx + 1}`;
              return (
                <div
                  key={idx}
                  className="rounded-xl border border-border/30 bg-white/[0.03] p-4 transition-colors hover:border-border/50"
                >
                  <div className="mb-2 flex items-center justify-between">
                    <span className="font-medium">{name}</span>
                    <Badge variant={score >= 0.7 ? "success" : score >= 0.4 ? "warning" : "default"}>
                      {(score * 100).toFixed(0)}%
                    </Badge>
                  </div>
                  <div className="mb-2 h-2 w-full overflow-hidden rounded-full bg-white/10">
                    <div
                      className="h-full rounded-full transition-all duration-500"
                      style={{
                        width: `${Math.min(100, score * 100)}%`,
                        backgroundColor:
                          score >= 0.7
                            ? "#22c55e"
                            : score >= 0.4
                              ? "#eab308"
                              : "#6b7280",
                      }}
                    />
                  </div>
                  {match.description && (
                    <p className="text-xs text-muted-foreground line-clamp-2">{match.description}</p>
                  )}
                </div>
              );
            })}
          </div>
        )}
      </GlassCard>

      {/* ── Position Suggestions ─────────────────────────────────────── */}
      <GlassCard glow className="p-5">
        <h3 className="mb-4 flex items-center gap-2 text-lg font-semibold">
          <TrendingUp className="h-5 w-5 text-primary" />
          仓位建议
        </h3>
        {report.position_suggestions.length === 0 ? (
          <p className="text-sm text-muted-foreground">暂无仓位建议</p>
        ) : (
          <div className="space-y-3">
            {report.position_suggestions.map((s, idx) => {
              const weight = s.suggested_weight ?? s.weight ?? 0;
              return (
                <div
                  key={idx}
                  className="flex items-start gap-4 rounded-xl border border-border/30 bg-white/[0.03] p-4 transition-colors hover:border-border/50"
                >
                  <div className="shrink-0 text-center">
                    <div className="text-2xl font-extrabold text-primary">{(weight * 100).toFixed(0)}%</div>
                    <div className="text-[10px] text-muted-foreground">权重</div>
                  </div>
                  <div className="min-w-0 flex-1">
                    <div className="flex items-center gap-2">
                      <span className="font-mono text-xs text-primary">{s.code}</span>
                      <span className="font-medium truncate">{s.name}</span>
                    </div>
                    {s.reason && (
                      <p className="mt-1 text-sm text-muted-foreground line-clamp-2">{s.reason}</p>
                    )}
                  </div>
                </div>
              );
            })}
          </div>
        )}
      </GlassCard>
    </div>
  );
}
