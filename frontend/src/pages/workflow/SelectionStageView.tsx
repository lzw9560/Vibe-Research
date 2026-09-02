// S140 R5 + S146: 选股（forward）语境视图——2 级导航（pipeline | breakout 研究）+ context 降级。
// S146 Round 3：breakout 降级 2 级导航研究（§44 naive lift=1.36x <2x 最弱方向特征，非 standalone edge，
//   后续继续优化）；主 pipeline = 2 并行列（涨停叉 ‖ 非涨停叉）+ ④ 涨停叉内 CV（PipelineFlow 自算，不依赖 useCrossValidationGroups）。
//   echarts graph（PipelineTopology）弃；原始功能组件全保。
import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { api } from "@/lib/api";
import { usePreMarketBriefing } from "@/lib/query";
import { PipelineFlow } from "@/components/pipeline/PipelineFlow";
import { PremarketSelectionSection } from "@/components/workflow/PremarketSelectionSection";
import { CollapsibleFold } from "@/components/ui/CollapsibleFold";
import { GlassCard } from "@/components/ui/GlassCard";
import { ContextTab } from "@/components/workflow/ContextTab";
import { SectionHeader } from "@/components/ui/SectionHeader";
import { WeatherDecisionBar } from "@/components/workflow/WeatherDecisionBar";
import { P2RiskPanel } from "@/components/workflow/P2RiskPanel";
import { WinRateCompareSection } from "@/components/workflow/WinRateCompareSection";
import { EntryCard } from "@/components/workflow/EntryCard";
import { CandidateStateRail } from "@/components/workflow/CandidateStateRail";
import { cn } from "@/lib/utils";

type SubTab = "pipeline" | "breakout";

export function SelectionStageView({ F, forward, urlDate, today }: { F: string; forward: string; urlDate?: string; today?: string }) {
  const { data: briefing, isLoading: briefingLoading } = usePreMarketBriefing(F);
  const { data: advisory } = useQuery({
    queryKey: ["advisory-summary"],  // S094 audit: advisory 是 latest（backend /advisory/summary 不支持 date），非 per-F
    queryFn: () => api.advisorySummary(5),
    staleTime: 5 * 60_000,
    retry: false,
  });
  const recs = advisory?.recommendations ?? [];
  const funnelLayers = briefing?.funnel_layers;
  const [subtab, setSubtab] = useState<SubTab>("pipeline");

  return (
    <>
      {/* rail（顶，常驻——标的状态摘要） */}
      <CandidateStateRail date={today} />

      {/* 前置共享区（顶折叠——context，展开按需） */}
      <PreSharedRegion F={F} briefing={briefing} />

      {/* 2 级导航：选股 pipeline | breakout 因子研究（breakout 降级研究，后续继续优化） */}
      <div className="flex gap-1 rounded-lg bg-muted/20 p-1">
        <button
          type="button"
          onClick={() => setSubtab("pipeline")}
          className={cn("rounded-md px-3 py-1 text-xs font-medium transition-colors",
            subtab === "pipeline" ? "bg-primary/15 text-primary" : "text-muted-foreground hover:text-foreground")}
        >
          选股 pipeline
        </button>
        <button
          type="button"
          onClick={() => setSubtab("breakout")}
          className={cn("rounded-md px-3 py-1 text-xs font-medium transition-colors",
            subtab === "breakout" ? "bg-primary/15 text-primary" : "text-muted-foreground hover:text-foreground")}
        >
          breakout 因子研究
        </button>
      </div>

      {/* S146: 主视图——pipeline（2 列 + ④叉内CV） 或 breakout 研究（PremarketSelectionSection） */}
      {subtab === "pipeline" ? (
        <PipelineFlow briefing={briefing} F={F} funnelLayers={funnelLayers} />
      ) : (
        <BreakoutResearchView forward={forward} />
      )}

      {/* 后置共享区（底折叠——选后动作，降级；defaultOpen=false 修本末倒置） */}
      <PostSharedRegion briefing={briefing} recs={recs} urlDate={urlDate} />

      {briefingLoading && !briefing && (
        <GlassCard className="p-4 text-sm text-muted-foreground">前瞻简报加载中…</GlassCard>
      )}
    </>
  );
}

