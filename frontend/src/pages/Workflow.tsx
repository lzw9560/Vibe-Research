// S075 065-066：选股工作流首页——卡片入口布局。
// 原"盘前/盘中/盘后 三阶段状态机看板"降级为 workflow 卡片的展开子视图（不删能力，仅改入口形态）。
// 战法流入口：首板流✅ 已实现 / 连板流·炸板回交流·低吸流·反包流·N字反击流 灰显待实现。
// §44 诚实标注：首板流卡片标注"§44未validated仅参考"。
import { useMemo, useState } from "react";
import { Link, useSearchParams } from "react-router-dom";
import {
  Clock, TrendingUp, BarChart3, ChevronRight, RefreshCw, Flame,
  ArrowRight, Activity, Zap, Share2, Layers, Sparkles, Lock,
} from "lucide-react";
import { cn } from "@/lib/utils";
import { PageHeader } from "@/components/ui/PageHeader";
import { GlassCard } from "@/components/ui/GlassCard";
import { Button } from "@/components/ui/Button";
import { Badge } from "@/components/ui/Badge";
import { Skeleton } from "@/components/ui/Skeleton";
import { Disclaimer } from "@/components/ui/Disclaimer";
import { AskAiButton } from "@/components/ui/AskAiButton";
import { PipelineProgressBar } from "@/components/workflow/PipelineProgressBar";
// S072：WeatherDecisionBar 移出工作流首页（天气无 §44 edge，留 PostMarketReview 复盘）
import {
  useWorkflowStatus, usePreMarketBriefing, usePreMarketDates, useWorkflowStates,
  useFirstBoardCandidates,
} from "@/lib/query";

// ---- 类型定义 ----
interface WorkflowStatus {
  stageKey: string;
  stageLabel: string;
  currentTime: string;
  marketStatus: string;
  nextStageKey: string | null;
  nextStageTime: string | null;
  candidateCount: number;
  signalCount: number;
  alertCount: number;
  winRate: number;
}

// ---- 工具函数 ----
// 阶段/时间唯一源 = 后端 /api/workflow/status（get_current_stage：北京 tz + is_trading_day 节假日）。
// 原本地 getAStockTimeInfo（浏览器 tz、仅周末、无节假日）是 drift 源，task 117 移除——
// useMemo 直接取 backend.stage/market_status/next_stage/next_stage_time/current_time。

/** stageKey → PipelineProgressBar current 映射 */
function stageToPipeline(stageKey: string): "t1" | "ctx" | "pre" | "intraday" | "post" {
  if (stageKey === "pre-market") return "pre";
  if (stageKey === "intraday") return "intraday";
  return "post";
}

/** 计算距离下一个阶段的分钟数（task 122：用后端 current_time 北京 tz，非浏览器 new Date） */
function countDownToNext(stageKey: string, currentTime: string): string {
  // currentTime="HH:MM"（后端北京 tz）；缺 backend 时间 → 无法算，返 "--"（不回退浏览器 tz）。
  const parts = (currentTime || "").split(":");
  if (parts.length < 2) return "--";
  const nowMin = Number(parts[0]) * 60 + Number(parts[1]);
  if (Number.isNaN(nowMin)) return "--";

  let targetMin: number;
  if (stageKey === "pre-market") {
    targetMin = 9 * 60 + 30;        // 09:30（盘前结束→盘中开始）
  } else if (stageKey === "intraday") {
    targetMin = 15 * 60;            // 15:00（盘中结束→盘后开始）
  } else {
    targetMin = 8 * 60 + 24 * 60;   // 次日 08:00（盘后结束→次日盘前）
  }

  let diff = targetMin - nowMin;
  if (stageKey === "post-market") {
    if (diff <= 0) diff += 24 * 60;  // 兜底（盘后当前 <22:00 < 次日 08:00，diff>0）
  } else if (diff <= 0) {
    return "即将开始";
  }
  const hours = Math.floor(diff / 60);
  const mins = diff % 60;
  if (hours > 0) return `${hours}小时${mins}分`;
  return `${mins}分钟`;
}

