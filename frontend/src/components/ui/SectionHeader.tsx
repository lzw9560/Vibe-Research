import { type ReactNode } from "react";
import { cn } from "@/lib/utils";

interface SectionHeaderProps {
  title: ReactNode;
  icon?: ReactNode;
  subtitle?: string;
  action?: ReactNode;
  className?: string;
}

// 统一区块标题：左侧主色竖线 + 图标 + 标题 + 辅助说明 + 右侧操作区
export function SectionHeader({ title, icon, subtitle, action, className }: SectionHeaderProps) {
  return (
    <div className={cn("mb-3 flex items-center gap-2", className)}>
      <div className="flex items-center gap-1.5">
        {icon && <span className="text-muted-foreground">{icon}</span>}
        <h3 className="text-sm font-semibold text-foreground">{title}</h3>
      </div>
      {subtitle && (
        <span className="text-[11px] text-muted-foreground/50">{subtitle}</span>
      )}
      {action && <div className="ml-auto">{action}</div>}
    </div>
  );
}
