// S146: 选股 pipeline 流——2 并行列（涨停叉 ‖ 非涨停叉）+ ④ 涨停叉内交叉验证。
// 取代 PipelineTopology 的 echarts graph。breakout 降级 2 级导航研究（§44 naive lift=1.36x <2x，4 方向特征里最弱，
// 非可信 standalone edge，移 SelectionStageView 2 级导航研究 tab）。
// 交叉验证（原 ④叉内 CV: finals∩scored）已删——两 <2x 弱信号交集无 validated edge（§44），且 scored⊆finals 非真双路。
// 保：CandidateFunnelEmbed(①) / StrategySubPipelineView(②战法匹配)
//     / CandidateFactorTable(★候选因子表) / NonLimitupLane(⑤⑥⑧非涨停叉)。
import { useState, type ReactNode } from "react";
import { useNavigate } from "react-router-dom";
import { cn } from "@/lib/utils";
import { StrategySubPipelineView } from "./StrategySubPipelineView";
import { NonLimitupLane } from "./NonLimitupPlaceholder";
import CandidateFunnelEmbed from "@/components/workflow/CandidateFunnelEmbed";
import { CandidateFactorTable } from "@/components/workflow/CandidateFactorTable";
import type { PreMarketBriefing, FunnelLayer } from "@/lib/api";

interface Props {
  briefing: PreMarketBriefing | null | undefined;
  F: string;
  funnelLayers: FunnelLayer[] | undefined;
}

/** 紧凑步骤卡：头（步骤号 + 标题 + 计数）+ 展开态（原始组件，默认折叠——流串着可见、组件按需展开）。 */
function PipelineStep({
  step, title, count, sub, defaultOpen = false, children,
}: {
  step: string;
  title: string;
  count?: number | string;
  sub?: string;
  defaultOpen?: boolean;
  children?: ReactNode;
}) {
  const [open, setOpen] = useState(defaultOpen);
  const hasChildren = !!children;
  return (
    <div className="rounded-lg border border-border/40 bg-card/40 p-2.5">
      <button
        type="button"
        onClick={hasChildren ? () => setOpen((v) => !v) : undefined}
        className={cn("flex w-full items-center gap-2 text-left", !hasChildren && "cursor-default")}
      >
        <span className="flex h-5 w-5 shrink-0 items-center justify-center rounded-full bg-primary/15 text-[10px] font-bold text-primary">{step}</span>
        <div className="min-w-0 flex-1">
          <span className="truncate text-xs font-medium">{title}</span>
          {sub && <span className="ml-1.5 text-[10px] text-muted-foreground/60">{sub}</span>}
        </div>
        {count != null && <span className="shrink-0 font-mono text-[11px] tabular-nums text-muted-foreground">{count}</span>}
        {hasChildren && (
          <span className={cn("shrink-0 text-[10px] text-muted-foreground/50 transition-transform", open && "rotate-90")}>▶</span>
        )}
      </button>
      {open && hasChildren && <div className="mt-2">{children}</div>}
    </div>
  );
}


/** 选股 pipeline 流（2 并行列 + ④ 涨停叉内 CV；breakout 移 2 级导航研究）。 */
export function PipelineFlow({ briefing, F, funnelLayers }: Props) {
  const navigate = useNavigate();
  const scored = briefing?.scored_candidates ?? [];
  const marketScan = briefing?.market_scan_scored ?? [];
  const finals = briefing?.final_candidates ?? [];
  const ztCount = briefing?.market_emotion?.zt_count ?? undefined;
  const dataDate = briefing?.data_date ?? F;

  return (
    <div className="space-y-2">
      {/* 2 并行列（涨停叉 ‖ 非涨停叉；breakout 移 2 级导航研究，非主 pipeline peer lane） */}
      <div className="grid gap-2 lg:grid-cols-2 items-start">
        {/* 涨停叉 */}
        <div className="space-y-2 border-l-2 border-primary/30 pl-2">
          <p className="text-[10px] font-semibold text-primary/70">涨停叉</p>
          {/* ① 涨停股池+漏斗——CandidateFunnelEmbed */}
          <PipelineStep
            step="①"
            title="涨停股池+漏斗"
            sub="CandidateFunnelEmbed"
            count={ztCount ?? finals.length}
          >
            <CandidateFunnelEmbed
              date={dataDate}
              onPick={(code) => navigate(`/stock/${code}`)}
              snapshotLayers={funnelLayers}
              scoredCandidates={scored}
              marketScanScored={marketScan}
              finalCandidates={finals}
              ztPoolSize={ztCount}
              sharedSectorRotation={true}
            />
          </PipelineStep>
          {/* ② 战法匹配——StrategySubPipelineView（limitup lane；relabel 去"因子"防误导） */}
          <PipelineStep step="②" title="战法匹配" sub="7 战法分组" count={scored.length}>
            <StrategySubPipelineView scoredCandidates={scored} marketScanScored={marketScan} lane="limitup" scoredTotal={scored.length} />
          </PipelineStep>
          {/* ★ 候选因子表——CandidateFactorTable（八项标准+量价/资金+基因因子，DiagnosisCard 形状） */}
          <PipelineStep step="★" title="候选因子表" sub="基因分 · 八项标准 · 量价/资金" count={finals.length}>
            <CandidateFactorTable candidates={finals} date={dataDate} />
          </PipelineStep>
        </div>

        {/* 非涨停叉（⑧ 候选终选为 ScoredCandidate 简表——无八项标准/gene_score 数据形状，不硬塞全"—"的因子表，诚实留简表） */}
        <div className="space-y-2 border-l-2 border-muted/40 pl-2">
          <p className="text-[10px] font-semibold text-muted-foreground/70">非涨停叉</p>
          {/* ⑤⑥⑦⑧ 非涨停叉——NonLimitupLane（自管四节点） */}
          <PipelineStep step="⑤⑥⑦⑧" title="非涨停叉" sub="选股宇宙 · K线 · 战法 · 候选终选" count={marketScan.length}>
            <NonLimitupLane date={dataDate} candidates={marketScan} />
          </PipelineStep>
        </div>
      </div>
    </div>
  );
}
