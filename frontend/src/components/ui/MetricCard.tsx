import { cn } from "@/lib/utils";

interface MetricCardProps {
  label: string;
  value: string | number;
  unit?: string;
  trend?: string;
  trendUp?: boolean;
  sub?: string;
  className?: string;
  valueClassName?: string;
  onClick?: () => void;
}

// 统一指标卡：用于展示关键数值，支持趋势指示和辅助说明
export function MetricCard({ label, value, unit, trend, trendUp, sub, className, valueClassName, onClick }: MetricCardProps) {
  const displayValue = typeof value === "number" ? value.toLocaleString("zh-CN") : value;
  const displayUnit = unit ? ` ${unit}` : "";

  return (
    <div
      onClick={onClick}
      className={cn(
        "rounded-lg bg-muted/25 p-3 transition-colors",
        onClick && "cursor-pointer hover:bg-muted/40",
        className
      )}
    >
      <p className="text-xs text-muted-foreground">{label}</p>
      <div className="mt-0.5 flex items-baseline gap-1">
        <p className={cn("font-mono text-base font-bold text-foreground", valueClassName)}>
          {displayValue}
          {displayUnit}
        </p>
        {trend && (
          <span className={cn("text-xs font-medium", trendUp ? "text-danger" : "text-success")}>
            {trend}
          </span>
        )}
      </div>
      {sub && <p className="mt-0.5 text-[11px] text-muted-foreground/60">{sub}</p>}
    </div>
  );
}
