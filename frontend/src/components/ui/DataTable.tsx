import { type ReactNode } from "react";
import { cn } from "@/lib/utils";
import { GlassCard } from "./GlassCard";

interface DataTableProps<T> {
  data: T[];
  columns: {
    key: string;
    header: string;
    render?: (item: T) => ReactNode;
    className?: string;
    align?: "left" | "right" | "center";
  }[];
  keyExtractor: (item: T, index: number) => string;
  emptyState?: ReactNode;
  loading?: boolean;
  skeletonRows?: number;
  className?: string;
  onRowClick?: (item: T) => void;
}

// 统一数据表格：支持自定义渲染、加载态、空状态、行点击
export function DataTable<T>({
  data,
  columns,
  keyExtractor,
  emptyState,
  loading = false,
  skeletonRows = 5,
  className,
  onRowClick,
}: DataTableProps<T>) {
  const alignClasses = {
    left: "text-left",
    right: "text-right",
    center: "text-center",
  };

  const defaultEmptyState = (
    <div className="py-8 text-center text-sm text-muted-foreground/60">暂无数据</div>
  );

  if (loading) {
    return (
      <GlassCard className={className}>
        <div className="space-y-2">
          {/* Header */}
          <div className="flex gap-4 border-b border-border/50 bg-muted/20 px-4 py-2.5">
            {columns.map((col) => (
              <div
                key={col.key}
                className={cn("text-xs font-medium text-muted-foreground", alignClasses[col.align || "left"])}
                style={{ flex: col.key === "name" || col.key === "title" ? 2 : 1 }}
              >
                {col.header}
              </div>
            ))}
          </div>
          {/* Skeleton rows */}
          {Array.from({ length: skeletonRows }).map((_, i) => (
            <div key={i} className="flex gap-4 border-b border-border/20 px-4 py-2.5 last:border-0">
              {columns.map((col) => (
                <div
                  key={col.key}
                  className={cn("h-4 rounded bg-muted/20 animate-pulse", alignClasses[col.align || "left"])}
                  style={{ flex: col.key === "name" || col.key === "title" ? 2 : 1 }}
                />
              ))}
            </div>
          ))}
        </div>
      </GlassCard>
    );
  }

  if (data.length === 0) {
    return (
      <GlassCard className={className}>
        {emptyState || defaultEmptyState}
      </GlassCard>
    );
  }

  return (
    <GlassCard className={cn("overflow-hidden", className)}>
      <div className="overflow-x-auto">
        <table className="w-full text-sm">
          <thead>
            <tr className="border-b border-border/50 bg-muted/20 text-left text-xs text-muted-foreground">
              {columns.map((col) => (
                <th
                  key={col.key}
                  className={cn(
                    "whitespace-nowrap px-4 py-2.5 font-medium",
                    alignClasses[col.align || "left"],
                    col.className
                  )}
                >
                  {col.header}
                </th>
              ))}
            </tr>
          </thead>
          <tbody className="divide-y divide-border/20">
            {data.map((item, index) => (
              <tr
                key={keyExtractor(item, index)}
                onClick={() => onRowClick?.(item)}
                className={cn(
                  "transition-colors",
                  onRowClick && "cursor-pointer hover:bg-muted/20"
                )}
              >
                {columns.map((col) => (
                  <td
                    key={col.key}
                    className={cn(
                      "whitespace-nowrap px-4 py-2.5",
                      alignClasses[col.align || "left"],
                      col.className
                    )}
                  >
                    {col.render ? col.render(item) : (item as any)[col.key]}
                  </td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </GlassCard>
  );
}
