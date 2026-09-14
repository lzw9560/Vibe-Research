// 多维度 IA: 线状态灯——每条用户线一个状态灯（绿=就绪/琥珀=待办/红=告警/灰=空闲）
// 被七灯汇总(SevenLineStatus)和各线页内灯复用
import { type ReactNode } from "react";
import { Link } from "react-router-dom";
import { cn } from "@/lib/utils";

export type LineStatus = "ok" | "pending" | "alert" | "idle";

export interface LineStatusLightProps {
  lineKey: string;
  label: string;
  status: LineStatus;
  detail?: string;
  link?: string;
  icon?: ReactNode;
  compact?: boolean;
}

const STATUS_META: Record<LineStatus, { dot: string; text: string; label: string }> = {
  ok: { dot: "bg-emerald-500", text: "text-emerald-500", label: "就绪" },
  pending: { dot: "bg-amber-500", text: "text-amber-500", label: "待办" },
  alert: { dot: "bg-red-500", text: "text-red-500", label: "告警" },
  idle: { dot: "bg-gray-400", text: "text-muted-foreground", label: "空闲" },
};

export function LineStatusLight({
  label,
  status,
  detail,
  link,
  icon,
  compact,
}: LineStatusLightProps) {
  const meta = STATUS_META[status];
  const content = (
    <div
      className={cn(
        "flex items-center gap-2 rounded-lg border border-border/40 bg-muted/10 transition-colors hover:border-primary/20",
        compact ? "px-2.5 py-1.5" : "px-3 py-2",
      )}
    >
      <span className={cn("h-2 w-2 shrink-0 rounded-full", meta.dot)} />
      {icon && <span className="shrink-0 text-muted-foreground">{icon}</span>}
      <div className="min-w-0 flex-1">
        <div className={cn("font-medium", compact ? "text-xs" : "text-sm")}>
          {label}
          <span className={cn("ml-1.5 text-[10px]", meta.text)}>{meta.label}</span>
        </div>
        {detail && !compact && (
          <div className="truncate text-[11px] text-muted-foreground">{detail}</div>
        )}
      </div>
      {link && <span className="shrink-0 text-[10px] text-primary">→</span>}
    </div>
  );

  if (!link) return content;
  return <Link to={link}>{content}</Link>;
}

// 静态状态计算工具——被各线页内用，七灯汇总也用
export function statusFromBool(ready: boolean, hasAlert = false): LineStatus {
  if (hasAlert) return "alert";
  return ready ? "ok" : "idle";
}
