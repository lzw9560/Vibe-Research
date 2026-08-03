import { useMemo } from "react";
import { Link } from "react-router-dom";
import {
  Clock, TrendingUp, BarChart3, ChevronRight, RefreshCw, Flame,
  ArrowRight, Activity, Zap, Share2,
} from "lucide-react";
import { cn } from "@/lib/utils";
import { PageHeader } from "@/components/ui/PageHeader";
import { GlassCard } from "@/components/ui/GlassCard";
import { Button } from "@/components/ui/Button";
import { Badge } from "@/components/ui/Badge";
import { Skeleton } from "@/components/ui/Skeleton";
import { Disclaimer } from "@/components/ui/Disclaimer";
import { useWorkflowStatus } from "@/lib/query";

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
function getAStockTimeInfo(): {
  hours: number;
  minutes: number;
  stageKey: string;
  marketStatus: string;
  nextStageKey: string | null;
  nextStageTime: string | null;
} {
  const now = new Date();
  const h = now.getHours();
  const m = now.getMinutes();
  const totalMin = h * 60 + m;

  // A股交易时段精确划分
  // 盘前: 08:00 - 09:25 (集合竞价 09:15-09:25)
  // 集合竞价: 09:15 - 09:25
  // 早盘: 09:30 - 11:30
  // 午盘: 13:00 - 15:00
  // 盘后: 15:00 - 22:00

  if (totalMin >= 480 && totalMin < 555) { // 08:00 - 09:14
    return { hours: h, minutes: m, stageKey: "pre-market", marketStatus: "盘前准备", nextStageKey: "intraday", nextStageTime: "09:30" };
  } else if (totalMin >= 555 && totalMin < 570) { // 09:15 - 09:24 集合竞价
    return { hours: h, minutes: m, stageKey: "pre-market", marketStatus: "集合竞价中", nextStageKey: "intraday", nextStageTime: "09:30" };
  } else if (totalMin >= 570 && totalMin < 750) { // 09:30 - 11:29 上午盘
    return { hours: h, minutes: m, stageKey: "intraday", marketStatus: "上午盘", nextStageKey: "post-market", nextStageTime: "15:00" };
  } else if (totalMin >= 750 && totalMin < 780) { // 11:30 - 12:59 午休
    return { hours: h, minutes: m, stageKey: "intraday", marketStatus: "午休时段", nextStageKey: "post-market", nextStageTime: "15:00" };
  } else if (totalMin >= 780 && totalMin < 900) { // 13:00 - 14:59 下午盘
    return { hours: h, minutes: m, stageKey: "intraday", marketStatus: "下午盘", nextStageKey: "post-market", nextStageTime: "15:00" };
  } else if (totalMin >= 900 && totalMin < 1320) { // 15:00 - 21:59 盘后
    return { hours: h, minutes: m, stageKey: "post-market", marketStatus: "盘后复盘", nextStageKey: "pre-market", nextStageTime: "次日 08:00" };
  } else { // 22:00 - 07:59 非交易时段
    return { hours: h, minutes: m, stageKey: "pre-market", marketStatus: "休市中", nextStageKey: "pre-market", nextStageTime: "08:00" };
  }
}

/** 计算距离下一个阶段的分钟数 */
function countDownToNext(stageKey: string): string {
  const now = new Date();
  let target = new Date(now);

  if (stageKey === "pre-market") {
    // 到 09:30
    target.setHours(9, 30, 0, 0);
  } else if (stageKey === "intraday") {
    // 到 15:00
    target.setHours(15, 0, 0, 0);
  } else {
    // 到次日 08:00
    target.setDate(target.getDate() + 1);
    target.setHours(8, 0, 0, 0);
  }

  const diff = target.getTime() - now.getTime();
  if (diff <= 0) return "即将开始";
  const hours = Math.floor(diff / 3600000);
  const mins = Math.floor((diff % 3600000) / 60000);
  if (hours > 0) return `${hours}小时${mins}分`;
  return `${mins}分钟`;
}

// ---- 阶段配置 ----
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

// ---- Session Map 组件 ----
function SessionMap({ currentStage }: { currentStage: string }) {
  return (
    <GlassCard className="p-4 md:p-6">
      <div className="flex items-center justify-between mb-2">
        <h3 className="text-sm font-semibold text-muted-foreground uppercase tracking-wider">今日交易时段</h3>
        <span className="text-xs text-muted-foreground/60">实时更新</span>
      </div>

      {/* 时间线 */}
      <div className="relative">
        {/* 背景轨道 */}
        <div className="absolute inset-x-0 top-5 h-1 rounded-full bg-muted/30" />

        {/* 进度填充（根据当前时间动态） */}
        <div
          className="absolute inset-y-0 left-0 h-1 rounded-full bg-primary/40 transition-all duration-1000"
          style={{
            width: currentStage === "pre-market" ? "33%" : currentStage === "intraday" ? "66%" : "100%",
          }}
        />

        {/* 时段节点 */}
        <div className="relative flex justify-between">
          {STAGE_ORDER.map((key, i) => {
            const config = STAGE_CONFIG[key];
            const isCurrent = key === currentStage;
            const isPast = STAGE_ORDER.indexOf(currentStage) > i;
            const Icon = config.icon;

            return (
              <div key={key} className="flex flex-col items-center gap-2">
                {/* 节点圆 */}
                <div
                  className={cn(
                    "flex h-10 w-10 items-center justify-center rounded-full border-2 transition-all",
                    isCurrent
                      ? cn("border-primary bg-primary/20", "animate-pulse")
                      : isPast
                        ? cn("border-emerald-500/60 bg-emerald-500/10")
                        : "border-muted/40 bg-muted/10",
                  )}
                >
                  <Icon className={cn("h-5 w-5", isCurrent ? config.color : isPast ? "text-emerald-400" : "text-muted-foreground/40")} />
                </div>

                {/* 标签 */}
                <div className="text-center">
                  <p className={cn(
                    "text-xs font-medium",
                    isCurrent ? "text-primary" : isPast ? "text-emerald-400/70" : "text-muted-foreground/50",
                  )}>
                    {config.label}
                  </p>
                  <p className="text-[10px] text-muted-foreground/40">{config.timeRange}</p>
                </div>
              </div>
            );
          })}
        </div>
      </div>

      {/* 当前时间标记 */}
      <div className="mt-4 flex items-center justify-center gap-2 text-xs text-muted-foreground/50">
        <Activity className="h-3 w-3 animate-pulse text-primary" />
        <span>当前: {getAStockTimeInfo().marketStatus}</span>
      </div>
    </GlassCard>
  );
}

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

