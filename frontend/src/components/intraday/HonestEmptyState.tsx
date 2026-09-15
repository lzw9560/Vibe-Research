// S179 P0.4: 盘中无数据诚实空态（不假装有数据）。
// 仿 OfiDashboard 空态（「暂无 OFI 快照·盘中采集后显示」）
// + JournalLedger 暂无闭环记录（「运行 journal_recorder.run_daily() 后显示」）范式。
// 与 ui/EmptyState 区别：EmptyState 通用空态（icon/title/description/action），
// 本组件专做「诚实」——如实呈现无数据 + 提示来源/触发条件，不渲染假数据或永转 loading。
import { type ReactNode } from "react";
import { cn } from "@/lib/utils";

interface HonestEmptyStateProps {
  /** 主消息：如实说明无什么数据（如「暂无 OFI 快照」） */
  message: string;
  /** 可选提示：数据来源 / 触发条件 / 下一步（如「盘中采集后显示」）。支持 ReactNode 以放 <code> 等 */
  hint?: ReactNode;
  className?: string;
}

// 诚实空态——不假装有数据。
// 用于盘中 OFI / 选股行 / conditioning 等场景：
// 数据未采集到时如实显示空态 + 提示来源，而非渲染假数据或 loading 永转。
export function HonestEmptyState({ message, hint, className }: HonestEmptyStateProps) {
  return (
    <div
      className={cn(
        "rounded-md border border-dashed border-border/40 bg-muted/10 px-4 py-6 text-center",
        className,
      )}
    >
      <p className="text-sm text-muted-foreground">{message}</p>
      {hint && <p className="mt-1 text-[11px] text-muted-foreground">{hint}</p>}
    </div>
  );
}
