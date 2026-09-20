// 多维度 IA: /today — 时间线（今日 hub）
// 时段感知: useDateTriplet stage 驱动（晚上=复盘+T+1备 / 盘前=T+1选 / 盘中=实时）
// 7 状态灯汇总（5线+风控+数据）+ 时间线闭环卡 + 动作队列 + 大盘/自选快照
// focus 日 T-1/T/T+1 切（借 useDateTriplet）
import { useQuery } from "@tanstack/react-query";
import { Link } from "react-router-dom";
import { AlertCircle, ChevronDown, Clock, Telescope } from "lucide-react";
import { useState } from "react";
import { GlassCard } from "@/components/ui/GlassCard";
import { PageHeader } from "@/components/ui/PageHeader";
import { NextStepBar } from "@/components/ui/NextStepBar";
import { FocusDayStrip } from "@/components/ui/FocusDayStrip";
import { SeatRankingBoard } from "@/components/seat/SeatRankingBoard";
import { useCommandPalette } from "@/components/command-palette/useCommandPalette";
import { useFocusDay } from "@/stores/focusDay";
import { useIndices, useDateTriplet, useDailyWinReview, useBombAlerts, useScheduledTasks } from "@/lib/query";
import { useEvaluationSummary } from "@/lib/query/strategy";
import { useStrategyBacktest } from "@/lib/query/strategy";
import { apiWatchlist } from "@/lib/watchlist";
import { useLiveQuotes, isTradingHours } from "@/hooks/useLiveQuotes";
import type { DimensionValidation } from "@/lib/candidates";
import { SevenLineStatus } from "@/components/lines/SevenLineStatus";
import { LineLoopCard } from "@/components/lines/LineLoopCard";
import { CrossLineDrawer } from "@/components/lines/CrossLineDrawer";
import { LINES, buildSevenLineItems } from "@/components/lines/lines";
import type { LineStatus } from "@/components/lines/LineStatusLight";
import { cn } from "@/lib/utils";

const STAGE_LABEL: Record<string, string> = {
  pre_market: "盘前",
  pre_open: "集合竞价",
  intraday: "盘中",
  post_transition: "收盘过渡",
  post_market: "盘后",
  non_trading: "非交易日",
};

// 时段→动作映射（时段感知核心）
function stageActions(stage: string): { focus: string; hint: string }[] {
  switch (stage) {
    case "pre_market":
      return [
        { focus: "T+1 选股", hint: "盘前候选就绪，切盘面选股" },
        { focus: "竞价监控", hint: "9:15 竞价开始" },
      ];
    case "pre_open":
      return [
        { focus: "竞价监控", hint: "集合竞价中，看竞价异常" },
        { focus: "切盘中", hint: "9:30 开盘切盘中盯盘" },
      ];
    case "intraday":
      return [
        { focus: "盘中盯盘", hint: "自选 live + 预警" },
        { focus: "信号触发", hint: "信号触发记日志待 §44" },
      ];
    case "post_transition":
    case "post_market":
      return [
        { focus: "收盘复盘", hint: "查今日战绩 + §44 verdict" },
        { focus: "T+1 备", hint: "明日军备 + 选股" },
      ];
    default:
      return [
        { focus: "T+1 选股", hint: "非交易日，可提前选股备军" },
      ];
  }
}

