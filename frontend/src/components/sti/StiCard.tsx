import { useState } from "react";
import { Info, ChevronDown, ChevronUp, TrendingUp, TrendingDown, Minus } from "lucide-react";
import { GlassCard } from "@/components/ui/GlassCard";
import { Badge } from "@/components/ui/Badge";
import { cn } from "@/lib/utils";
import {
  type STIResult,
  PHASE_COLORS,
  STI_WEIGHTS,
  DIMENSION_LABELS,
} from "./types";

interface Props {
  data: STIResult | null;
  loading: boolean;
  error: string | null;
  onClick: () => void;
}

function getMomentumIcon(change: number | null) {
  if (change == null) return <Minus className="h-3 w-3" />;
  if (change > 0) return <TrendingUp className="h-3 w-3 text-danger" />;
  if (change < 0) return <TrendingDown className="h-3 w-3 text-success" />;
  return <Minus className="h-3 w-3 text-foreground/50" />;
}

function getMomentumText(change: number | null) {
  if (change == null) return "—";
  return `${change > 0 ? "+" : ""}${change.toFixed(1)}`;
}

export function STICard({ data, loading, error, onClick }: Props) {
  const [expanded, setExpanded] = useState(false);

  if (loading) {
    return (
      <GlassCard className="mb-4">
        <div className="flex items-center gap-2">
          <h3 className="text-xs font-medium text-foreground/80">情绪温度指数 (STI)</h3>
          <span className="text-[10px] text-foreground/50">加载中…</span>
        </div>
        <div className="mt-2 h-12 rounded bg-foreground/10 animate-pulse" />
      </GlassCard>
    );
  }

  if (error) {
    return (
      <GlassCard className="mb-4">
        <div className="flex items-center gap-2">
          <h3 className="text-xs font-medium text-foreground/80">情绪温度指数 (STI)</h3>
        </div>
        <p className="mt-2 text-xs text-danger/80">{error}</p>
      </GlassCard>
    );
  }

  if (!data || !data.source_ok || data.score === null) {
    return (
      <GlassCard className="mb-4">
        <div className="flex items-center gap-2">
          <h3 className="text-xs font-medium text-foreground/80">情绪温度指数 (STI)</h3>
        </div>
        <div className="mt-2 rounded-lg border border-border bg-foreground/5 p-3 text-center">
          <p className="text-xs text-foreground/70">数据未就绪</p>
          <p className="mt-0.5 text-[10px] text-foreground/50">
            {data?.data_updated ? `上次更新: ${data.data_updated}` : "非交易日或数据源暂不可用"}
          </p>
        </div>
      </GlassCard>
    );
  }

  const phaseColor = PHASE_COLORS[data.phase || ""] || "text-foreground";
  const stale = data.data_updated && (() => {
    const updated = new Date(data.data_updated);
    const now = new Date();
    return (now.getTime() - updated.getTime()) > 2 * 86400000;
  })();

  return (
    <GlassCard className="mb-4 cursor-pointer" onClick={onClick}>
      {/* Header */}
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-2">
          <h3 className="text-xs font-medium text-foreground/80">情绪温度指数 (STI)</h3>
          {stale && (
            <span className="rounded bg-warning/15 px-1.5 py-0.5 text-[9px] text-warning">
              数据可能不是最新的
            </span>
          )}
        </div>
        <button
          onClick={(e) => { e.stopPropagation(); setExpanded(!expanded); }}
          className="text-foreground/50 hover:text-foreground"
        >
          {expanded ? <ChevronUp className="h-3.5 w-3.5" /> : <ChevronDown className="h-3.5 w-3.5" />}
        </button>
      </div>

      {/* Score Display - Compact */}
      <div className="mt-2 flex items-center justify-between">
        <div className="flex items-baseline gap-2">
          <span className={`text-2xl font-bold tabular-nums ${phaseColor}`}>
            {data.score.toFixed(1)}
          </span>
          <span className="text-xs text-foreground/50">/ 100</span>
        </div>
        <div className="flex items-center gap-2">
          <span className={`text-sm font-medium ${phaseColor}`}>
            {data.phase}
          </span>
          <Badge variant="default" className="text-[10px] h-5">
            {data.phase_explanation || "历史统计"}
          </Badge>
        </div>
      </div>

      {/* Compact Gauge */}
      <div className="mt-2 h-1.5 rounded-full bg-foreground/10 overflow-hidden">
        <div
          className="h-full rounded-full bg-gradient-to-r from-blue-500 via-green-500 via-yellow-500 to-red-500 transition-all duration-500"
          style={{ width: `${Math.min(100, Math.max(0, data.score))}%` }}
        />
      </div>

      {/* Momentum */}
      <div className="mt-2 flex items-center gap-2 text-[10px] text-foreground/50">
        <div className="flex items-center gap-1">
          {getMomentumIcon(data.change_from_yesterday)}
          <span>较昨日</span>
          <span className="font-mono">
            {getMomentumText(data.change_from_yesterday)}
          </span>
        </div>
        <span>·</span>
        <span>置信度: {data.confidence}</span>
        {data.data_updated && (
          <>
            <span>·</span>
            <span>{data.data_updated}</span>
          </>
        )}
      </div>

      {/* Expanded Dimensions */}
      {expanded && data.dimensions && (
        <div className="mt-3 space-y-2">
          <p className="text-[10px] font-medium text-foreground/70">八维指标明细</p>
          <div className="grid grid-cols-2 gap-1.5 sm:grid-cols-4">
            {Object.entries(STI_WEIGHTS).map(([key, weight]) => {
              const val = (data.dimensions as any)[key] ?? 0;
              const label = DIMENSION_LABELS[key] || key;
              const isNegative = key === "limit_down_count";
              return (
                <div key={key} className="rounded-lg bg-foreground/5 p-2 border border-foreground/5">
                  <p className="text-[9px] text-foreground/70">{label}</p>
                  <p className={cn(
                    "mt-0.5 font-mono text-xs font-bold",
                    isNegative ? (val < 30 ? "text-danger" : val > 70 ? "text-success" : "text-foreground") :
                    val > 70 ? "text-danger" : val < 30 ? "text-success" : "text-foreground"
                  )}>
                    {val.toFixed(1)}
                  </p>
                  <p className="mt-0.5 text-[8px] text-foreground/40">权重 {weight}</p>
                </div>
              );
            })}
          </div>
          <div className="rounded-lg bg-foreground/5 p-2 text-[10px] text-foreground/60 border border-foreground/5">
            成交额调节因子: {(data.dimensions as any).market_factor ?? 1.0}
          </div>
        </div>
      )}

      {/* Compliance: 视觉隔离 + 免责声明 + 引导性提示 */}
      <div className="mt-2 pt-2 border-t border-border/50">
        <div className="flex items-center gap-1">
          <Info className="h-2.5 w-2.5 text-foreground/30" />
          <span className="text-[9px] text-foreground/30">
            情绪温度仅为历史统计维度之一，不构成任何操作建议。历史统计特征不代表未来行为。
          </span>
        </div>
      </div>
    </GlassCard>
  );
}
