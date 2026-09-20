// S221 gap1: 推送状态卡——TodaySignalsPanel 顶部 cron fire 状态灯。
// 复用 useDeliveryFireStatus（GET /api/scheduled-tasks，filter daily_report task）。
// today_status + notify_on_success 映射 ✓/✗/⚠。不臆造"已送达"（无 webhook receipt，只标配置态）。
import { Loader2, CheckCircle2, XCircle, AlertTriangle, Bell, BellOff } from "lucide-react";
import { useDeliveryFireStatus } from "@/lib/query/signals";
import type { ScheduledTaskStatus } from "@/lib/query/scheduledTasks";

/** today_status + notify_on_success → 人话状态灯配置 */
function deriveFireState(task: ScheduledTaskStatus | null): {
  icon: typeof CheckCircle2;
  label: string;
  tone: "ok" | "warn" | "err" | "idle";
  feishuLabel: string;
  feishuOk: boolean;
} {
  if (!task) {
    return { icon: XCircle, label: "今日未 fire", tone: "err", feishuLabel: "—", feishuOk: false };
  }
  const feishuOk = task.notify_on_success;
  const feishuLabel = feishuOk ? "飞书已配置" : "飞书未配置";
  switch (task.today_status) {
    case "done":
      return {
        icon: feishuOk ? CheckCircle2 : AlertTriangle,
        label: feishuOk ? "今天已 fire" : "今天已 fire",
        tone: feishuOk ? "ok" : "warn",
        feishuLabel,
        feishuOk,
      };
    case "running":
      return { icon: Loader2, label: "运行中", tone: "idle", feishuLabel, feishuOk };
    case "degraded":
      return { icon: AlertTriangle, label: "fire 但降级", tone: "warn", feishuLabel, feishuOk };
    case "error":
      return { icon: XCircle, label: "fire 失败", tone: "err", feishuLabel, feishuOk };
    case "pending":
    default:
      return { icon: XCircle, label: "今日未 fire", tone: "err", feishuLabel, feishuOk };
  }
}

const TONE_CLASS: Record<string, string> = {
  ok: "text-emerald-600",
  warn: "text-amber-600",
  err: "text-red-500",
  idle: "text-blue-500",
};

export function DeliveryStatusCard() {
  const { dailyReport, isLoading, isError } = useDeliveryFireStatus();

  if (isLoading) {
    return (
      <div className="mb-3 flex items-center gap-2 rounded border border-border/40 px-3 py-2 text-xs">
        <div className="h-3 w-3 animate-pulse rounded bg-muted/40" />
        <div className="h-3 w-24 animate-pulse rounded bg-muted/40" />
      </div>
    );
  }

  if (isError) {
    return (
      <div className="mb-3 rounded border border-border/40 px-3 py-2 text-xs text-muted-foreground">
        推送状态加载失败
      </div>
    );
  }

  const state = deriveFireState(dailyReport);
  const Icon = state.icon;
  const FeishuIcon = state.feishuOk ? Bell : BellOff;

  return (
    <div
      className="mb-3 flex items-center justify-between rounded border border-border/40 px-3 py-2 text-xs"
      data-testid="delivery-status-card"
    >
      <div className="flex items-center gap-1.5">
        <Icon className={`h-3.5 w-3.5 ${TONE_CLASS[state.tone]}`} />
        <span className="font-medium">
          每日报告推送：
          <span className={TONE_CLASS[state.tone]}>{state.label}</span>
        </span>
      </div>
      <div className="flex items-center gap-1 text-muted-foreground">
        <FeishuIcon className={`h-3 w-3 ${state.feishuOk ? "text-emerald-500" : "text-muted-foreground/60"}`} />
        <span className={state.feishuOk ? "text-emerald-600" : "text-amber-600"}>{state.feishuLabel}</span>
      </div>
    </div>
  );
}
