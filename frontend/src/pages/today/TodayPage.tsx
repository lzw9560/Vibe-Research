// Track B IA: /today — 今日动作队列（新 home，替 /market root redirect）
// 布局: PRIMARY 待办动作队列 + 次卡 大盘指数strip+自选快照 + 辅折叠 昨日复盘摘要 + CTA脊
// 数据源: useDateTriplet(时段)/useIndices(大盘)/apiWatchlist+useLiveQuotes(自选)/useBombAlerts(预警)
//        /useEvaluationSummary(§44)/useDailyWinReview(昨日复盘)
import { useQuery } from "@tanstack/react-query";
import { Link } from "react-router-dom";
import { AlertCircle, ChevronDown, RefreshCw } from "lucide-react";
import { useState } from "react";
import { GlassCard } from "@/components/ui/GlassCard";
import { PageHeader } from "@/components/ui/PageHeader";
import { NextStepBar } from "@/components/ui/NextStepBar";
import { useIndices, useDateTriplet, useDailyWinReview, useBombAlerts } from "@/lib/query";
import { useEvaluationSummary } from "@/lib/query/strategy";
import { apiWatchlist } from "@/lib/watchlist";
import { useLiveQuotes } from "@/hooks/useLiveQuotes";
import type { DimensionValidation } from "@/lib/candidates";
import { cn } from "@/lib/utils";

const STAGE_LABEL: Record<string, string> = {
  pre_market: "盘前",
  pre_open: "集合竞价",
  intraday: "盘中",
  post_transition: "收盘过渡",
  post_market: "盘后",
  non_trading: "非交易日",
};

