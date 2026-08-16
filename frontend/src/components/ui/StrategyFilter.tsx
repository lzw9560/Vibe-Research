import { cn } from "@/lib/utils";

interface Props {
  strategies: string[];
  selected: Set<string>;
  onChange: (next: Set<string>) => void;
  className?: string;
  // S058：天气适配度软过滤——传入则每战法 chip 后挂适配/不适配/中性标签
  weatherFit?: Record<string, "适配" | "不适配" | "中性">;
  /** grill Q7：天气推荐战法集合——推荐战法 chip 加绿色「★」徽标（软标注，不过滤）。 */
  weatherRecommended?: Set<string>;
}

/** S031 R19：战法多选 chips（8 大战法 + "全部"）——反筛纯前端，不请求后端。
 * 选"全部"清空 selected 恢复；点已选战法移除、未选加入。
 * S058：weatherFit 传入时，不适配战法降权（chip 淡化 + 标注「不适配」）。
 * grill Q7：weatherRecommended 传入时，推荐战法 chip 加绿色「★」（所有战法仍可选）。 */
export function StrategyFilter({ strategies, selected, onChange, className, weatherFit, weatherRecommended }: Props) {
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
      {strategies.map((s) => {
        const fit = weatherFit?.[s];
        const isUnfit = fit === "不适配";
        return (
          <button
            key={s}
            type="button"
            onClick={() => toggle(s)}
            aria-pressed={selected.has(s)}
            className={cn(
              "rounded-full px-3 py-1 text-xs font-medium transition-colors inline-flex items-center gap-1",
              selected.has(s)
                ? "bg-primary/15 text-primary"
                : isUnfit
                  ? "bg-muted/10 text-muted-foreground/50 hover:bg-muted/20"
                  : "bg-muted/20 text-muted-foreground hover:bg-muted/30 hover:text-foreground",
            )}
          >
            {s}
            {weatherRecommended?.has(s) && (
              <span className="text-[10px] text-emerald-500" aria-label="天气推荐">★</span>
            )}
            {fit && fit !== "中性" && (
              <span className={cn(
                "text-[10px]",
                fit === "适配" ? "text-emerald-500" : "text-amber-500",
              )}>
                {fit}
              </span>
            )}
          </button>
        );
      })}
    </div>
  );
}