// ---- 阶段配置（原状态机看板用）----
const STAGE_CONFIG: Record<string, {
  icon: React.ComponentType<{ className?: string }>;
  color: string;
  bg: string;
  border: string;
  label: string;
  timeRange: string;
  description: string;
  steps: string[];
  links: { to: string; label: string }[];
}> = {
  "pre-market": {
    icon: Clock,
    color: "text-blue-400",
    bg: "bg-blue-500/10",
    border: "border-blue-500/30",
    label: "盘前简报",
    timeRange: "08:00 - 09:30",
    description: "候选池筛选 → 战法匹配 → 仓位建议",
    steps: ["候选池筛选", "战法匹配", "仓位建议", "推送准备"],
    links: [
      { to: "/workflow/pre-market", label: "盘前简报" },
      { to: "/limitup/gene", label: "基因选股" },
      { to: "/limitup/auction", label: "竞价预案" },
    ],
  },
  "intraday": {
    icon: TrendingUp,
    color: "text-green-400",
    bg: "bg-green-500/10",
    border: "border-green-500/30",
    label: "盘中监控",
    timeRange: "09:30 - 15:00",
    description: "实时监控 → 炸板预警 → 动态调仓",
    steps: ["实时监控", "炸板预警", "动态调仓", "止盈止损"],
    links: [
      { to: "/workflow/intraday", label: "盘中监控" },
      { to: "/workflow/alerts", label: "炸板预警" },
      { to: "/sentiment/weather", label: "情绪气象" },
      { to: "/limitup/seats", label: "席位引擎" },
    ],
  },
  "post-market": {
    icon: BarChart3,
    color: "text-purple-400",
    bg: "bg-purple-500/10",
    border: "border-purple-500/30",
    label: "盘后复盘",
    timeRange: "15:00 - 22:00",
    description: "自动结算 → LLM复盘 → 胜率更新",
    steps: ["自动结算", "LLM复盘", "胜率更新", "参数优化"],
    links: [
      { to: "/workflow/post-market", label: "盘后复盘" },
      { to: "/daily-review", label: "每日复盘" },
      { to: "/metrics", label: "性能监控" },
    ],
  },
};

const STAGE_ORDER = ["pre-market", "intraday", "post-market"];

// ---- 阶段步骤项 ----
function StepItem({ label, index, isActive, isPast }: { label: string; index: number; isActive: boolean; isPast: boolean }) {
  return (
    <div className={cn(
      "flex items-center gap-3 text-sm transition-opacity",
      !isActive && !isPast && "opacity-40",
    )}>
      {/* 序号 */}
      <div className={cn(
        "flex h-6 w-6 shrink-0 items-center justify-center rounded-full text-xs font-medium",
        isPast ? "bg-emerald-500/20 text-emerald-400" : isActive ? "bg-primary/20 text-primary" : "bg-muted/20 text-muted-foreground/50",
      )}>
        {isPast ? "✓" : index + 1}
      </div>
      <span className={cn(
        "transition-colors",
        isPast ? "text-emerald-300/70 line-through" : isActive ? "text-foreground font-medium" : "text-muted-foreground/50",
      )}>
        {label}
      </span>
    </div>
  );
}

