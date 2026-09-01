// 非涨停叉 lane——S094 §11 附录 A2 四节点结构（⑤⑥⑦⑧）
// ⑤ 选股宇宙（板块 TOP-N 成分股）→ ⑥ K线形态 → ⑦ 战法匹配（5战法分组视图）→ ⑧ 候选终选
// §44 Phase 2 未验证因子（relative_strength/ma_bullish/volume_signal/sector_strength），接入标未验证
// 数据本地（baostock industry_map + kline cache），不依赖 datacenter
// S094 §11：去 opacity-60（双叉切换后为独立显式 lane）+ 重写为四节点结构
// ⑦ 战法匹配复用 StrategySubPipelineView（与 Workflow.tsx 涨停叉②共用同一分组组件）
import { useNonLimitupFunnel } from "@/lib/query/strategy";
import { HonestyBanner } from "@/components/ui/HonestyBanner";
import { StrategySubPipelineView } from "@/components/pipeline/StrategySubPipelineView";
import { GlassCard } from "@/components/ui/GlassCard";
import { Clock } from "lucide-react";
import type { ScoredCandidate } from "@/lib/api";
import { ArrowDown } from "@/components/pipeline/primitives";

interface NonLimitupLaneProps {
  date?: string;
  /** S094 T17/R28：briefing 透传的 market_scan_scored（若提供则直接用，不调独立端点）。 */
  candidates?: ScoredCandidate[];
}

// 候选展示上限（防超长列表，超出显"…共 N 只"）
const MAX_CANDIDATES = 50;

export function NonLimitupLane({ date, candidates: briefingCandidates }: NonLimitupLaneProps) {
  // S094 T17/R28：briefing market_scan_scored 优先；未提供时 fallback 独立端点
  const skipFetch = briefingCandidates != null;
  const { data: funnel, isLoading } = useNonLimitupFunnel(date, { enabled: !skipFetch });
  const candidates: ScoredCandidate[] = skipFetch
    ? (briefingCandidates ?? [])
    : ((funnel?.candidates as unknown as ScoredCandidate[]) ?? []);
  const sectorsScanned = skipFetch ? undefined : funnel?.sectors_scanned;
  const note = skipFetch ? undefined : funnel?.note;

  return (
    <div className="space-y-1.5">
      <HonestyBanner />

      {/* ⑤ 选股宇宙：板块 TOP-N 成分股 */}
      <SelectionUniverseNode
        candidateCount={candidates.length}
        sectorsScanned={sectorsScanned}
        isLoading={isLoading}
        note={note}
      />
      <ArrowDown label="K线形态" />

      {/* ⑥ K线形态：PatternScan 因子概览（候选数 + 因子名列表） */}
      <PatternScanNode candidates={candidates} />
      <ArrowDown label="战法匹配" />

      {/* ⑦ 战法匹配（5 战法分组视图）——复用 StrategySubPipelineView（与涨停叉②同组件） */}
      <StrategySubPipelineView
        scoredCandidates={briefingCandidates ?? []}
        marketScanScored={candidates}
        lane="non-limitup"
      />
      <ArrowDown label="候选终选" />

      {/* ⑧ 候选终选：全量展开候选列表（去 opacity-60，每只显 strategy_score/confidence/sector） */}
      <FinalSelectionNode candidates={candidates} />
    </div>
  );
}

// ⑤ 选股宇宙节点
function SelectionUniverseNode({
  candidateCount,
  sectorsScanned,
  isLoading,
  note,
}: {
  candidateCount: number;
  sectorsScanned?: number;
  isLoading: boolean;
  note?: string;
}) {
  return (
    <div className={NODE}>
      <div className="flex items-center justify-between">
        <div>
          <div className="text-sm font-medium">⑤ 选股宇宙</div>
          <div className="text-[11px] text-muted-foreground">板块 TOP-N 成分股 · §44 未验证</div>
        </div>
        <div className="text-lg font-bold text-primary">
          {isLoading ? "…" : candidateCount}
        </div>
      </div>
      {sectorsScanned != null && !isLoading && (
        <div className="mt-0.5 text-[10px] text-muted-foreground/60">
          扫描 {sectorsScanned} 板块 · {candidateCount} 只候选
        </div>
      )}
      {candidateCount === 0 && !isLoading && !note && (
        <div className="mt-0.5 text-[10px] text-muted-foreground/60">
          无候选（§44 Phase 2 未验证，本地 baostock 数据）
        </div>
      )}
      {note && !isLoading && (
        <div className="mt-0.5 text-[10px] text-muted-foreground/60">{note}</div>
      )}
    </div>
  );
}

