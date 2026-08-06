/** 基因结果表格（S029：可展开多层明细 A3）。
 *  每行 expand → 五维 factors + qualify/high 标记 + 回测摘要 + qualified 行跳候选详情（看战法/仓位）。
 */
import { ChevronDown, ChevronUp, Loader2 } from "lucide-react";
import { Link } from "react-router-dom";
import { cn } from "@/lib/utils";
import type { GeneScore } from "@/lib/api";

interface Props {
  data: GeneScore[];
  loading: boolean;
  expandedCode: string | null;
  onToggle: (code: string) => void;
}

const scoreColor = (s: number) => (s >= 75 ? "text-primary" : s >= 60 ? "text-blue-400" : "text-gray-400");
const fmtPct = (v: number | null | undefined) => (v == null ? "—" : `${v.toFixed(1)}%`);

// 五维口径（后端 calc_total_score 权重）
const FACTOR_ROWS: Array<{ key: string; weight: string }> = [
  { key: "次日溢价率", weight: "25%" },
  { key: "红盘率", weight: "25%" },
  { key: "封板率", weight: "25%" },
  { key: "炸板后溢价", weight: "15%" },
  { key: "涨停频次", weight: "10%" },
];

function ExpandedDetail({ row }: { row: GeneScore }) {
  const bs = row.backtest_summary;
  return (
    <div className="mt-2 space-y-2 rounded-lg bg-muted/10 p-3 text-xs">
      {/* 标记 */}
      <div className="flex flex-wrap items-center gap-1.5">
        {row.qualify && (
          <span className="rounded bg-blue-500/15 px-1.5 py-0.5 text-blue-400">合格</span>
        )}
        {row.high_gene && (
          <span className="rounded bg-primary/15 px-1.5 py-0.5 text-primary">高基因</span>
        )}
        <span className="text-muted-foreground">
          250日涨停 {row.zt_count_250d} 次 · wilson {row.wilson_adjusted}
        </span>
      </div>

      {/* 五维明细 */}
      <div>
        <div className="mb-1 text-muted-foreground/70">五维因子（权重）</div>
        <div className="grid grid-cols-2 gap-x-4 gap-y-0.5 sm:grid-cols-3">
          {FACTOR_ROWS.map(({ key, weight }) => (
            <div key={key} className="flex justify-between">
              <span className="text-muted-foreground">
                {key} <span className="text-muted-foreground/50">({weight})</span>
              </span>
              <span className="font-mono">{fmtPct(row.factors[key])}</span>
            </div>
          ))}
        </div>
      </div>

      {/* 回测摘要 */}
      {bs && bs.samples > 0 && (
        <div className="text-muted-foreground/70">
          回测：{bs.samples} 样本 · 连板率 {fmtPct(bs.lianban_rate)}
          {bs.avg_score_lianban != null && <> · 连板均分 {bs.avg_score_lianban}</>}
        </div>
      )}

      {/* 最近涨停日 */}
      {row.last_zt_dates?.length > 0 && (
        <div className="text-muted-foreground/70">最近涨停：{row.last_zt_dates.slice(0, 5).join("、")}</div>
      )}

      {/* qualified 行：看战法/仓位（跳候选详情，S028 已修 Lazy bug） */}
      {row.qualify && (
        <div>
          <Link
            to={`/workflow/candidates/${row.code}`}
            className="text-primary underline-offset-2 hover:underline"
          >
            看战法匹配 / 仓位建议 →
          </Link>
        </div>
      )}
    </div>
  );
}

export function GeneResultTable({ data, loading, expandedCode, onToggle }: Props) {
  if (loading) {
    return (
      <div className="flex items-center justify-center py-8">
        <Loader2 className="h-5 w-5 animate-spin" />
      </div>
    );
  }

  if (data.length === 0) {
    return <div className="py-8 text-center text-sm text-muted-foreground">暂无数据</div>;
  }

  return (
    <div className="space-y-2">
      {data.map((row) => {
        const expanded = expandedCode === row.code;
        return (
          <div key={row.code} className="rounded-lg border border-border/30 bg-card/30">
            <button
              onClick={() => onToggle(row.code)}
              className="flex w-full items-center gap-3 p-3 text-left transition-colors hover:bg-muted/20"
            >
              <span className="w-6 text-xs text-muted-foreground/50">{row.code}</span>
              <span className="flex-1 font-medium">{row.name}</span>
              <span className="text-xs text-muted-foreground">溢价{fmtPct(row.factors["次日溢价率"])}</span>
              <span className={cn("font-mono font-bold", scoreColor(row.total_score))}>{row.total_score}</span>
              {expanded ? <ChevronUp className="h-4 w-4" /> : <ChevronDown className="h-4 w-4" />}
            </button>
            {expanded && <div className="px-3 pb-3"><ExpandedDetail row={row} /></div>}
          </div>
        );
      })}
    </div>
  );
}
