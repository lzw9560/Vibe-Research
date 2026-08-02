import { type ReactNode } from "react";
import { cn } from "@/lib/utils";
import { GlassCard } from "./GlassCard";

export type SortDirection = "asc" | "desc";
export interface SortState {
  key: string;
  direction: SortDirection;
}

export interface Column<T> {
  key: string;
  header: string;
  render?: (item: T) => ReactNode;
  className?: string;
  align?: "left" | "right" | "center";
  /** 列可排序：true 时表头可点击触发 onSort。 */
  sortable?: boolean;
  /** 排序键；默认用 col.key。 */
  sortKey?: string;
}

export interface DataTableProps<T> {
  data: T[];
  columns: Column<T>[];
  keyExtractor: (item: T, index: number) => string;
  emptyState?: ReactNode;
  loading?: boolean;
  skeletonRows?: number;
  className?: string;
  onRowClick?: (item: T) => void;
  /** 受控排序状态（null = 未排序）。DataTable 本身不排序，由父层驱动数据顺序。 */
  sort?: SortState | null;
  /** 表头点击排序回调；传出 sortKey（或 col.key）。 */
  onSort?: (key: string) => void;
}

// 统一数据表格：三态（loading/empty/data）+ 列级排序契约 + 行点击。
// 排序为受控：DataTable 只呈现排序指示与 aria-sort，实际数据排序由父层负责（纯展示组件）。
export function DataTable<T>({
  data,
  columns,
  keyExtractor,
  emptyState,
  loading = false,
  skeletonRows = 5,
  className,
  onRowClick,
  sort = null,
  onSort,
}: DataTableProps<T>) {
  const alignClasses = {
    left: "text-left",
    right: "text-right",
    center: "text-center",
  };

  const defaultEmptyState = (
    <div className="py-8 text-center text-sm text-muted-foreground/60">暂无数据</div>
  );

  const sortKeyOf = (col: Column<T>) => col.sortKey ?? col.key;

  const handleSort = (col: Column<T>) => {
    if (!col.sortable || !onSort) return;
    onSort(sortKeyOf(col));
  };

  const sortIndicator = (col: Column<T>): ReactNode => {
    // 需 sortable 且提供了 onSort 才显示指示；否则列为静态，不误导用户可点。
    if (!col.sortable || !onSort) return null;
    const active = sort && sort.key === sortKeyOf(col);
    if (active && sort!.direction === "asc") return <span aria-hidden="true">▲</span>;
    if (active && sort!.direction === "desc") return <span aria-hidden="true">▼</span>;
    return <span aria-hidden="true" className="text-muted-foreground/40">↕</span>;
  };

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
              {columns.map((col) => {
                const sortable = col.sortable && onSort;
                const active = sort && sort.key === sortKeyOf(col);
                return (
                  <th
                    key={col.key}
                    scope="col"
                    aria-sort={
                      active
                        ? sort!.direction === "asc"
                          ? "ascending"
                          : "descending"
                        : "none"
                    }
                    className={cn(
                      "whitespace-nowrap px-4 py-2.5 font-medium",
                      alignClasses[col.align || "left"],
                      col.className,
                      sortable && "cursor-pointer select-none hover:text-foreground",
                    )}
                    onClick={() => handleSort(col)}
                  >
                    <span className="inline-flex items-center gap-1">
                      {col.header}
                      {sortIndicator(col)}
                    </span>
                  </th>
                );
              })}
            </tr>
          </thead>
          <tbody className="divide-y divide-border/20">
            {data.map((item, index) => (
              <tr
                key={keyExtractor(item, index)}
                onClick={() => onRowClick?.(item)}
                className={cn(
                  "transition-colors",
                  onRowClick && "cursor-pointer hover:bg-muted/20",
                )}
              >
                {columns.map((col) => (
                  <td
                    key={col.key}
                    className={cn(
                      "whitespace-nowrap px-4 py-2.5",
                      alignClasses[col.align || "left"],
                      col.className,
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
