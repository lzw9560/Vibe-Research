/** 全球市场 */
import { GlassCard } from "@/components/ui/GlassCard";
import { pctColor } from "@/lib/utils";
import { Globe } from "lucide-react";
import { cn } from "@/lib/utils";
import type { GlobalIndex } from "@/lib/api";

interface Props { globalIdx: GlobalIndex[] }
export function GlobalMarket({ globalIdx }: Props) {
  if (globalIdx.length === 0) return null;
  return (
    <>
      <div className="mb-3 flex items-center gap-2">
        <h3 className="flex items-center gap-1.5 text-sm font-semibold text-muted-foreground"><Globe className="h-4 w-4" /> 全球市场</h3>
        <span className="text-[11px] text-muted-foreground/50">隔夜外围 · A 股常看美股 / 港股脸色</span>
      </div>
      <div className="mb-6 grid grid-cols-2 gap-3 sm:grid-cols-5">
        {globalIdx.map((g) => (
          <GlassCard key={g.key} className="p-3">
            <p className="truncate text-xs text-muted-foreground">{g.name} <span className="text-muted-foreground/40">{g.region}</span></p>
            <p className={cn("mt-1 font-mono text-lg font-bold", g.change_pct == null ? "text-foreground" : pctColor(g.change_pct))}>{g.price ?? "—"}</p>
            <p className={cn("text-xs", g.change_pct == null ? "text-muted-foreground" : pctColor(g.change_pct))}>
              {g.change_pct == null ? "—" : `${g.change_pct > 0 ? "+" : ""}${g.change_pct}%`}
            </p>
          </GlassCard>
        ))}
      </div>
    </>
  );
}
