import { type ReactNode } from "react";
import { Search } from "lucide-react";
import { cn } from "@/lib/utils";

interface SearchConfig {
  value: string;
  onChange: (value: string) => void;
  placeholder?: string;
}

interface PillConfig {
  key: string;
  label: string;
  active: boolean;
  onClick: () => void;
}

interface SortConfig {
  value: string;
  onChange: (value: string) => void;
  options: { value: string; label: string }[];
}

interface FilterBarProps {
  search?: SearchConfig;
  pills?: PillConfig[];
  sort?: SortConfig;
  /** 右侧操作槽（刷新按钮等）。 */
  right?: ReactNode;
  className?: string;
}

// 统一筛选条：搜索 + pill 筛选 + 排序 + 右侧操作。
// 全受控——状态由父层持有；本组件只呈现 + 派发 onChange/onClick。
// 设计契约见 specs/S014-前端UI重设计/plan.md §4。
export function FilterBar({ search, pills, sort, right, className }: FilterBarProps) {
  return (
    <div className={cn("flex flex-wrap items-center gap-2", className)}>
      {search && (
        <div className="relative min-w-[180px] flex-1">
          <Search
            className="pointer-events-none absolute left-2.5 top-1/2 h-4 w-4 -translate-y-1/2 text-muted-foreground/60"
            aria-hidden="true"
          />
          <input
            type="text"
            value={search.value}
            onChange={(e) => search.onChange(e.target.value)}
            placeholder={search.placeholder ?? "搜索..."}
            aria-label="搜索"
            className="w-full rounded-lg border border-border/60 bg-muted/20 py-1.5 pl-8 pr-3 text-sm text-foreground placeholder:text-muted-foreground/50 focus:border-primary/50 focus:outline-none focus:ring-1 focus:ring-primary/30"
          />
        </div>
      )}

      {pills && pills.length > 0 && (
        <div className="flex items-center gap-1" role="group" aria-label="筛选">
          {pills.map((p) => (
            <button
              key={p.key}
              type="button"
              onClick={p.onClick}
              aria-pressed={p.active}
              className={cn(
                "rounded-full px-3 py-1 text-xs font-medium transition-colors",
                p.active
                  ? "bg-primary/15 text-primary"
                  : "bg-muted/20 text-muted-foreground hover:bg-muted/30 hover:text-foreground",
              )}
            >
              {p.label}
            </button>
          ))}
        </div>
      )}

      {sort && (
        <select
          value={sort.value}
          onChange={(e) => sort.onChange(e.target.value)}
          aria-label="排序"
          className="rounded-lg border border-border/60 bg-muted/20 px-2.5 py-1.5 text-sm text-foreground focus:border-primary/50 focus:outline-none focus:ring-1 focus:ring-primary/30"
        >
          {sort.options.map((o) => (
            <option key={o.value} value={o.value}>
              {o.label}
            </option>
          ))}
        </select>
      )}

      {right && <div className="ml-auto flex items-center gap-2">{right}</div>}
    </div>
  );
}
