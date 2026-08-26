// S094 附录 A2/A3：战法分组视图——②涨停7战法 / ⑦非涨停5战法分组渲染。
// 数据源：scored_candidates（涨停）/ market_scan_scored（非涨停）。
// 按战法 strategy_code 分组：每战法一栏，标题=战法中文名，副标题=命中 N 只，命中候选卡片列表。
// 空战法显"0 只"（诚实标注，不建假数据）。涨停战法 §44 已验证 / 非涨停战法 §44 未验证。
// 因子过滤下沉到各战法子管线内部（附录 A3：禁止全局因子预过滤闸）。
import { useState } from "react";
import { Badge } from "@/components/ui/Badge";
import { CollapsibleFold } from "@/components/ui/CollapsibleFold";
import type { ScoredCandidate, StrategyFunnelSummary, StrategyFunnelCandidateCondition } from "@/lib/api";

// 12 战法归组（spec §3.M STRATEGIES_BY_FUNNEL_TYPE）
const LIMITUP_STRATEGIES: { code: string; name: string }[] = [
  { code: "first_plate", name: "首板挖掘" },
  { code: "consecutive_relay", name: "连板接力" },
  { code: "break_reseal", name: "炸板回封" },
  { code: "n_shape_counterattack", name: "N字反击" },
  { code: "end_of_day_sneak", name: "尾盘偷袭" },
  { code: "weak_turn_strong", name: "弱转强接力" },
  { code: "storm_reversal", name: "暴风雨逆势涨停" },
];

const MARKET_SCAN_STRATEGIES: { code: string; name: string }[] = [
  { code: "dragon_head", name: "龙头" },
  { code: "low_absorption", name: "低吸" },
  { code: "reverse_package", name: "反包" },
  { code: "platform_breakout", name: "平台突破" },
  { code: "pattern_reversal", name: "形态反包" },
];

interface Props {
  /** 涨停战法命中候选（briefing.scored_candidates）。 */
  scoredCandidates?: ScoredCandidate[];
  /** 非涨停战法命中候选（briefing.market_scan_scored）。 */
  marketScanScored?: ScoredCandidate[];
  /** 渲染哪一叉的战法分组——涨停叉显7战法 / 非涨停叉显5战法。 */
  lane: "limitup" | "non-limitup";
}

// 按战法分组：strategy_code -> ScoredCandidate[]
function groupByStrategyCode(items: ScoredCandidate[]): Map<string, ScoredCandidate[]> {
  const m = new Map<string, ScoredCandidate[]>();
  for (const it of items) {
    const arr = m.get(it.strategy_code) ?? [];
    arr.push(it);
    m.set(it.strategy_code, arr);
  }
  return m;
}

export function StrategySubPipelineView({ scoredCandidates = [], marketScanScored = [], lane }: Props) {
  const strategies = lane === "limitup" ? LIMITUP_STRATEGIES : MARKET_SCAN_STRATEGIES;
  const candidates = lane === "limitup" ? scoredCandidates : marketScanScored;
  const subtitle = lane === "limitup"
    ? "7 战法分组 · §44 已验证"
    : "5 战法分组 · §44 未验证";

  // 按战法分组
  const byCode = groupByStrategyCode(candidates);
  const totalHits = candidates.length;
  const hitStrategies = strategies.filter((s) => (byCode.get(s.code)?.length ?? 0) > 0).length;

  if (totalHits === 0) {
    // 无命中：诚实标注，不建假数据
    return (
      <CollapsibleFold
        title={lane === "limitup" ? "涨停战法匹配" : "非涨停战法匹配"}
        subtitle={`${subtitle} · 无命中（0/${strategies.length} 战法）`}
        defaultOpen={false}
      >
        <div className="rounded-lg border border-dashed border-muted/40 bg-card/20 p-3 text-xs text-muted-foreground">
          无战法命中候选（briefing 未 done 或无候选）。{lane === "non-limitup" && " §44 Phase 2 未验证。"}
        </div>
      </CollapsibleFold>
    );
  }

  return (
    <CollapsibleFold
      title={lane === "limitup" ? "涨停战法匹配" : "非涨停战法匹配"}
      subtitle={`${subtitle} · ${hitStrategies}/${strategies.length} 战法命中 · 共 ${totalHits} 只`}
      defaultOpen={true}
    >
      <div className="space-y-2">
        {strategies.map((s) => {
          const hits = byCode.get(s.code) ?? [];
          return (
            <StrategyGroupCard
              key={s.code}
              code={s.code}
              name={s.name}
              hits={hits}
              lane={lane}
            />
          );
        })}
      </div>
      <p className="mt-2 text-[10px] text-muted-foreground/60">
        因子过滤下沉各战法子管线（附录 A3：禁止全局因子预过滤闸）；历史统计特征，非执行指令。
      </p>
    </CollapsibleFold>
  );
}

