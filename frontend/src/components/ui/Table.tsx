import { cn } from "@/lib/utils";
import { SkeletonTable } from "@/components/ui/Skeleton";
import type { ReactNode } from "react";

interface Column<T> {
  key: string;
  header: string;
  render?: (item: T) => ReactNode;
  className?: string;
  align?: "left" | "center" | "right";
}

interface TableProps<T> {
  data: T[] | null | undefined;
  columns: Column<T>[];
  keyExtractor: (item: T) => string;
  emptyMessage?: string;
  loading?: boolean;
  rowClassName?: (item: T) => string;
}

export function Table<T>({
  data,
  columns,
  keyExtractor,
  emptyMessage = "暂无数据",
  loading = false,
  rowClassName,
}: TableProps<T>) {
  if (loading) {
    return <SkeletonTable rows={5} />;
  }

  if (!data || data.length === 0) {
    return (
      <div className="flex items-center justify-center py-8 text-sm text-muted-foreground/60">
        {emptyMessage}
      </div>
    );
  }

  return (
    <div className="overflow-x-auto">
      <table className="w-full text-sm">
        <thead>
          <tr className="border-b border-border/50 bg-muted/20 text-left text-xs text-muted-foreground">
            {columns.map((col) => (
              <th
                key={col.key}
                className={cn(
                  "whitespace-nowrap px-3 py-2.5 font-medium",
                  col.align === "center" && "text-center",
                  col.align === "right" && "text-right",
                  col.className
                )}
              >
                {col.header}
              </th>
            ))}
          </tr>
        </thead>
        <tbody className="divide-y divide-border/20">
          {data.map((item) => (
            <tr
              key={keyExtractor(item)}
              className={cn(
                "transition-colors hover:bg-muted/20",
                rowClassName?.(item)
              )}
            >
              {columns.map((col) => (
                <td
                  key={col.key}
                  className={cn(
                    "whitespace-nowrap px-3 py-2.5",
                    col.align === "center" && "text-center",
                    col.align === "right" && "text-right",
                    col.className
                  )}
                >
                  {col.render ? col.render(item) : (item as Record<string, unknown>)[col.key] as ReactNode}
                </td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