// ⑥ K线形态：PatternScan 因子概览
function PatternScanNode({ candidates }: { candidates: ScoredCandidate[] }) {
  // 因子名列表（PatternScan 4 因子，spec §3.M：相对强度/均线多头/量能信号/板块强度）
  const factorNames = ["相对强度", "均线多头", "量能信号", "板块强度"];
  return (
    <div className={NODE}>
      <div className="flex items-center justify-between">
        <div>
          <div className="text-sm font-medium">⑥ K线形态</div>
          <div className="text-[11px] text-muted-foreground">PatternScan 因子概览</div>
        </div>
        <span className="rounded bg-muted/30 px-1 text-[10px] text-muted-foreground">§44 未验证</span>
      </div>
      <div className="mt-1 flex flex-wrap gap-1">
        {factorNames.map((f) => (
          <span key={f} className="rounded bg-muted/20 px-1.5 py-0.5 text-[10px] text-muted-foreground/70">
            {f}
          </span>
        ))}
      </div>
      {candidates.length === 0 && (
        <div className="mt-0.5 text-[10px] text-muted-foreground/60">无候选数据（因子未扫描）</div>
      )}
    </div>
  );
}

// ⑧ 候选终选：全量展开候选列表
function FinalSelectionNode({ candidates }: { candidates: ScoredCandidate[] }) {
  const shown = candidates.slice(0, MAX_CANDIDATES);
  const overflow = candidates.length - shown.length;

  if (candidates.length === 0) {
    // F5：空态引导卡——不显空白，用 GlassCard + Clock 图标暗示"采集中"
    return (
      <GlassCard className="flex flex-col items-center justify-center gap-1.5 p-4 text-center">
        <Clock className="h-5 w-5 text-muted-foreground/50" />
        <div className="text-xs font-medium text-muted-foreground">market_scan 数据采集中</div>
        <div className="text-[10px] text-muted-foreground/60">
          K线形态扫描 + 5 战法匹配需盘后数据回填
        </div>
        <div className="text-[10px] text-muted-foreground/50">
          当前状态：0 只候选（sti_timeline 数据库为空，盘后采集任务未跑）
        </div>
      </GlassCard>
    );
  }

  return (
    <div className="space-y-1.5">
      <div className="flex items-center gap-2">
        <span className="text-xs font-semibold tracking-wide text-muted-foreground uppercase">⑧ 候选终选</span>
        <span className="text-[10px] text-muted-foreground/70">{candidates.length} 只 · §44 未验证</span>
      </div>
      {shown.map((c) => (
        <CandidateCard key={c.code} c={c} />
      ))}
      {overflow > 0 && (
        <div className="text-[10px] text-muted-foreground">…共 {candidates.length} 只（显前 {MAX_CANDIDATES}）</div>
      )}
    </div>
  );
}

// 候选卡片：strategy_score + confidence + sector
function CandidateCard({ c }: { c: ScoredCandidate }) {
  const sector = c.sector as string | undefined;
  const confidence = c.confidence as number | undefined;
  return (
    <div className="rounded-lg border border-dashed border-muted/40 bg-card/20 p-2">
      <div className="flex items-center justify-between">
        <div className="text-xs font-medium text-muted-foreground">
          {c.name} <span className="text-muted-foreground/60">{c.code}</span>
        </div>
        <span className="text-sm font-bold tabular-nums text-primary">
          {c.strategy_score?.toFixed(1) ?? "—"}
        </span>
      </div>
      <div className="mt-0.5 flex flex-wrap gap-x-3 gap-y-0.5 text-[10px] text-muted-foreground/60">
        {sector && <span>板块 {sector}</span>}
        {confidence != null && <span>置信 {confidence.toFixed(2)}</span>}
        {c.strategy_name && <span>战法 {c.strategy_name}</span>}
      </div>
    </div>
  );
}

// ArrowDown 见 primitives.tsx（S140 R4 去重）

const NODE = "rounded-lg border border-dashed border-muted/40 bg-card/20 p-2.5";

// 兼容旧 import
export const NonLimitupPlaceholder = NonLimitupLane;