/** 单战法分组卡片：标题=战法中文名 + 命中数 + 候选列表（可折叠） */
function StrategyGroupCard({
  code,
  name,
  hits,
  lane,
}: {
  code: string;
  name: string;
  hits: ScoredCandidate[];
  lane: "limitup" | "non-limitup";
}) {
  const hasHits = hits.length > 0;
  // 无命中战法折叠（附录 A2：空战法折叠或显"0 只"）
  const [open, setOpen] = useState(hasHits);

  return (
    <div className={`rounded-lg border ${hasHits ? "border-border/40 bg-card/30" : "border-dashed border-muted/30 bg-card/10"} p-2.5`}>
      <button
        type="button"
        onClick={() => hasHits && setOpen((v) => !v)}
        className="flex w-full items-center justify-between text-left"
        disabled={!hasHits}
      >
        <div className="flex items-center gap-2">
          <span className="text-sm font-medium">{name}</span>
          <span className="text-[10px] text-muted-foreground/60">{code}</span>
          {lane === "non-limitup" && (
            <span className="rounded bg-muted/30 px-1 text-[9px] text-muted-foreground">§44 未验证</span>
          )}
        </div>
        <div className="flex items-center gap-1.5">
          <Badge variant={hasHits ? "info" : "default"}>{hits.length} 只</Badge>
          {hasHits && (
            <span className="text-[10px] text-muted-foreground/60">{open ? "▼" : "▶"}</span>
          )}
        </div>
      </button>
      {hasHits && open && (
        <div className="mt-2 space-y-1.5 border-t border-border/20 pt-2">
          {/* S097 D：逐条件漏斗摘要（同战法共享，取首候选 strategy_funnel；R15 旧快照无此字段则不渲染） */}
          <FunnelSummary funnel={hits[0]?.strategy_funnel} />
          {hits.map((c) => (
            <CandidateRow
              key={`${c.code}-${c.strategy_code}`}
              c={c}
              conditionStates={findFunnelCandidateConditions(hits[0]?.strategy_funnel, c.code)}
            />
          ))}
        </div>
      )}
    </div>
  );
}

/** 候选行：name + code + strategy_score + confidence + sector + 逐条件命中标记（S097） */
function CandidateRow({
  c,
  conditionStates,
}: {
  c: ScoredCandidate;
  conditionStates?: StrategyFunnelCandidateCondition[];
}) {
  const sector = c.sector as string | undefined;
  const confidence = c.confidence as number | undefined;
  return (
    <div className="flex items-center justify-between rounded border border-border/30 bg-card/20 px-2 py-1.5">
      <div className="min-w-0 flex-1">
        <div className="flex items-center gap-1.5">
          <span className="truncate text-xs font-medium text-foreground">{c.name}</span>
          <span className="shrink-0 font-mono text-[10px] text-muted-foreground/60">{c.code}</span>
        </div>
        {conditionStates && conditionStates.length > 0 && (
          <div className="mt-0.5 flex flex-wrap gap-0.5">
            {conditionStates.map((cs) => (
              <ConditionMarker key={cs.condition_id} state={cs.state} conditionId={cs.condition_id} />
            ))}
          </div>
        )}
        <div className="mt-0.5 flex flex-wrap gap-x-2 gap-y-0.5 text-[9px] text-muted-foreground/50">
          {sector && <span>板块 {sector}</span>}
          {confidence != null && <span>置信 {confidence.toFixed(2)}</span>}
        </div>
      </div>
      <div className="ml-2 shrink-0 text-right">
        <span className="text-sm font-bold tabular-nums text-primary">
          {c.strategy_score?.toFixed(1) ?? "—"}
        </span>
        <div className="text-[9px] text-muted-foreground/50">策略分</div>
      </div>
    </div>
  );
}

/** S097 D：从漏斗 candidates 中按 code 取该候选的逐条件命中状态（无则 undefined，不渲染标记）。 */
function findFunnelCandidateConditions(
  funnel: StrategyFunnelSummary | undefined,
  code: string,
): StrategyFunnelCandidateCondition[] | undefined {
  if (!funnel) return undefined;
  return funnel.candidates.find((c) => c.code === code)?.conditions;
}

/** S097 D：逐条件漏斗摘要（同战法共享）。无 strategy_funnel 时不渲染（R15 历史快照兼容）。 */
function FunnelSummary({ funnel }: { funnel?: StrategyFunnelSummary }) {
  if (!funnel) return null;
  const fireRate = funnel.total_count > 0
    ? `${funnel.fired_count}/${funnel.total_count}（${Math.round((funnel.fired_count / funnel.total_count) * 100)}%）`
    : `${funnel.fired_count}/${funnel.total_count}`;
  return (
    <div className="rounded border border-border/20 bg-card/10 p-1.5 text-[10px]">
      <div className="text-muted-foreground/70">
        <span className="text-foreground/80">触发率</span> {fireRate}
      </div>
      <div className="mt-1 flex flex-col gap-1">
        {funnel.conditions.map((cond) => {
          const rate = cond.input_count > 0
            ? Math.round((cond.passed_count / cond.input_count) * 100)
            : null;
          return (
            <div key={cond.condition_id} className="flex flex-wrap items-center gap-x-1.5 gap-y-0.5">
              <span className="text-muted-foreground/80">{cond.condition_name}</span>
              <span className="font-mono tabular-nums text-muted-foreground/60">
                {cond.input_count}→{cond.passed_count}
              </span>
              {cond.data_unavailable_count > 0 && (
                <span className="text-yellow-500/80">数据缺失 {cond.data_unavailable_count}</span>
              )}
              <span className="font-mono tabular-nums text-muted-foreground/60">
                {rate != null ? `${rate}%` : "—"}
              </span>
            </div>
          );
        })}
      </div>
    </div>
  );
}

/** S097 D：候选行条件命中标记（三态：✓ 绿 / ✗ 灰 / — 黄）。 */
function ConditionMarker({
  state,
  conditionId,
}: {
  state: "hit" | "miss" | "data_unavailable";
  conditionId: string;
}) {
  const config = {
    hit: { symbol: "✓", cls: "text-green-500" },
    miss: { symbol: "✗", cls: "text-muted-foreground/30" },
    data_unavailable: { symbol: "—", cls: "text-yellow-500" },
  } as const;
  const { symbol, cls } = config[state];
  return (
    <span title={`${conditionId}: ${state}`} className={`text-[11px] leading-none ${cls}`}>
      {symbol}
    </span>
  );
}
