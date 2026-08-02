/** 可展开表格 */
import { ChevronDown, ChevronUp, Loader2 } from "lucide-react";
import { GlassCard } from "@/components/ui/GlassCard";
import { cn } from "@/lib/utils";
import type { GeneScore, LimitUpAnalysis } from "@/lib/api";

interface Props {
  data: GeneScore[];
  expandedCode: string | null;
  expandedData: LimitUpAnalysis | null;
  expandedLoading: boolean;
  expandedError: string | null;
  onToggle: (code: string) => void;
}

const scoreColor = (s: number) => s >= 75 ? "text-primary" : s >= 60 ? "text-blue-400" : "text-gray-400";
const fmtPct = (v: number | null | undefined) => v == null ? "—" : `${v.toFixed(1)}%`;

export function ExpandableTable({ data, expandedCode, expandedData, expandedLoading, expandedError, onToggle }: Props) {
  return (
    <div className="space-y-2">
      {data.map((row) => (
        <div key={row.code}>
          <button
            onClick={() => onToggle(row.code)}
            className="w-full flex items-center gap-3 rounded-lg border border-border/30 p-3 text-left hover:bg-muted/20 transition-colors"
          >
            <span className="w-6 text-xs text-muted-foreground/50">{row.code}</span>
            <span className="flex-1 font-medium">{row.name}</span>
            <span className={cn("font-mono font-bold", scoreColor(row.total_score))}>{row.total_score}</span>
            <span className="text-xs text-muted-foreground">溢价{fmtPct(row.factors["次日溢价率"])}</span>
            {expandedCode === row.code ? <ChevronUp className="h-4 w-4" /> : <ChevronDown className="h-4 w-4" />}
          </button>
          
          {expandedCode === row.code && (
            <div className="mt-2 ml-8 space-y-3">
              {expandedLoading ? (
                <div className="flex items-center justify-center py-4"><Loader2 className="h-5 w-5 animate-spin" /></div>
              ) : expandedError ? (
                <div className="py-2 text-sm text-destructive">{expandedError}</div>
              ) : expandedData ? (
                <div className="space-y-3">
                  {/* 基因得分雷达图 */}
                  <div className="h-[200px] rounded-lg bg-muted/20" />
                  {/* 统计卡片 */}
                  <div className="grid gap-2 sm:grid-cols-3">
                    <GlassCard className="p-3">
                      <p className="text-xs text-muted-foreground">样本数</p>
                      <p className="mt-1 text-xl font-bold">{(expandedData as any).total ?? "—"}</p>
                    </GlassCard>
                    <GlassCard className="p-3">
                      <p className="text-xs text-muted-foreground">连板率</p>
                      <p className="mt-1 text-xl font-bold text-primary">
                        {(() => {
                          const t = (expandedData as any).total ?? 0;
                          const lc = (expandedData as any).lianban_count ?? 0;
                          return t > 0 ? `${((lc / t) * 100).toFixed(0)}%` : "—";
                        })()}
                      </p>
                    </GlassCard>
                    <GlassCard className="p-3">
                      <p className="text-xs text-muted-foreground">连板均分</p>
                      <p className="mt-1 text-xl font-bold text-primary">{(expandedData as any).avg_score_lianban ?? "—"}</p>
                    </GlassCard>
                  </div>
                </div>
              ) : null}
            </div>
          )}
        </div>
      ))}
    </div>
  );
}