export function TodayPage() {
  const { data: triplet } = useDateTriplet();
  const { data: indices, isLoading: idxLoading } = useIndices();
  const { data: evaluation } = useEvaluationSummary();
  const { data: winReview } = useDailyWinReview();
  const { data: bombAlerts } = useBombAlerts();

  // 自选股快照
  const { data: watchlistCodes } = useQuery({
    queryKey: ["watchlist", "codes"],
    queryFn: () => apiWatchlist.fetch(),
    staleTime: 60_000,
  });
  const topCodes = (watchlistCodes ?? []).slice(0, 5);
  const { quotes } = useLiveQuotes(topCodes, topCodes.length > 0);

  const [showReview, setShowReview] = useState(false);
  const stage = triplet?.stage ?? "pre_market";
  const stageLabel = STAGE_LABEL[stage] ?? "盘前";
  const today = triplet?.today ?? new Date().toISOString().slice(0, 10);

  // 待办动作队列
  const todos: { id: string; label: string; detail: string; link: string; badge?: string }[] = [];

  // ① 预警（炸板/价格）
  if (bombAlerts && bombAlerts.length > 0) {
    const alertCount = bombAlerts.length;
    todos.push({
      id: "alerts",
      label: "预警",
      detail: `${alertCount} 只预警（炸板/价格异动）`,
      link: "/workspace?phase=intraday",
      badge: "查看",
    });
  }

  // ② 盘前候选就绪
  todos.push({
    id: "premarket",
    label: "盘前候选就绪",
    detail: "breakout 候选 (§44 lift 1.4x 待验证)",
    link: "/workspace?phase=premarket",
    badge: "选股",
  });

  // ③ §44 待复验
  if (evaluation && evaluation.dimensions) {
    const pending = evaluation.dimensions.filter((d: DimensionValidation) => d.status.includes("待复验") || d.status.includes("探索"));
    if (pending.length > 0) {
      todos.push({
        id: "s44",
        label: "§44 待复验",
        detail: `${pending.length} 项维度待 60 天复验`,
        link: "/review?tab=backtest",
        badge: "查看",
      });
    }
  }

  // ④ 待平仓日志桩
  todos.push({
    id: "journal",
    label: "待平仓日志桩",
    detail: "昨买标的到止盈位，待记卖出",
    link: "/ledger?tab=journal",
    badge: "记日志",
  });

  // 预警
  const alertCount = bombAlerts?.length ?? 0;

  return (
    <div>
      <PageHeader
        title="今日"
        subtitle={`${today} · ${stageLabel}${triplet?.is_trading_day ? "" : " · 非交易日"}`}
        actions={<RefreshCw className="h-4 w-4 text-muted-foreground" />}
      />

      {/* PRIMARY: 待办动作队列 */}
      <GlassCard tier="primary" className="mb-4">
        <div className="mb-3 flex items-center justify-between">
          <h2 className="text-sm font-semibold">待办动作队列</h2>
          {alertCount > 0 && (
            <span className="inline-flex items-center gap-1 text-xs text-red-500">
              <AlertCircle className="h-3.5 w-3.5" />
              {alertCount} 预警
            </span>
          )}
        </div>
        <div className="space-y-2">
          {todos.map((todo, i) => (
            <Link
              key={todo.id}
              to={todo.link}
              className="flex items-center gap-3 rounded-lg border border-border/50 bg-muted/20 px-3 py-2.5 transition-colors hover:border-primary/30 hover:bg-muted/40"
            >
              <span className="flex h-6 w-6 shrink-0 items-center justify-center rounded-full bg-primary/10 text-xs font-medium text-primary">
                {i + 1}
              </span>
              <div className="min-w-0 flex-1">
                <div className="text-sm font-medium">{todo.label}</div>
                <div className="text-xs text-muted-foreground">{todo.detail}</div>
              </div>
              {todo.badge && (
                <span className="shrink-0 text-xs text-primary">{todo.badge} →</span>
              )}
            </Link>
          ))}
        </div>
      </GlassCard>

      {/* 次卡1: 大盘指数 strip */}
      <div className="mb-4">
        <GlassCard className="py-3">
          <div className="flex flex-wrap items-center gap-x-6 gap-y-1">
            <span className="text-xs font-medium text-muted-foreground">大盘</span>
            {idxLoading ? (
              <span className="text-xs text-muted-foreground">加载中…</span>
            ) : indices && indices.length > 0 ? (
              indices.slice(0, 6).map(idx => (
                <span key={idx.name} className="inline-flex items-center gap-1 text-sm">
                  <span className="text-muted-foreground">{idx.name}</span>
                  <span className={cn(
                    "font-mono font-medium",
                    idx.change_pct >= 0 ? "text-red-500" : "text-green-500",
                  )}>
                    {idx.change_pct >= 0 ? "+" : ""}{idx.change_pct.toFixed(2)}%
                  </span>
                </span>
              ))
            ) : (
              <span className="text-xs text-muted-foreground">—</span>
            )}
            <Link to="/market" className="ml-auto text-xs text-primary">市场全景 →</Link>
          </div>
        </GlassCard>
      </div>

      {/* 次卡2: 自选快照 */}
      <div className="mb-4">
        <GlassCard>
          <div className="mb-2 flex items-center justify-between">
            <h3 className="text-sm font-semibold">我的自选快照</h3>
            <Link to="/watchlist" className="text-xs text-primary">全部 →</Link>
          </div>
          {topCodes.length > 0 && quotes ? (
            <div className="grid grid-cols-2 gap-2 sm:grid-cols-3 lg:grid-cols-5">
              {topCodes.map(code => {
                const q = quotes[code];
                const pct = q?.change_pct ?? 0;
                return (
                  <Link
                    key={code}
                    to={`/stock/${code}`}
                    className="rounded-lg border border-border/30 bg-muted/10 px-2.5 py-2 transition-colors hover:border-primary/30"
                  >
                    <div className="text-xs text-muted-foreground">{code}</div>
                    <div className={cn(
                      "text-sm font-mono font-medium",
                      pct >= 0 ? "text-red-500" : "text-green-500",
                    )}>
                      {pct >= 0 ? "+" : ""}{pct.toFixed(2)}%
                    </div>
                  </Link>
                );
              })}
            </div>
          ) : (
            <p className="text-xs text-muted-foreground">暂无自选股，<Link to="/screener" className="text-primary">去选股 →</Link></p>
          )}
        </GlassCard>
      </div>

      {/* 辅折叠: 昨日复盘摘要 */}
      <div className="mb-2">
        <button
          onClick={() => setShowReview(!showReview)}
          className="flex w-full items-center gap-2 text-xs text-muted-foreground transition-colors hover:text-foreground"
        >
          <ChevronDown className={cn("h-3.5 w-3.5 transition-transform", showReview && "rotate-180")} />
          昨日复盘摘要
        </button>
        {showReview && (
          <div className="mt-2">
            <GlassCard tier="sub">
              {winReview ? (
                <p className="text-xs text-muted-foreground">
                  {`推荐 ${winReview.pushed?.length ?? 0} / 买入 ${winReview.bought?.length ?? 0} / 漏掉 ${winReview.missed?.length ?? 0}`}
                  <Link to="/review" className="ml-2 text-primary">去复盘 →</Link>
                </p>
              ) : (
                <p className="text-xs text-muted-foreground">复盘数据待累积 · <Link to="/review" className="text-primary">去复盘 →</Link></p>
              )}
            </GlassCard>
          </div>
        )}
      </div>

      {/* CTA 脊 */}
      <NextStepBar pageCtx="today" />
    </div>
  );
}