// ---- 阶段卡片（降级视图用）----
function StageCard({
  stageKey,
  isActive,
  isPast,
  status,
  histValue,
  selectedDate,
}: {
  stageKey: string;
  isActive: boolean;
  isPast: boolean;
  status: WorkflowStatus | null;
  histValue?: number | null;
  selectedDate?: string;
}) {
  const config = STAGE_CONFIG[stageKey];
  const Icon = config.icon;
  const countdown = !isPast ? countDownToNext(stageKey, status?.currentTime ?? "") : null;

  // 该阶段的统计数据
  const stats: Record<string, { label: string; value: string | number; icon: React.ComponentType<{ className?: string }> }> = {
    "pre-market": {
      label: "候选池",
      value: status?.candidateCount ?? 0,
      icon: Flame,
    },
    "intraday": {
      label: "活跃信号",
      value: status?.signalCount ?? 0,
      icon: Zap,
    },
    "post-market": {
      label: "今日胜率",
      value: status?.winRate != null ? `${status.winRate}%` : "--",
      icon: BarChart3,
    },
  };
  const base = stats[stageKey];
  const stat = histValue !== undefined
    ? { label: base.label, value: histValue ?? "--", icon: base.icon }
    : base;

  return (
    <GlassCard
      glow={isActive}
      className={cn(
        "p-5 transition-all",
        isActive && "ring-2 ring-primary/30 scale-[1.02]",
        isPast && "opacity-60",
      )}
    >
      {/* 头部 */}
      <div className="flex items-start justify-between mb-4">
        <div className="flex items-center gap-3">
          <div className={cn("p-2.5 rounded-xl", config.bg, config.border, "border")}>
            <Icon className={cn("h-5 w-5", config.color)} />
          </div>
          <div>
            <div className="flex items-center gap-2">
              <h3 className="font-semibold">{config.label}</h3>
              {isActive && <Badge variant="primary">进行中</Badge>}
              {isPast && <Badge variant="success">已完成</Badge>}
            </div>
            <p className="text-xs text-muted-foreground/60 mt-0.5">{config.timeRange}</p>
          </div>
        </div>

        {/* 倒计时 */}
        {!isActive && !isPast && countdown && (
          <div className="text-right">
            <p className="text-[10px] text-muted-foreground/40 uppercase tracking-wider">开始于</p>
            <p className="text-sm font-mono text-muted-foreground">{countdown}</p>
          </div>
        )}
      </div>

      {/* 描述 */}
      <p className="text-sm text-muted-foreground/70 mb-4">{config.description}</p>

      {/* 步骤列表 */}
      <div className="space-y-2 mb-4">
        {config.steps.map((step, i) => (
          <StepItem
            key={step}
            label={step}
            index={i}
            isActive={isActive && i === 0}
            isPast={isPast}
          />
        ))}
      </div>

      {/* 统计指标 */}
      {stat && (
        <div className={cn(
          "rounded-lg p-3 mb-4",
          isPast ? "bg-muted/10" : isActive ? config.bg : "bg-muted/5",
        )}>
          <div className="flex items-center gap-2">
            <stat.icon className={cn("h-4 w-4", isPast ? "text-muted-foreground/40" : config.color)} />
            <span className="text-xs text-muted-foreground/60">{stat.label}</span>
            <span className={cn(
              "ml-auto text-lg font-bold font-mono",
              isPast ? "text-muted-foreground/30" : "text-foreground",
            )}>
              {stat.value}
            </span>
          </div>
        </div>
      )}

      {/* 快捷链接 */}
      <div className="flex flex-wrap gap-2">
        {config.links.map((link, i) => (
          <Link key={`${link.to}-${i}`} to={selectedDate ? `${link.to}?date=${selectedDate}` : link.to}>
            <Button variant="ghost" size="sm" className={cn(
              "text-xs",
              isActive ? config.color : "text-muted-foreground/60",
            )}>
              {link.label}
              <ArrowRight className="ml-1 h-3 w-3" />
            </Button>
          </Link>
        ))}
      </div>
    </GlassCard>
  );
}

// ============================================================================
// S075 065-066：战法流入口卡片
// ============================================================================

interface StrategyFlowCardProps {
  title: string;
  subtitle: string;
  icon: React.ComponentType<{ className?: string }>;
  to?: string;                          // 可点击跳转的路径；undefined=待实现灰显
  implemented: boolean;
  badge?: string;                        // 状态徽标文案（如"候选 91 只"）
  badges?: { text: string; variant?: "default" | "primary" | "success" | "warning" | "info" }[];
  footnote?: string;                      // §44 标注 / "待 S055" / "待实现" 等
  dimReason?: string;                     // 未实现的降级原因
}

