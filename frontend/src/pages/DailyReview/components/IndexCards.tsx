/** 大盘指数卡片 */
import { GlassCard } from "@/components/ui/GlassCard";
import { pctColor, cn } from "@/lib/utils";
import { RefreshCw } from "lucide-react";
import type { IndexQuote } from "@/lib/api";

interface Props {
  indices: IndexQuote[];
  idxErr: boolean;
  onRefresh: () => void;
}
export function IndexCards({ indices, idxErr, onRefresh }: Props) {
  return (
    <>
      <div className="mb-3 flex items-center justify-between">
        <h3 className="text-sm font-semibold text-muted-foreground">大盘指数</h3>
        <button onClick={onRefresh} className="text-muted-foreground hover:text-primary" title="刷新">
          <RefreshCw className="h-3.5 w-3.5" />
        </button>
      </div>
      <div className="mb-6 grid grid-cols-2 gap-3 sm:grid-cols-4">
        {indices.length === 0
          ? [1, 2, 3, 4].map((i) => (
              <GlassCard key={i} className="p-3">
                <p className="text-xs text-muted-foreground">{idxErr ? "行情未接通" : "加载中…"}</p>
                <p className="mt-1 font-mono text-lg font-bold text-muted-foreground/40">—</p>
              </GlassCard>
            ))
          : indices.map((i) => (
              <GlassCard key={i.name} className="p-3">
                <p className="truncate text-xs text-muted-foreground">{i.name}</p>
                <p className={cn("mt-1 font-mono text-lg font-bold", pctColor(i.change_pct))}>{i.price}</p>
                <p className={cn("text-xs", pctColor(i.change_pct))}>{i.change_pct > 0 ? "+" : ""}{i.change_pct}%</p>
              </GlassCard>
            ))}
      </div>
    </>
  );
}
