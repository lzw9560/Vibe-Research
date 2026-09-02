// S140 R5：选股（forward）语境视图——从 Workflow.tsx 提取 ForwardTabSection + 专用 helpers。
// 数据源：usePreMarketBriefing(F) + useCrossValidationGroups(F, forward) + advisory summary。
// 工程底线：不臆造——query 无数据返空数组；组件缺数据返 null / "—"。
// 历史统计特征标注：参考值，非执行指令；市场有风险。
import { useQuery } from "@tanstack/react-query";
import { api } from "@/lib/api";
import { usePreMarketBriefing } from "@/lib/query";
import { useCrossValidationGroups } from "@/lib/query/useCrossValidation";
import { PipelineTopology } from "@/components/pipeline/PipelineTopology";
import { CollapsibleFold } from "@/components/ui/CollapsibleFold";
import { GlassCard } from "@/components/ui/GlassCard";
import { ContextTab } from "@/components/workflow/ContextTab";
import { SectionHeader } from "@/components/ui/SectionHeader";
import { WeatherDecisionBar } from "@/components/workflow/WeatherDecisionBar";
import { P2RiskPanel } from "@/components/workflow/P2RiskPanel";
import { WinRateCompareSection } from "@/components/workflow/WinRateCompareSection";
import { EntryCard } from "@/components/workflow/EntryCard";
import { CrossValidationBadge } from "@/components/workflow/CrossValidationBadge";
import { CandidateStateRail } from "@/components/workflow/CandidateStateRail";

// 涨停叉：① 涨停股池+漏斗 → ② 战法匹配（7战法分组视图）→ ③ breakout → ④ 交叉验证
// 非涨停叉：⑤ 选股宇宙 → ⑥ K线形态 → ⑦ 非涨停战法分组视图 → ⑧ 候选终选
// graph 显示双叉（不再互斥切换）——②⑦ 金框节点 click 展开战法分组 inline。

export function SelectionStageView({ F, forward, urlDate, today }: { F: string; forward: string; urlDate?: string; today?: string }) {
  // 数据源：前瞻简报（F 日收盘数据算出来的选 T+1 标的结果）
  const { data: briefing, isLoading: briefingLoading } = usePreMarketBriefing(F);
  // 交叉验证：漏斗 final_candidates ∩ breakout top-N
  const cv = useCrossValidationGroups(F, forward);
  // advisory 仓位推荐摘要
  const { data: advisory } = useQuery({
    queryKey: ["advisory-summary"],  // S094 audit: advisory 是 latest（backend /advisory/summary 不支持 date），非 per-F
    queryFn: () => api.advisorySummary(5),
    staleTime: 5 * 60_000,
    retry: false,
  });
  const recs = advisory?.recommendations ?? [];

  const funnelLayers = briefing?.funnel_layers;

  return (
    <>
      {/* ============ 标的 7 态常驻 rail（S140 R6，date=triplet.today） ============ */}
      <CandidateStateRail date={today} />

      {/* ============ 前置共享区（辅助角色，顶部折叠态——展开才看详情） ============ */}
      <PreSharedRegion F={F} briefing={briefing} />

      {/* ============ 拓扑主视图（echarts graph ①~⑧，默认收缩——展开才看 graph） ============ */}
      <CollapsibleFold title="pipeline 拓扑" subtitle="①~⑧ echarts graph" defaultOpen={false}>
        <PipelineTopology
          briefing={briefing}
          F={F}
          forward={forward}
          funnelLayers={funnelLayers}
          cv={cv}
        />
      </CollapsibleFold>

      {/* ============ ④ 交叉验证（folded——CrossValidationSummary 随 SelectionStageView 一并迁出，S140 R5） ============ */}
      <CollapsibleFold title="④ 交叉验证" subtitle="漏斗 ∩ breakout" defaultOpen={false}>
        <CrossValidationSummary groups={cv} />
      </CollapsibleFold>

      {/* ============ 后置共享区：风控 + P2 仓位（advisory 摘要并入） ============ */}
      <PostSharedRegion briefing={briefing} recs={recs} urlDate={urlDate} />

      {briefingLoading && !briefing && (
        <GlassCard className="p-4 text-sm text-muted-foreground">前瞻简报加载中…</GlassCard>
      )}
    </>
  );
}