/** breakout 因子研究视图（2 级导航；§44 naive lift=1.36x <2x 弱信号，后续继续优化该因子） */
function BreakoutResearchView({ forward }: { forward: string }) {
  return (
    <div className="space-y-2">
      <div className="rounded-lg border border-amber-500/40 bg-amber-500/5 p-2.5">
        <div className="flex items-center gap-2">
          <span className="text-sm font-semibold text-amber-300">breakout 因子研究</span>
          <span className="rounded bg-amber-500/20 px-1 text-[10px] text-amber-300">§44 &lt;2x 弱信号</span>
        </div>
        <p className="mt-1 text-[10px] text-amber-200/70">
          naive lift=1.36x（4 方向特征里最弱），非 standalone edge；后续继续优化该因子。前向测试期间不投真金。
        </p>
      </div>
      <PremarketSelectionSection date={forward} />
    </div>
  );
}

/** 前置共享区：板块轮动 · 语境(ContextTab) · 情绪天气(WeatherDecisionBar) */
function PreSharedRegion({ F, briefing }: { F: string; briefing: import("@/lib/api").PreMarketBriefing | null | undefined }) {
  return (
    <CollapsibleFold title="前置共享区" subtitle="板块轮动 · 语境 · 情绪天气" defaultOpen={false}>
      <ContextTab date={F} />
      {briefing?.sentiment_context && (
        <div>
          <SectionHeader title="情绪天气决策" subtitle="S063 情绪天气 → 战法推荐/不推荐" />
          <div className="mt-2">
            <WeatherDecisionBar ctx={briefing.sentiment_context} />
          </div>
        </div>
      )}
    </CollapsibleFold>
  );
}

/** 后置共享区：风控非对称 + P2 仓位 + advisory 摘要 + 战法胜率对比（S146: defaultOpen=false 降级） */
function PostSharedRegion({
  briefing, recs, urlDate,
}: {
  briefing: import("@/lib/api").PreMarketBriefing | null | undefined;
  recs: import("@/lib/api").AdvisoryItem[];
  urlDate?: string;
}) {
  return (
    <CollapsibleFold title="后置共享区" subtitle="风控非对称 · P2 仓位 · 战法胜率 · 仓位推荐" defaultOpen={false}>
      <RiskAsymmetryCard />
      {briefing && <P2RiskPanel briefing={briefing} />}
      {briefing?.factors && briefing.factors.length > 0 && (
        <WinRateCompareSection factors={briefing.factors} onPick={() => {}} />
      )}
      {recs.length > 0 && (
        <GlassCard className="p-4">
          <p className="mb-2 text-sm font-medium">仓位推荐</p>
          <p className="text-xs text-muted-foreground/70">推荐标的 {recs.length} 只</p>
          <div className="mt-2 space-y-1">
            {recs.map((r) => (
              <div key={r.code} className="flex min-w-0 items-center justify-between gap-2 text-xs">
                <span className="min-w-0 flex-1 truncate">{r.name}({r.code})</span>
                <span className="shrink-0 text-right text-muted-foreground/60">
                  {r.matched_strategy ?? "—"} 胜率{r.win_rate != null ? `${(r.win_rate * 100).toFixed(0)}%` : "—"} {r.action}
                </span>
              </div>
            ))}
          </div>
          <div className="mt-3">
            <EntryCard to="/advisory" title="仓位详情" subtitle="PositionAdvisor 推荐/自选/持仓三场景" date={urlDate} />
          </div>
        </GlassCard>
      )}
    </CollapsibleFold>
  );
}

/** 风控非对称卡片（§44 唯一 lever） */
function RiskAsymmetryCard() {
  return (
    <div className="rounded-lg border border-amber-500/40 bg-amber-500/5 p-3">
      <div className="flex items-center justify-between">
        <span className="text-sm font-medium text-amber-300">风控非对称</span>
        <span className="rounded bg-amber-500/20 px-1 text-[10px] text-amber-300">唯一 lever</span>
      </div>
      <div className="mt-1 grid grid-cols-2 gap-x-3 gap-y-0.5 text-[11px] text-muted-foreground sm:grid-cols-3">
        <span>仓位 3% × 日历</span>
        <span>止损 −4%</span>
        <span>止盈 +8%</span>
        <span>max 3 仓</span>
        <span>max 持 3 日</span>
        <span>R:R ≈ 1:2</span>
      </div>
      <div className="mt-1 text-[10px] text-amber-200/70">
        §44 信号全无 validated edge → 盈利靠风控非对称（小仓+紧止损+非对称 R:R+短持），非信号
      </div>
    </div>
  );
}