function StrategyFlowCard({
  title, subtitle, icon: Icon, to, implemented, badge, badges, footnote, dimReason,
}: StrategyFlowCardProps) {
  const content = (
    <GlassCard
      glow={implemented}
      className={cn(
        "p-5 h-full transition-all",
        implemented
          ? "ring-1 ring-primary/20 hover:ring-2 hover:ring-primary/40 hover:-translate-y-0.5"
          : "opacity-60 cursor-not-allowed",
      )}
    >
      <div className="flex items-start justify-between mb-3">
        <div className={cn(
          "p-2.5 rounded-xl border",
          implemented
            ? "bg-primary/10 border-primary/30"
            : "bg-muted/20 border-border/40",
        )}>
          <Icon className={cn("h-5 w-5", implemented ? "text-primary" : "text-muted-foreground/50")} />
        </div>
        {implemented ? (
          <Badge variant="success">✅ 已实现</Badge>
        ) : (
          <Badge variant="default">
            <Lock className="mr-1 h-2.5 w-2.5" />
            待实现
          </Badge>
        )}
      </div>

      <h3 className={cn(
        "font-semibold mb-1",
        implemented ? "text-foreground" : "text-muted-foreground/70",
      )}>
        {title}
      </h3>
      <p className="text-xs text-muted-foreground/70 mb-3">{subtitle}</p>

      {/* 状态徽章 */}
      {badges && badges.length > 0 && (
        <div className="flex flex-wrap gap-1.5 mb-3">
          {badges.map((b, i) => (
            <Badge key={i} variant={b.variant ?? "default"}>{b.text}</Badge>
          ))}
        </div>
      )}
      {badge && (
        <div className="mb-3">
          <Badge variant="primary">{badge}</Badge>
        </div>
      )}

      {/* 脚注 */}
      {footnote && (
        <p className={cn(
          "text-[11px] leading-relaxed",
          implemented ? "text-amber-200/70" : "text-muted-foreground/40",
        )}>
          {footnote}
        </p>
      )}
      {dimReason && !implemented && (
        <p className="text-[11px] text-muted-foreground/40 mt-2">{dimReason}</p>
      )}

      {/* 跳转箭头 */}
      {implemented && to && (
        <div className="mt-3 flex items-center gap-1 text-xs text-primary">
          <span>进入工作流</span>
          <ArrowRight className="h-3 w-3" />
        </div>
      )}
    </GlassCard>
  );

  if (!implemented || !to) return content;
  return <Link to={to} className="block h-full">{content}</Link>;
}

// ============================================================================
// 主页面
// ============================================================================