export function TodayPage() {
  const { focusDate } = useFocusDay();
  const { open: openPalette } = useCommandPalette();
  const { data: triplet } = useDateTriplet(focusDate ?? undefined);
  const { data: indices, isLoading: idxLoading } = useIndices({
    refetchInterval: () => (isTradingHours() ? 5000 : false),
  });
  const { data: evaluation } = useEvaluationSummary();
  const { data: winReview } = useDailyWinReview();
  const { data: bombAlerts } = useBombAlerts();
  const { data: backtest } = useStrategyBacktest(60);
  const { data: tasks } = useScheduledTasks();

  // 自选股快照
  const { data: watchlistCodes } = useQuery({
    queryKey: ["watchlist", "codes"],
    queryFn: () => apiWatchlist.fetch(),
    staleTime: 60_000,
  });
  const topCodes = (watchlistCodes ?? []).slice(0, 5);
  const { quotes } = useLiveQuotes(topCodes, topCodes.length > 0);

  const [showReview, setShowReview] = useState(false);
  const [drawerCode, setDrawerCode] = useState<string | null>(null);
  const stage = triplet?.stage ?? "pre_market";
  const stageLabel = STAGE_LABEL[stage] ?? "盘前";
  const today = triplet?.today ?? new Date().toISOString().slice(0, 10);

  // ── 七灯 status 计算 ──
  const isTradingDay = triplet?.is_trading_day ?? false;
  const timeStatus: LineStatus = isTradingDay ? "ok" : "idle";

  const watchCount = watchlistCodes?.length ?? 0;
  const selectionStatus: LineStatus = watchCount > 0 ? "ok" : "pending";

  const pendingDims = evaluation?.dimensions?.filter(
    (d: DimensionValidation) => d.status.includes("待复验") || d.status.includes("探索"),
  ) ?? [];
  const validationStatus: LineStatus =
    pendingDims.length > 0 ? "pending" : evaluation?.dimensions?.length ? "ok" : "idle";

  const strategyStatus: LineStatus =
    backtest && backtest.length > 0 ? "ok" : "idle";

  // 认知线: 无直接 endpoint → idle（honest，标待接线）
  const cognitionStatus: LineStatus = "idle";

  const alertCount = bombAlerts?.length ?? 0;
  const riskStatus: LineStatus = alertCount > 0 ? "alert" : "ok";

  const taskList = tasks ?? [];
  const failedTasks = taskList.filter(t => t.last_run_status === "failed");
  const dataStatus: LineStatus = failedTasks.length > 0 ? "alert" : taskList.length > 0 ? "ok" : "idle";

  const sevenItems = buildSevenLineItems(
    {
      time: timeStatus,
      selection: selectionStatus,
      validation: validationStatus,
      strategy: strategyStatus,
      cognition: cognitionStatus,
      risk: riskStatus,
      data: dataStatus,
    },
    {
      time: stageLabel,
      selection: watchCount > 0 ? `${watchCount} 自选` : "去选股",
      validation: pendingDims.length > 0 ? `${pendingDims.length} 待复验` : undefined,
      strategy: backtest?.length ? `${backtest.length} 战法` : undefined,
      cognition: "待接线",
      risk: alertCount > 0 ? `${alertCount} 预警` : undefined,
      data: failedTasks.length > 0 ? `${failedTasks.length} 失败` : undefined,
    },
  );

  // 时间线步骤环
  const timeLine = LINES[0];
  const stageActionsList = stageActions(stage);

  // 待办动作队列
  const todos: { id: string; label: string; detail: string; link: string; badge?: string }[] = [];

  // 时段感知动作
  stageActionsList.forEach((a, i) => {
    todos.push({
      id: `stage-${i}`,
      label: a.focus,
      detail: a.hint,
      link: a.focus.includes("选股") ? "/workspace?phase=premarket"
        : a.focus.includes("竞价") ? "/bidding"
        : a.focus.includes("盯盘") ? "/workspace?phase=intraday"
        : a.focus.includes("复盘") ? "/review"
        : "/today",
      badge: "前往",
    });
  });

  // 预警
  if (alertCount > 0) {
    todos.push({
      id: "alerts",
      label: "预警",
      detail: `${alertCount} 只预警（炸板/价格异动）`,
      link: "/workspace?phase=intraday",
      badge: "查看",
    });
  }

  // §44 待复验
  if (pendingDims.length > 0) {
    todos.push({
      id: "s44",
      label: "§44 待复验",
      detail: `${pendingDims.length} 项维度待 60 天复验`,
      link: "/review?tab=validation",
      badge: "查看",
    });
  }

  // Track E A8: 因子→§44 verdict 直达（始终可达，非仅 pending 时）
  todos.push({
    id: "s44-verdict",
    label: "查 §44 verdict",
    detail: "因子 verdict 全量表（lift / 状态 / 降权 / edge-type）",
    link: "/review?tab=validation",
    badge: "查看",
  });

  return (
    <div>
      <PageHeader
        title="今日"
        subtitle={`${today} · ${stageLabel}${isTradingDay ? "" : " · 非交易日"}`}
        actions={
          <div className="flex items-center gap-3">
            {/* focus 日 T-1/T/T+1 切（全局，跨页跟切重拉） */}
            <FocusDayStrip />
            <button
              onClick={openPalette}
              className="inline-flex items-center gap-1 rounded-lg border border-border/50 px-2.5 py-1 text-xs text-muted-foreground transition-colors hover:border-primary/30 hover:text-primary"
              title="研究深挖（Cmd+K / Ctrl+K）"
            >
              <Telescope className="h-3.5 w-3.5" />
              研究深挖
              <kbd className="rounded border border-border/40 px-1 text-[9px]">⌘K</kbd>
            </button>
          </div>
        }
      />

      {/* 七灯汇总 */}
      <SevenLineStatus items={sevenItems} />

      {/* 时间线闭环卡 */}
      <div className="mb-4">
        <LineLoopCard
          title="时间线闭环"
          subtitle="盘前→竞价→盘中→收盘复盘→T+1备→(loop)"
          steps={timeLine.steps}
          currentStep={stage === "pre_market" ? 0 : stage === "pre_open" ? 1 : stage === "intraday" ? 2 : 3}
          icon={<Clock className="h-3.5 w-3.5 text-muted-foreground" />}
        />
      </div>

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

      {/* M1 盘后榜：盘后 phase 显今日龙虎榜净买入排名（cross-cutting 席位 view） */}
      {(stage === "post_market" || stage === "post_transition") && (
        <div className="mb-4">
          <SeatRankingBoard />
        </div>
      )}

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
                  <div
                    key={code}
                    className="rounded-lg border border-border/30 bg-muted/10 px-2.5 py-2 transition-colors hover:border-primary/30"
                  >
                    <div className="flex items-center justify-between">
                      <Link to={`/stock/${code}`} className="text-xs text-muted-foreground hover:text-primary">{code}</Link>
                      <button
                        onClick={() => setDrawerCode(code)}
                        className="text-[10px] text-primary/60 hover:text-primary"
                        title="跨线视图"
                      >⇄</button>
                    </div>
                    <div className={cn(
                      "text-sm font-mono font-medium",
                      pct >= 0 ? "text-red-500" : "text-green-500",
                    )}>
                      {pct >= 0 ? "+" : ""}{pct.toFixed(2)}%
                    </div>
                  </div>
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

      {/* 跨线 drawer */}
      <CrossLineDrawer
        open={drawerCode !== null}
        onClose={() => setDrawerCode(null)}
        stockCode={drawerCode}
      />
    </div>
  );
}
