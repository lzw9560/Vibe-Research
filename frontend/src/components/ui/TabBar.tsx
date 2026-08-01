import { type ReactNode } from "react";
import { cn } from "@/lib/utils";

interface TabItem {
  key: string;
  label: string;
  icon?: ReactNode;
  disabled?: boolean;
}

interface TabBarProps {
  tabs: TabItem[];
  activeKey: string;
  onChange: (key: string) => void;
  className?: string;
  size?: "sm" | "md";
}

// 统一 Tab 栏：胶囊样式，支持图标和禁用状态
export function TabBar({ tabs, activeKey, onChange, className, size = "md" }: TabBarProps) {
  const sizeClasses = {
    sm: "px-2.5 py-1 text-xs",
    md: "px-3.5 py-1.5 text-sm",
  };

  return (
    <div className={cn("flex items-center gap-1 rounded-lg bg-muted/30 p-1", className)}>
      {tabs.map((tab) => {
        const isActive = activeKey === tab.key;
        return (
          <button
            key={tab.key}
            onClick={() => !tab.disabled && onChange(tab.key)}
            disabled={tab.disabled}
            className={cn(
              "flex items-center gap-1.5 whitespace-nowrap rounded-md font-medium transition-all",
              sizeClasses[size],
              isActive
                ? "bg-primary/15 text-primary shadow-sm"
                : "text-muted-foreground hover:text-foreground hover:bg-muted/20",
              tab.disabled && "opacity-50 cursor-not-allowed"
            )}
          >
            {tab.icon && <span className="h-4 w-4">{tab.icon}</span>}
            {tab.label}
          </button>
        );
      })}
    </div>
  );
}