export default function Workflow() {
  // S048 R2：顶级日期选择——?date= 存在即历史视角（不带参数=今日实时，现状不变）
  const [searchParams, setSearchParams] = useSearchParams();
  const selectedDate = searchParams.get("date");
  const isHistorical = !!selectedDate;

  // S075 065：默认显示卡片入口；点 workflow 降级入口卡片切到原状态机看板
  const [view, setView] = useState<"entries" | "legacy-state-machine">("entries");

  // S048 R3：历史视角数据源——盘前卡读快照候选数，盘中/盘后卡读该日状态计数
  const { data: histBriefing } = usePreMarketBriefing(selectedDate ?? undefined);
  const { data: histStates } = useWorkflowStates(selectedDate ?? undefined);
  // I1：有快照的日期列表（日期选择器标注）
  const { data: datesData } = usePreMarketDates();

  // 首板流候选池（卡片入口状态徽章用）——未实现日期兜底取最近交易日
  const { data: firstBoardData, isLoading: fbLoading } = useFirstBoardCandidates(selectedDate ?? undefined);

  // T9：原 useState/useEffect + setInterval(60s) + getWorkflowStatus() → useWorkflowStatus + refetchInterval。
  const { data: backend, isLoading: loading, isFetching, refetch } = useWorkflowStatus({
    refetchInterval: isHistorical ? false : 60_000,
  });
  const refreshing = isFetching && !loading;

  const status = useMemo<WorkflowStatus | null>(() => {
    // 后端字段名容错（candidate_count / candidate_pool_count 等多别名）
    const candidateCount = (backend?.candidate_count as number) ?? (backend?.candidate_pool_count as number) ?? 0;
    const signalCount = (backend?.signal_count as number) ?? (backend?.active_signals as number) ?? 0;
    const alertCount = (backend?.alert_count as number) ?? 0;
    const winRate = (backend?.win_rate as number) ?? (backend?.today_win_rate as number) ?? 0;

    const stageKey = (backend?.stage as string) ?? "pre-market";
    const marketStatus = (backend?.market_status as string) ?? "加载中";
    const nextStageKey = (backend?.next_stage as string | null) ?? null;
    const nextStageTime = (backend?.next_stage_time as string | null) ?? null;
    const currentTime = (backend?.current_time as string) ?? "";

    return {
      stageKey,
      stageLabel: STAGE_CONFIG[stageKey]?.label ?? "",
      currentTime,
      marketStatus,
      nextStageKey,
      nextStageTime,
      candidateCount,
      signalCount,
      alertCount,
      winRate,
    };
  }, [backend]);

  const handleRefresh = () => {
    refetch();
  };

  // 当前阶段
  const currentStage = status?.stageKey ?? "pre-market";

  // S065 followup：问 AI 上下文——注入本页真实数据
  const ctx = histBriefing?.sentiment_context;
  const counts = histStates?.counts ?? {};
  const askAiContext = [
    `当前页面：选股工作流首页`,
    `视图模式：${view === "entries" ? "卡片入口" : "状态机看板（降级）"}`,
    `当前阶段：${STAGE_CONFIG[status?.stageKey ?? "pre-market"]?.label ?? ""}（${status?.marketStatus ?? ""}）`,
    `候选数：${status?.candidateCount ?? 0}，活跃信号：${status?.signalCount ?? 0}，今日胜率：${status?.winRate ?? "--"}%`,
    ctx?.fuse_state
      ? `熔断：${ctx.fuse_state.fuse_state}，允许战法：${(ctx.allowed_styles ?? []).join("、") || "无"}，禁用：${(ctx.forbidden_styles ?? []).join("、") || "无"}`
      : `熔断：未取得`,
    `工作流状态计数：候选${counts.candidate ?? 0}/观察${counts.watching ?? 0}/监控${counts.monitoring ?? 0}/持仓${counts.holding ?? 0}/已结${counts.settled ?? 0}`,
    firstBoardData
      ? `首板流：涨停池${firstBoardData.zt_pool_count}/首板${firstBoardData.first_board_count}/候选${firstBoardData.candidates.length}/${firstBoardData.note}`
      : `首板流：未取得`,
    status?.nextStageKey
      ? `下一阶段：${STAGE_CONFIG[status.nextStageKey]?.label ?? ""}（${countDownToNext(status.nextStageKey, status.currentTime ?? "")}）`
      : "",
  ].filter(Boolean).join("\n");

  // S048 R3：历史视角三卡数值（无数据 null → 渲染 "--"）
  const histValues: Record<string, number | null> = {
    "pre-market": histBriefing?.status === "done"
      ? (histBriefing.factors ?? []).reduce((n, f) => n + (f.candidates?.length ?? 0), 0)
      : null,
    "intraday": histStates?.counts?.monitoring ?? null,
    "post-market": histStates?.counts?.settled ?? null,
  };

  // S048 R2：日期切换——写 URL query，子页链接同携 date
  const handleDateChange = (value: string) => {
    if (!value) return;
    setSearchParams((prev) => {
      const next = new URLSearchParams(prev);
      next.set("date", value);
      return next;
    });
  };
  const clearDate = () => {
    setSearchParams((prev) => {
      const next = new URLSearchParams(prev);
      next.delete("date");
      return next;
    });
  };

  // ---- 卡片入口视图 ----
  if (view === "entries") {
    // 首板流卡片状态徽章——候选数来自 first-board/candidates；已建仓/T+1卖出来自 workflow_state counts
    const fbCandidates = firstBoardData?.candidates.length;
    const holdingCount = counts.holding ?? 0;
    const settledCount = counts.settled ?? 0;
    const fbBadges = fbLoading
      ? [{ text: "加载中…", variant: "default" as const }]
      : firstBoardData
        ? [
            { text: `候选 ${fbCandidates ?? 0} 只`, variant: "primary" as const },
            { text: `已建仓 ${holdingCount} 只`, variant: holdingCount > 0 ? "success" as const : "default" as const },
            { text: `T+1 卖出 ${settledCount} 只`, variant: settledCount > 0 ? "info" as const : "default" as const },
          ]
        : [{ text: "数据未取得", variant: "default" as const }];

    return (
      <div className="space-y-6">
        <PageHeader
          title="选股工作流"
          subtitle="战法流入口 · 首板流已实现 / 连板流·炸板回交流·低吸流·反包流·N字反击流 待实现"
          actions={
            <div className="flex items-center gap-2">
              <AskAiButton context={askAiContext} />
              <input
                type="date"
                value={selectedDate ?? ""}
                onChange={(e) => handleDateChange(e.target.value)}
                aria-label="选择历史日期"
                className="rounded-lg border border-border/40 bg-muted/10 px-2 py-1 text-xs text-foreground focus:outline-none focus:ring-2 focus:ring-primary/50"
              />
              {selectedDate && (
                <Button variant="ghost" size="sm" onClick={clearDate}>回到今日</Button>
              )}
              <Button variant="ghost" onClick={handleRefresh} disabled={refreshing} className="p-2" aria-label="刷新">
                <RefreshCw className={`h-4 w-4 ${refreshing ? "animate-spin" : ""}`} />
              </Button>
            </div>
          }
        />

        {/* 战法流入口网格 */}
        <div>
          <SectionHeader
            title="战法流入口"
            subtitle="按战法分流的选股→确认→建仓→卖出→结算 闭环工作流"
          />
          <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
            {/* 首板流 ✅ 已实现 */}
            <StrategyFlowCard
              title="首板流"
              subtitle="首板涨停股 T+1 操作工作流（5步闭环）"
              icon={Flame}
              to="/workflow/first-board"
              implemented
              badges={fbBadges}
              footnote="§44 未 validated 仅参考；9 维度评分权重待回测校准"
            />

            {/* 连板流 待实现 */}
            <StrategyFlowCard
              title="连板流"
              subtitle="连板梯队 T+1 接力工作流"
              icon={Layers}
              implemented={false}
              dimReason="待实现（依赖 S055 炸板预警完善后启动）"
            />

            {/* 炸板回交流 待实现 */}
            <StrategyFlowCard
              title="炸板回交流"
              subtitle="炸板后回封的 T+1 反包工作流"
              icon={Zap}
              implemented={false}
              dimReason="待实现"
            />

            {/* 低吸流 待实现 */}
            <StrategyFlowCard
              title="低吸流"
              subtitle="强势股低吸 T+1 工作流"
              icon={TrendingUp}
              implemented={false}
              dimReason="待实现"
            />

            {/* 反包流 待实现 */}
            <StrategyFlowCard
              title="反包流"
              subtitle="前日大跌后反包 T+1 工作流"
              icon={BarChart3}
              implemented={false}
              dimReason="待实现"
            />

            {/* N字反击流 待实现 */}
            <StrategyFlowCard
              title="N字反击流"
              subtitle="N字结构反击 T+1 工作流"
              icon={Activity}
              implemented={false}
              dimReason="待实现"
            />
          </div>
        </div>

        {/* workflow 降级入口（原状态机看板） */}
        <div>
          <SectionHeader
            title="状态机看板（降级入口）"
            subtitle="原盘前/盘中/盘后三阶段闭环——保留作为降级视图"
          />
          <button
            type="button"
            onClick={() => setView("legacy-state-machine")}
            className="block w-full text-left"
          >
            <GlassCard
              glow
              className="p-5 transition-all hover:ring-2 hover:ring-primary/30 hover:-translate-y-0.5"
            >
              <div className="flex items-start gap-3">
                <div className="p-2.5 rounded-xl bg-indigo-500/10 border border-indigo-500/30">
                  <Share2 className="h-5 w-5 text-indigo-400" aria-hidden="true" />
                </div>
                <div className="flex-1">
                  <div className="flex items-center gap-2">
                    <h3 className="font-semibold">盘前 · 盘中 · 盘后 状态机</h3>
                    <Badge variant="info">降级视图</Badge>
                  </div>
                  <p className="text-xs text-muted-foreground/70 mt-0.5">
                    原三阶段闭环（候选池筛选 → 实时监控 → 自动结算），保留作为降级入口
                  </p>
                  {/* 当前阶段快览 */}
                  {status && (
                    <div className="mt-3 flex flex-wrap items-center gap-3 text-xs text-muted-foreground">
                      <span className="flex items-center gap-1">
                        <Clock className="h-3 w-3" /> {status.currentTime}
                      </span>
                      <span className="flex items-center gap-1">
                        <Activity className={cn("h-3 w-3", STAGE_CONFIG[status.stageKey]?.color)} />
                        {status.marketStatus}
                      </span>
                      <span>候选 {status.candidateCount}</span>
                      <span>信号 {status.signalCount}</span>
                    </div>
                  )}
                </div>
                <ChevronRight className="h-4 w-4 text-muted-foreground/50" />
              </div>
            </GlassCard>
          </button>
        </div>

        {/* 拓扑展示入口 — 关系网/漏斗流程/连板梯队三视角客观关联 */}
        <Link to="/workflow/topology">
          <GlassCard className="p-4 transition-all hover:ring-2 hover:ring-primary/30">
            <div className="flex items-center gap-3">
              <div className="p-2.5 rounded-xl bg-indigo-500/10 border border-indigo-500/30">
                <Share2 className="h-5 w-5 text-indigo-400" aria-hidden="true" />
              </div>
              <div className="flex-1">
                <div className="flex items-center gap-2">
                  <h3 className="font-semibold">拓扑展示</h3>
                  <Badge variant="default">三视角</Badge>
                </div>
                <p className="text-xs text-muted-foreground/70 mt-0.5">
                  关系网 · 漏斗流程 · 连板梯队（客观关联，只呈现不附方向结论）
                </p>
              </div>
              <ArrowRight className="h-4 w-4 text-muted-foreground/50" />
            </div>
          </GlassCard>
        </Link>

        <Disclaimer compact />
      </div>
    );
  }

  // ---- 降级视图：原状态机看板（保留全量能力）----
  if (loading) {
    return (
      <div className="space-y-6">
        <PageHeader title="Workflow" subtitle="盘前 · 盘中 · 盘后 三阶段闭环" />
        <div className="space-y-4">
          <Skeleton className="h-24 w-full" />
          <Skeleton className="h-56 w-full" />
          <Skeleton className="h-56 w-full" />
          <Skeleton className="h-56 w-full" />
        </div>
      </div>
    );
  }

  return (
    <div className="space-y-6">
      <PageHeader
        title="Workflow"
        subtitle="盘前 · 盘中 · 盘后 三阶段闭环"
        actions={
          <div className="flex items-center gap-2">
            <Button variant="ghost" size="sm" onClick={() => setView("entries")}>
              ← 返回卡片入口
            </Button>
            <AskAiButton context={askAiContext} />
            <input
              type="date"
              value={selectedDate ?? ""}
              onChange={(e) => handleDateChange(e.target.value)}
              aria-label="选择历史日期"
              className="rounded-lg border border-border/40 bg-muted/10 px-2 py-1 text-xs text-foreground focus:outline-none focus:ring-2 focus:ring-primary/50"
            />
            {selectedDate && (
              <Button variant="ghost" size="sm" onClick={clearDate}>回到今日</Button>
            )}
            <Button variant="ghost" onClick={handleRefresh} disabled={refreshing} className="p-2" aria-label="刷新">
              <RefreshCw className={`h-4 w-4 ${refreshing ? "animate-spin" : ""}`} />
            </Button>
          </div>
        }
      />

      {/* S072 去天气决策条（无 §44 edge）；保留流水线进度 */}
      <div className="mb-2">
        <PipelineProgressBar current={stageToPipeline(status?.stageKey ?? "pre-market")} />
      </div>

      {/* I1：历史快照日期 chips */}
      {datesData?.dates && datesData.dates.length > 0 && (
        <GlassCard className="p-3">
          <div className="flex flex-wrap items-center gap-2">
            <span className="text-xs text-muted-foreground/70">历史快照</span>
            {datesData.dates.map((d) => {
              const isActive = d === selectedDate;
              return (
                <button
                  key={d}
                  type="button"
                  onClick={() => handleDateChange(d)}
                  aria-pressed={isActive}
                  className={cn(
                    "rounded-full border px-2 py-0.5 text-xs transition-colors",
                    isActive
                      ? "border-primary/50 bg-primary/15 text-primary"
                      : "border-border/40 bg-muted/10 text-muted-foreground hover:border-primary/30 hover:text-primary",
                  )}
                >
                  {d}
                </button>
              );
            })}
          </div>
        </GlassCard>
      )}

      {/* 当前状态摘要 */}
      {status && (
        <GlassCard className="p-4">
          <div className="flex flex-wrap items-center gap-4 text-sm">
            <div className="flex items-center gap-2">
              <Clock className="h-4 w-4 text-muted-foreground/50" />
              <span className="text-muted-foreground/70">{status.currentTime}</span>
            </div>
            <div className="h-4 w-px bg-border/40" />
            <div className="flex items-center gap-2">
              <Activity className={cn("h-4 w-4", STAGE_CONFIG[status.stageKey]?.color)} />
              <span>{status.marketStatus}</span>
            </div>
            {status.nextStageKey && (
              <>
                <div className="h-4 w-px bg-border/40" />
                <div className="flex items-center gap-2">
                  <ChevronRight className="h-4 w-4 text-muted-foreground/50" />
                  <span className="text-muted-foreground/70">下一: {STAGE_CONFIG[status.nextStageKey]?.label}</span>
                  <span className="text-xs text-muted-foreground/50">· {countDownToNext(status.nextStageKey, status.currentTime ?? "")}</span>
                </div>
              </>
            )}
          </div>
        </GlassCard>
      )}

      {/* 阶段卡片 — 恒按 盘前→盘中→盘后 固定位 */}
      <div className="space-y-4">
        {STAGE_ORDER.map((stageKey) => {
          const isCurrent = stageKey === currentStage;
          const stageIdx = STAGE_ORDER.indexOf(stageKey);
          const pastIdx = STAGE_ORDER.indexOf(currentStage);
          const isPast = stageIdx < pastIdx && !isCurrent;

          return (
            <StageCard
              key={stageKey}
              stageKey={stageKey}
              isActive={isCurrent}
              isPast={isPast}
              status={status}
              histValue={isHistorical ? histValues[stageKey] : undefined}
              selectedDate={selectedDate ?? undefined}
            />
          );
        })}
      </div>

      {/* 拓扑展示入口 */}
      <Link to="/workflow/topology">
        <GlassCard className="p-4 transition-all hover:ring-2 hover:ring-primary/30">
          <div className="flex items-center gap-3">
            <div className="p-2.5 rounded-xl bg-indigo-500/10 border border-indigo-500/30">
              <Share2 className="h-5 w-5 text-indigo-400" aria-hidden="true" />
            </div>
            <div className="flex-1">
              <div className="flex items-center gap-2">
                <h3 className="font-semibold">拓扑展示</h3>
                <Badge variant="default">三视角</Badge>
              </div>
              <p className="text-xs text-muted-foreground/70 mt-0.5">
                关系网 · 漏斗流程 · 连板梯队（客观关联，只呈现不附方向结论）
              </p>
            </div>
            <ArrowRight className="h-4 w-4 text-muted-foreground/50" />
          </div>
        </GlassCard>
      </Link>

      <Disclaimer compact />
    </div>
  );
}

// ---- SectionHeader（轻量本地实现，避免新增 import 路径依赖）----
function SectionHeader({ title, subtitle }: { title: string; subtitle?: string }) {
  return (
    <div className="mb-3">
      <h2 className="flex items-center gap-2 text-base font-semibold tracking-tight text-glow">
        <Sparkles className="h-4 w-4 text-primary" />
        {title}
      </h2>
      {subtitle && <p className="mt-0.5 text-xs text-muted-foreground">{subtitle}</p>}
    </div>
  );
}
