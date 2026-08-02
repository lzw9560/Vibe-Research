/** 基因结果表格 */
import { ChevronDown, ChevronUp, Loader2 } from "lucide-react";
import { cn } from "@/lib/utils";
import type { GeneScore } from "@/lib/api";

interface Props {
  data: GeneScore[];
  loading: boolean;
  expandedCode: string | null;
  onToggle: (code: string) => void;
}

const scoreColor = (s: number) => s >= 75 ? "text-primary" : s >= 60 ? "text-blue-400" : "text-gray-400";
const fmtPct = (v: number | null | undefined) => v == null ? "—" : `${v.toFixed(1)}%`;

export function GeneResultTable({ data, loading, expandedCode, onToggle }: Props) {
  if (loading) {
    return (
      <div className="flex items-center justify-center py-8">
        <Loader2 className="h-5 w-5 animate-spin" />
      </div>
    );
  }

  if (data.length === 0) {
    return (
      <div className="py-8 text-center text-sm text-muted-foreground">暂无数据</div>
    );
  }

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
        </div>
      ))}
    </div>
  );
}