// ---- 阶段卡片 ----
function StageCard({
  stageKey,
  isActive,
  isPast,
  status,
}: {
  stageKey: string;
  isActive: boolean;
  isPast: boolean;
  status: WorkflowStatus | null;
}) {
  const config = STAGE_CONFIG[stageKey];
  const Icon = config.icon;
  const countdown = !isPast ? countDownToNext(stageKey) : null;

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
  const stat = stats[stageKey];

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
        {config.links.map((link) => (
          <Link key={link.to} to={link.to}>
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

// ---- 主页面 ----
export default function Workflow() {
  // T9：原 useState/useEffect + setInterval(60s) + getWorkflowStatus() → useWorkflowStatus + refetchInterval。
  // 注：getWorkflowStatus() 返 T | null（null 为失败/空信号，不 throw），故无 error UI——null 时各计数回落 0。
  // 时间信息由 getAStockTimeInfo() 就地计算；useMemo 依赖 backend，每次 60s 重取时连同时间一并刷新（保留原行为）。
  // hook data 已类型化（api WorkflowStatus 含 [key: string]: unknown 索引签名），
  // 各字段经 `as number` 取值即可，不再需要 as unknown as Record<string, unknown> 放宽 cast。
  const { data: backend, isLoading: loading, isFetching, refetch } = useWorkflowStatus({ refetchInterval: 60_000 });
  const refreshing = isFetching && !loading;

  const status = useMemo<WorkflowStatus | null>(() => {
    const timeInfo = getAStockTimeInfo();
    // 后端字段名容错（candidate_count / candidate_pool_count 等多别名）
    const candidateCount = (backend?.candidate_count as number) ?? (backend?.candidate_pool_count as number) ?? 0;
    const signalCount = (backend?.signal_count as number) ?? (backend?.active_signals as number) ?? 0;
    const alertCount = (backend?.alert_count as number) ?? 0;
    const winRate = (backend?.win_rate as number) ?? (backend?.today_win_rate as number) ?? 0;

    return {
      stageKey: timeInfo.stageKey,
      stageLabel: STAGE_CONFIG[timeInfo.stageKey]?.label ?? "",
      currentTime: `${timeInfo.hours.toString().padStart(2, '0')}:${timeInfo.minutes.toString().padStart(2, '0')}`,
      marketStatus: timeInfo.marketStatus,
      nextStageKey: timeInfo.nextStageKey,
      nextStageTime: timeInfo.nextStageTime ?? "",
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

  // 排序：当前阶段置顶，然后是已完成的，最后是未开始的
  const sortedStages = useMemo(() => {
    return [...STAGE_ORDER].sort((a, b) => {
      const aIdx = STAGE_ORDER.indexOf(a);
      const bIdx = STAGE_ORDER.indexOf(b);
      const aPos = STAGE_ORDER.indexOf(a);
      const bPos = STAGE_ORDER.indexOf(b);

      // 当前阶段排第一
      if (a === currentStage) return -1;
      if (b === currentStage) return 1;

      // 已完成的排在前面
      const aPast = aIdx > aPos;
      const bPast = bIdx > bPos;
      if (aPast && !bPast) return -1;
      if (!aPast && bPast) return 1;

      return 0;
    });
  }, [currentStage]);

  if (loading) {
    return (
      <div className="space-y-6">
        <PageHeader title="打板工作流" subtitle="盘前 · 盘中 · 盘后 三阶段闭环" />
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
        title="打板工作流"
        subtitle="盘前 · 盘中 · 盘后 三阶段闭环"
        actions={
          <Button variant="ghost" onClick={handleRefresh} disabled={refreshing} className="p-2" aria-label="刷新">
            <RefreshCw className={`h-4 w-4 ${refreshing ? "animate-spin" : ""}`} />
          </Button>
        }
      />

      {/* Session Map — 横向时间线 */}
      <SessionMap currentStage={currentStage} />

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
                  <span className="text-xs text-muted-foreground/50">· {countDownToNext(status.nextStageKey)}</span>
                </div>
              </>
            )}
          </div>
        </GlassCard>
      )}

      {/* 阶段卡片 — 纵向流程 */}
      <div className="space-y-4">
        {sortedStages.map((stageKey) => {
          const isCurrent = stageKey === currentStage;
          const pastIdx = STAGE_ORDER.indexOf(currentStage);
          const stageIdx = STAGE_ORDER.indexOf(stageKey);
          const isPast = stageIdx < pastIdx && !isCurrent;

          return (
            <StageCard
              key={stageKey}
              stageKey={stageKey}
              isActive={isCurrent}
              isPast={isPast}
              status={status}
            />
          );
        })}
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