/** 前置共享区：板块轮动 · 语境(ContextTab) · 情绪天气(WeatherDecisionBar) */
function PreSharedRegion({ F, briefing }: { F: string; briefing: import("@/lib/api").PreMarketBriefing | null | undefined }) {
  return (
    <CollapsibleFold title="前置共享区" subtitle="板块轮动 · 语境 · 情绪天气" defaultOpen={false}>
      {/* 板块轮动（只渲染一个实例，见 SelectionPipeline 内 sharedSectorRotation=true 跳过内部渲染） */}
      <ContextTab date={F} />
      {/* 情绪天气（WeatherDecisionBar）— 天气影响选股决策 */}
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

/** 后置共享区：风控非对称 + P2 仓位 + advisory 摘要 + 战法胜率对比（并入此区，不重复展示） */
function PostSharedRegion({
  briefing, recs, urlDate,
}: {
  briefing: import("@/lib/api").PreMarketBriefing | null | undefined;
  recs: import("@/lib/api").AdvisoryItem[];
  urlDate?: string;
}) {
  return (
    <CollapsibleFold title="后置共享区" subtitle="风控非对称 · P2 仓位 · 战法胜率 · 仓位推荐" defaultOpen={true}>
      {/* 风控非对称（§44 唯一 lever：亏小赚大） */}
      <RiskAsymmetryCard />

      {/* P2 仓位闸 + 龙虎榜风控面板 */}
      {briefing && <P2RiskPanel briefing={briefing} />}

      {/* 战法胜率对比（S093 抽出后首次接入——60 日回测胜率 × 各战法） */}
      {briefing?.factors && briefing.factors.length > 0 && (
        <WinRateCompareSection factors={briefing.factors} onPick={() => {}} />
      )}

      {/* advisory 仓位推荐（并入后置共享区，显示全部推荐标的） */}
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
          {/* advisory 仓位详情入口（并入后置共享区，独立页 /advisory 保留为详情入口） */}
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

/** 交叉验证摘要——三组富对象列表 + 详情行（股票名/战法/分数）+ 徽章（spec R4④ + AC9） */
function CrossValidationSummary({ groups }: { groups: import("@/lib/query/useCrossValidation").CrossValidationGroups }) {
  if (groups.isLoading) {
    return <GlassCard className="mb-3 p-4 text-sm text-muted-foreground">交叉验证计算中…</GlassCard>;
  }
  const hasData = groups.dual.length > 0 || groups.funnelOnly.length > 0 || groups.breakoutOnly.length > 0;
  if (!hasData) return null;

  const groupConfig = [
    { key: "dual" as const, items: groups.dual, variant: "success" as const, label: "双重确认", desc: "漏斗 ∩ breakout", icon: "✓✓" },
    { key: "funnelOnly" as const, items: groups.funnelOnly, variant: "default" as const, label: "仅漏斗", desc: "漏斗有 · breakout 无", icon: "◆" },
    { key: "breakoutOnly" as const, items: groups.breakoutOnly, variant: "default" as const, label: "仅 breakout", desc: "breakout 有 · 漏斗无", icon: "◇" },
  ];

  return (
    <GlassCard className="mb-3 p-4">
      <div className="flex items-center gap-2 border-b border-border/30 pb-2">
        <span className="text-sm font-semibold">交叉验证</span>
        <span className="text-xs text-muted-foreground/70">漏斗 ∩ breakout · {groups.dual.length} 双重确认</span>
      </div>
      <div className="mt-3 space-y-3">
        {groupConfig.map((g) => g.items.length > 0 && (
          <div key={g.key}>
            {/* 组标题 */}
            <div className="mb-1.5 flex items-center gap-2">
              <CrossValidationBadge group={g.key} />
              <span className="text-xs text-muted-foreground/70">{g.desc}</span>
              <span className="text-xs font-bold tabular-nums text-foreground">{g.items.length} 只</span>
            </div>
            {/* 详情行列表 */}
            <div className="space-y-1">
              {g.items.map((item) => (
                <div key={item.code} className="flex items-center justify-between gap-2 rounded border border-border/20 bg-card/10 px-2 py-1 text-xs">
                  <div className="flex min-w-0 flex-1 items-center gap-1.5">
                    <span className={`shrink-0 ${g.variant === "success" ? "text-green-500" : "text-muted-foreground/50"}`}>{g.icon}</span>
                    <span className="truncate font-medium text-foreground">{item.name}</span>
                    <span className="shrink-0 font-mono text-[10px] text-muted-foreground/60">{item.code}</span>
                    {item.strategyName && (
                      <span className="shrink-0 rounded bg-muted/30 px-1 text-[10px] text-muted-foreground/80">{item.strategyName}</span>
                    )}
                  </div>
                  <div className="flex shrink-0 items-center gap-2 font-mono text-[10px] tabular-nums text-muted-foreground/70">
                    {item.geneScore != null && <span>基因 {item.geneScore.toFixed(1)}</span>}
                    {item.strategyScore != null && <span>战法 {item.strategyScore.toFixed(1)}</span>}
                    {item.breakoutScore != null && <span>breakout {item.breakoutScore.toFixed(2)}</span>}
                  </div>
                </div>
              ))}
            </div>
          </div>
        ))}
      </div>
      <p className="mt-2 text-[10px] text-muted-foreground/60">参考值，非执行指令；市场有风险</p>
    </GlassCard>
  );
}
