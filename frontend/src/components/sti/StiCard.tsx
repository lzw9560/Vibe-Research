import { useState } from "react";
import { Info, ChevronDown, ChevronUp, TrendingUp, TrendingDown, Minus } from "lucide-react";
import { GlassCard } from "@/components/ui/GlassCard";
import { cn } from "@/lib/utils";
import {
  type STIResult,
  PHASE_COLORS,
  getPhaseGradient,
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
  if (change == null) return <Minus className="h-3.5 w-3.5" />;
  if (change > 0) return <TrendingUp className="h-3.5 w-3.5 text-danger" />;
  if (change < 0) return <TrendingDown className="h-3.5 w-3.5 text-success" />;
  return <Minus className="h-3.5 w-3.5 text-muted-foreground" />;
}

function getMomentumText(change: number | null) {
  if (change == null) return "—";
  return `${change > 0 ? "+" : ""}${change.toFixed(1)}`;
}

export function STICard({ data, loading, error, onClick }: Props) {
  const [expanded, setExpanded] = useState(false);

  if (loading) {
    return (
      <GlassCard className="mb-6">
        <div className="flex items-center gap-2">
          <h3 className="text-sm font-semibold text-muted-foreground">情绪温度指数 (STI)</h3>
          <span className="text-xs text-muted-foreground/50">加载中…</span>
        </div>
        <div className="mt-3 h-20 rounded bg-muted/20 animate-pulse" />
      </GlassCard>
    );
  }

  if (error) {
    return (
      <GlassCard className="mb-6">
        <div className="flex items-center gap-2">
          <h3 className="text-sm font-semibold text-muted-foreground">情绪温度指数 (STI)</h3>
        </div>
        <p className="mt-3 text-sm text-destructive/80">{error}</p>
      </GlassCard>
    );
  }

  if (!data || !data.source_ok || data.score === null) {
    return (
      <GlassCard className="mb-6">
        <div className="flex items-center gap-2">
          <h3 className="text-sm font-semibold text-muted-foreground">情绪温度指数 (STI)</h3>
        </div>
        <div className="mt-3 rounded-lg border border-border/40 bg-muted/15 p-4 text-center">
          <p className="text-sm text-muted-foreground">数据未就绪</p>
          <p className="mt-1 text-[11px] text-muted-foreground/50">
            {data?.data_updated ? `上次更新: ${data.data_updated}` : "非交易日或数据源暂不可用"}
          </p>
        </div>
      </GlassCard>
    );
  }

  const phaseColor = PHASE_COLORS[data.phase || ""] || "text-muted-foreground";
  const gradient = getPhaseGradient(data.phase || "");
  const stale = data.data_updated && (() => {
    const updated = new Date(data.data_updated);
    const now = new Date();
    return (now.getTime() - updated.getTime()) > 2 * 86400000;
  })();

  return (
    <GlassCard className="mb-6" onClick={onClick}>
      {/* Header */}
      <div className="mb-3 flex items-center justify-between">
        <div className="flex items-center gap-2">
          <h3 className="text-sm font-semibold text-muted-foreground">情绪温度指数 (STI)</h3>
          {stale && (
            <span className="rounded bg-yellow-500/15 px-2 py-0.5 text-[10px] text-yellow-400">
              数据可能不是最新的
            </span>
          )}
        </div>
        <button
          onClick={(e) => { e.stopPropagation(); setExpanded(!expanded); }}
          className="text-muted-foreground/50 hover:text-muted-foreground"
        >
          {expanded ? <ChevronUp className="h-4 w-4" /> : <ChevronDown className="h-4 w-4" />}
        </button>
      </div>

      {/* Score Display */}
      <div className={cn("rounded-xl bg-gradient-to-br p-5", gradient)}>
        <div className="flex items-end justify-between">
          <div>
            <p className="text-xs text-muted-foreground/70">STI 分数</p>
            <p className={cn("mt-1 text-4xl font-bold", phaseColor)}>
              {data.score.toFixed(1)}
            </p>
          </div>
          <div className="text-right">
            <p className="text-xs text-muted-foreground/70">市场阶段</p>
            <p className={cn("mt-1 text-xl font-bold", phaseColor)}>
              {data.phase}
              {data.phase_explanation && (
                <span className="ml-2 text-xs font-normal opacity-70">{data.phase_explanation}</span>
              )}
            </p>
          </div>
        </div>

        {/* Momentum */}
        <div className="mt-3 flex items-center gap-3 border-t border-white/10 pt-3">
          <div className="flex items-center gap-1.5">
            {getMomentumIcon(data.change_from_yesterday)}
            <span className="text-xs text-muted-foreground/70">较昨日</span>
            <span className={cn(
              "font-mono text-xs font-bold",
              data.change_from_yesterday == null ? "text-muted-foreground" :
              data.change_from_yesterday > 0 ? "text-danger" :
              data.change_from_yesterday < 0 ? "text-success" : "text-muted-foreground"
            )}>
              {getMomentumText(data.change_from_yesterday)}
            </span>
          </div>
          <div className="ml-auto flex items-center gap-1.5 text-xs text-muted-foreground/50">
            <Info className="h-3 w-3" />
            <span>置信度: {data.confidence}</span>
          </div>
        </div>
      </div>

      {/* Expanded Dimensions */}
      {expanded && data.dimensions && (
        <div className="mt-3 space-y-2">
          <p className="text-xs font-medium text-muted-foreground">八维指标明细</p>
          <div className="grid grid-cols-2 gap-2 sm:grid-cols-4">
            {Object.entries(STI_WEIGHTS).map(([key, weight]) => {
              const val = (data.dimensions as any)[key] ?? 0;
              const label = DIMENSION_LABELS[key] || key;
              const isNegative = key === "limit_down_count";
              return (
                <div key={key} className="rounded-lg bg-muted/20 p-2.5">
                  <p className="text-[10px] text-muted-foreground">{label}</p>
                  <p className={cn(
                    "mt-0.5 font-mono text-sm font-bold",
                    isNegative ? (val < 30 ? "text-danger" : val > 70 ? "text-success" : "text-foreground") :
                    val > 70 ? "text-danger" : val < 30 ? "text-success" : "text-foreground"
                  )}>
                    {val.toFixed(1)}
                  </p>
                  <p className="mt-0.5 text-[9px] text-muted-foreground/50">权重 {weight}</p>
                </div>
              );
            })}
          </div>
          {/* Market Factor */}
          <div className="rounded-lg bg-muted/15 p-2.5 text-xs text-muted-foreground/70">
            成交额调节因子: {(data.dimensions as any).market_factor ?? 1.0}
          </div>
        </div>
      )}

      {/* Compliance: 视觉隔离 + 免责声明 + 引导性提示 */}
      <div className="mt-3 border-t border-border/30 pt-3">
        {/* Section divider: 与下方个股数据视觉隔离 */}
        <div className="mb-2 flex items-center gap-2">
          <div className="h-px flex-1 bg-border/40" />
          <span className="text-[10px] uppercase tracking-wider text-muted-foreground/40">市场情绪</span>
          <div className="h-px flex-1 bg-border/40" />
        </div>
        {/* 增强版免责声明（与全局 Disclaimer 同等显著） */}
        <div className="flex items-start gap-1.5 rounded-lg border border-warning/20 bg-warning/[0.03] p-2 text-[11px] leading-relaxed text-muted-foreground/70">
          <Info className="mt-0.5 h-3 w-3 shrink-0 text-warning/60" />
          <span>情绪温度仅为历史统计维度之一，不构成任何操作建议。历史统计特征不代表未来行为。</span>
        </div>
        {/* 引导性提示 */}
        <p className="mt-2 text-[10px] text-muted-foreground/40 italic">
          情绪温度反映的是市场整体统计状态，与具体个股表现无直接因果关系。
        </p>
      </div>
    </GlassCard>
  );
}
