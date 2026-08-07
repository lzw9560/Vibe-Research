import { cn } from "@/lib/utils";

interface Props {
  strategies: string[];
  selected: Set<string>;
  onChange: (next: Set<string>) => void;
  className?: string;
}

/** S031 R19：战法多选 chips（8 大战法 + "全部"）——反筛纯前端，不请求后端。
 * 选"全部"清空 selected 恢复；点已选战法移除、未选加入。 */
export function StrategyFilter({ strategies, selected, onChange, className }: Props) {
  const toggle = (s: string) => {
    const next = new Set(selected);
    if (next.has(s)) next.delete(s);
    else next.add(s);
    onChange(next);
  };

  return (
    <div className={cn("flex flex-wrap items-center gap-1", className)} role="group" aria-label="战法筛选">
      <button
        type="button"
        onClick={() => onChange(new Set())}
        aria-pressed={selected.size === 0}
        className={cn(
          "rounded-full px-3 py-1 text-xs font-medium transition-colors",
          selected.size === 0
            ? "bg-primary/15 text-primary"
            : "bg-muted/20 text-muted-foreground hover:bg-muted/30 hover:text-foreground",
        )}
      >
        全部
      </button>
      {strategies.map((s) => (
        <button
          key={s}
          type="button"
          onClick={() => toggle(s)}
          aria-pressed={selected.has(s)}
          className={cn(
            "rounded-full px-3 py-1 text-xs font-medium transition-colors",
            selected.has(s)
              ? "bg-primary/15 text-primary"
              : "bg-muted/20 text-muted-foreground hover:bg-muted/30 hover:text-foreground",
          )}
        >
          {s}
        </button>
      ))}
    </div>
  );
}
