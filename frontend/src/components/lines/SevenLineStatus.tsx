// 多维度 IA: 七灯汇总——/today hub 一屏 7 状态灯
// 5 线(时间/选股/验证/策略/认知) + 风控横切 + 数据底座
// 纯展示组件，由 TodayPage 从已有 hooks 算出 7 个 status 传入
import { type ReactNode } from "react";
import { Link } from "react-router-dom";
import { cn } from "@/lib/utils";
import { GlassCard } from "@/components/ui/GlassCard";
import type { LineStatus } from "./LineStatusLight";

export interface LineStatusItem {
  key: string;
  label: string;
  status: LineStatus;
  detail?: string;
  link?: string;
  icon?: ReactNode;
}

const STATUS_DOT: Record<LineStatus, string> = {
  ok: "bg-emerald-500",
  pending: "bg-amber-500",
  alert: "bg-red-500",
  idle: "bg-gray-400",
};

const STATUS_TEXT: Record<LineStatus, string> = {
  ok: "text-emerald-500",
  pending: "text-amber-500",
  alert: "text-red-500",
  idle: "text-muted-foreground",
};

const STATUS_LABEL: Record<LineStatus, string> = {
  ok: "就绪",
  pending: "待办",
  alert: "告警",
  idle: "空闲",
};

export function SevenLineStatus({ items }: { items: LineStatusItem[] }) {
  return (
    <GlassCard tier="primary" className="mb-4">
      <h2 className="mb-3 text-sm font-semibold">七线状态总览</h2>
      <div className="grid grid-cols-2 gap-2 sm:grid-cols-4 lg:grid-cols-7">
        {items.map((item) => {
          const content = (
            <div className="flex items-center gap-2 rounded-lg border border-border/30 bg-muted/10 px-2.5 py-2 transition-colors hover:border-primary/20">
              <span className={cn("h-2 w-2 shrink-0 rounded-full", STATUS_DOT[item.status])} />
              <div className="min-w-0 flex-1">
                <div className="truncate text-xs font-medium">
                  {item.label}
                </div>
                <div className={cn("truncate text-[10px]", STATUS_TEXT[item.status])}>
                  {STATUS_LABEL[item.status]}
                  {item.detail && ` · ${item.detail}`}
                </div>
              </div>
            </div>
          );
          return item.link ? (
            <Link key={item.key} to={item.link}>{content}</Link>
          ) : (
            <div key={item.key}>{content}</div>
          );
        })}
      </div>
    </GlassCard>
  );
}
