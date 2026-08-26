// S094 附录 A2/A3：战法分组视图——②涨停7战法 / ⑦非涨停5战法分组渲染。
// 数据源：scored_candidates（涨停）/ market_scan_scored（非涨停）。
// 按战法 strategy_code 分组：每战法一栏，标题=战法中文名，副标题=命中 N 只，命中候选卡片列表。
// 空战法显"0 只"（诚实标注，不建假数据）。涨停战法 §44 已验证 / 非涨停战法 §44 未验证。
// 因子过滤下沉到各战法子管线内部（附录 A3：禁止全局因子预过滤闸）。
import { useState } from "react";
import { Badge } from "@/components/ui/Badge";
import { CollapsibleFold } from "@/components/ui/CollapsibleFold";
import type { ScoredCandidate, StrategyFunnelSummary, StrategyFunnelCandidateCondition, StrategyFunnelCondition } from "@/lib/api";

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
  /** F6：战法评估候选总数（briefing.scored_candidates.length），subtitle 前缀"战法评估 M 只 ·"。
   *  让用户一眼区分"终选 N 只"（候选因子表）vs"战法评估 M 只"（战法漏斗）不同数据源。 */
  scoredTotal?: number;
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

export function StrategySubPipelineView({ scoredCandidates = [], marketScanScored = [], lane, scoredTotal }: Props) {
  const strategies = lane === "limitup" ? LIMITUP_STRATEGIES : MARKET_SCAN_STRATEGIES;
  const candidates = lane === "limitup" ? scoredCandidates : marketScanScored;
  // F6：战法评估 M 只前缀——scoredTotal 传入则显，否则 fallback candidates.length
  const evalTotal = scoredTotal ?? candidates.length;
  const subtitle = lane === "limitup"
    ? `战法评估 ${evalTotal} 只 · 7 战法分组 · §44 已验证`
    : `战法评估 ${evalTotal} 只 · 5 战法分组 · §44 未验证`;

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
        {/* F3：三态图例（与 ConditionMarker 同色系，首次使用者无需 hover 即懂符号） */}
        <ConditionLegend />
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

/** S097 D：逐条件漏斗摘要（同战法共享）。无 strategy_funnel 时不渲染（R15 历史快照兼容）。
 *  F2 改造：触发率环形进度 + 每条件横向条形漏斗（input 满宽底条 → passed 收窄窄条 → data_unavailable 黄条纹段）。 */
function FunnelSummary({ funnel }: { funnel?: StrategyFunnelSummary }) {
  if (!funnel) return null;
  const firePct = funnel.total_count > 0
    ? Math.round((funnel.fired_count / funnel.total_count) * 100)
    : 0;
  return (
    <div className="rounded border border-border/20 bg-card/10 p-1.5 text-[10px]">
      {/* 触发率：环形进度指示器（fired/total） */}
      <div className="flex items-center justify-between">
        <span className="text-muted-foreground/70">触发率</span>
        <div className="flex items-center gap-1.5">
          <FireRing percent={firePct} />
          <span className="font-mono tabular-nums text-muted-foreground/80">
            {funnel.fired_count}/{funnel.total_count}（{firePct}%）
          </span>
        </div>
      </div>
      {/* 逐条件横向条形漏斗：条件名左 · 条形图中 · 数值右 */}
      <div className="mt-1.5 flex flex-col gap-1">
        {funnel.conditions.map((cond) => (
          <FunnelConditionRow key={cond.condition_id} cond={cond} />
        ))}
      </div>
    </div>
  );
}

/** F2：环形进度指示器（SVG，32×32，内显百分比数字）。 */
function FireRing({ percent }: { percent: number }) {
  const r = 9;
  const c = 2 * Math.PI * r;
  const dash = c * (Math.max(0, Math.min(100, percent)) / 100);
  return (
    <svg width="22" height="22" viewBox="0 0 22 22" className="shrink-0">
      <circle cx="11" cy="11" r={r} fill="none" stroke="currentColor" strokeWidth="2" className="text-muted/30" />
      <circle
        cx="11"
        cy="11"
        r={r}
        fill="none"
        stroke="currentColor"
        strokeWidth="2.5"
        className="text-primary"
        strokeDasharray={`${dash} ${c}`}
        strokeLinecap="round"
        transform="rotate(-90 11 11)"
      />
      <text x="11" y="11.5" textAnchor="middle" dominantBaseline="middle" className="fill-current text-[6px] font-bold text-primary">
        {percent}
      </text>
    </svg>
  );
}

/** F2：单条件横向条形漏斗行（高度 ≤24px）。
 *  条形：input_count 满宽底条（灰）→ passed_count 内层窄条（主色，收窄效果）→ data_unavailable 黄条纹覆盖段。
 *  数值：input→passed + pass_rate% 在右。 */
function FunnelConditionRow({ cond }: { cond: StrategyFunnelCondition }) {
  const { condition_name, input_count, passed_count, data_unavailable_count, pass_rate } = cond;
  // 段宽：以 input_count 为分母（若 0 则全空）。passed + unavailable 不超过 input（unavailable 独立计，视觉上作 overlay）
  const denom = input_count > 0 ? input_count : 1;
  const passedW = (passed_count / denom) * 100;
  const unavailW = (data_unavailable_count / denom) * 100;
  const ratePct = pass_rate != null ? Math.round(pass_rate * 100) : null;
  return (
    <div className="flex items-center gap-1.5" style={{ height: "20px" }}>
      {/* 条件名（左，truncate 防长名撑开） */}
      <span className="w-20 shrink-0 truncate text-muted-foreground/80" title={condition_name}>
        {condition_name}
      </span>
      {/* 条形图（中，flex-1 满宽底条 + 内层窄条 + 黄条纹覆盖） */}
      <div className="relative h-2 flex-1 overflow-hidden rounded bg-muted/30">
        {/* passed 窄条（收窄效果：从左起，宽 = passed/input） */}
        <div
          className="absolute inset-y-0 left-0 rounded bg-primary/50"
          style={{ width: `${Math.max(passedW, passed_count > 0 ? 6 : 0)}%` }}
        />
        {/* data_unavailable 黄条纹覆盖段（叠加在 passed 右侧或独立段，斜纹纹理） */}
        {data_unavailable_count > 0 && (
          <div
            className="absolute inset-y-0 bg-yellow-500/40"
            style={{
              left: `${passedW}%`,
              width: `${unavailW}%`,
              backgroundImage:
                "repeating-linear-gradient(135deg, rgba(234,179,8,0.5) 0 2px, rgba(234,179,8,0.15) 2px 4px)",
            }}
            title={`数据缺失 ${data_unavailable_count}`}
          />
        )}
      </div>
      {/* 数值（右：input→passed + rate%） */}
      <span className="w-16 shrink-0 text-right font-mono tabular-nums text-muted-foreground/70">
        {input_count}→{passed_count}
        {ratePct != null ? ` ${ratePct}%` : ""}
      </span>
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

/** F3：三态图例条——与 ConditionMarker 同色系，让首次使用者无需 hover 即懂符号含义。 */
function ConditionLegend() {
  const items = [
    { symbol: "✓", label: "命中", cls: "text-green-500" },
    { symbol: "✗", label: "未命中", cls: "text-muted-foreground/30" },
    { symbol: "—", label: "数据缺失", cls: "text-yellow-500" },
  ] as const;
  return (
    <div className="flex items-center justify-end gap-3 text-[10px] text-muted-foreground/70">
      {items.map((it) => (
        <span key={it.label} className="inline-flex items-center gap-1">
          <span className={`leading-none ${it.cls}`}>{it.symbol}</span>
          <span>{it.label}</span>
        </span>
      ))}
    </div>
  );
}
