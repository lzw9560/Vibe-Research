// 多维度 IA: 风控横切徽章——M4 断路器 / M5 财报季 / M6 日历效应
// 贯穿各线触发，徽章非页。无后端 endpoint 时 honest-empty 标"待接线"
import { type ReactNode } from "react";
import { cn } from "@/lib/utils";

export interface RiskBadgeProps {
  variant: "circuit-breaker" | "earnings-season" | "calendar";
  status: "clear" | "active" | "warning" | "unknown";
  detail?: string;
  className?: string;
}

const META: Record<RiskBadgeProps["variant"], { label: string; icon: string }> = {
  "circuit-breaker": { label: "M4 断路器", icon: "🔌" },
  "earnings-season": { label: "M5 财报季", icon: "📅" },
  calendar: { label: "M6 日历", icon: "🗓️" },
};

const STATUS_STYLE: Record<RiskBadgeProps["status"], string> = {
  clear: "border-emerald-500/30 bg-emerald-500/5 text-emerald-500",
  active: "border-red-500/40 bg-red-500/10 text-red-500",
  warning: "border-amber-500/40 bg-amber-500/10 text-amber-500",
  unknown: "border-border/40 bg-muted/10 text-muted-foreground",
};

function statusText(s: RiskBadgeProps["status"]): string {
  return {
    clear: "正常",
    active: "触发",
    warning: "警戒",
    unknown: "待接线",
  }[s];
}

export function RiskBadge({ variant, status, detail, className }: RiskBadgeProps) {
  const meta = META[variant];
  return (
    <span
      className={cn(
        "inline-flex items-center gap-1 rounded-full border px-2.5 py-1 text-xs font-medium",
        STATUS_STYLE[status],
        className,
      )}
      title={detail ?? meta.label}
    >
      <span>{meta.icon}</span>
      {meta.label}
      <span className="opacity-70">· {statusText(status)}</span>
      {detail && status !== "unknown" && (
        <span className="hidden sm:inline opacity-60">· {detail}</span>
      )}
    </span>
  );
}

// 风控横切条——放各线页顶，3 徽章并排
export function RiskBadgeRow({ children }: { children?: ReactNode }) {
  return (
    <div className="flex flex-wrap items-center gap-2">
      <RiskBadge variant="circuit-breaker" status="unknown" />
      <RiskBadge variant="earnings-season" status="unknown" />
      <RiskBadge variant="calendar" status="unknown" />
      {children}
    </div>
  );
}

// 财报季判定（1/4/8 月为 A 股财报季雷区）
export function isEarningsSeason(month: number): boolean {
  return [1, 4, 8].includes(month);
}
