// S094 + S148(b)：战法分组列表视图——②涨停7战法 / ⑦非涨停5战法，紧凑列表（默认收缩，点击展开候选）。
// 数据源：scored_candidates（涨停）/ market_scan_scored（非涨停）。
// 按战法 strategy_code 分组：每战法一行（名+触发率+命中数），点击展开候选列表。
// 空战法显"0 只"+数据原因（诚实标注，不建假数据）。涨停战法 §44 已验证 / 非涨停战法 §44 未验证。
import { useState } from "react";
import { Link } from "react-router-dom";
import { Badge } from "@/components/ui/Badge";
import type { ScoredCandidate, StrategyFunnelCandidateCondition } from "@/lib/api";

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

// 无漏斗数据时的具体原因 + 修复指引
const STRATEGY_DATA_STATUS: Record<string, { reason: string; fix: string }> = {
  weak_turn_strong: {
    reason: "依赖盘中分时派生数据（炸板时长/跌幅度/回封时间）",
    fix: "交易日 9:25-15:05 保持后端运行，seal_intraday_collect 定时任务自动采集 → 盘后 derived_precompute 自动算 derived → 次日有数据",
  },
  dragon_head: {
    reason: "非涨停战法需 market_scan_ctx（板块内排名），涨停 pipeline 不构造此上下文",
    fix: "切换到非涨停叉，gather_non_limitup_candidates 采集 market_scan 数据后生效（需 baostock_kline_cache 全 A 扩容 + sti_timeline 数据回填）",
  },
  low_absorption: {
    reason: "非涨停战法需 PatternScan（MA5 回调/均线多头），涨停 pipeline 无此上下文",
    fix: "切换到非涨停叉，market_scan pipeline 采集 K 线形态因子后生效",
  },
  platform_breakout: {
    reason: "非涨停战法需 PatternScan（横盘天数/放量突破），涨停 pipeline 无此上下文",
    fix: "切换到非涨停叉，market_scan pipeline 采集 K 线形态因子后生效",
  },
  pattern_reversal: {
    reason: "非涨停战法需 PatternScan（上影线/放量/MA5 斜率），涨停 pipeline 无此上下文",
    fix: "切换到非涨停叉，market_scan pipeline 采集 K 线形态因子后生效",
  },
  reverse_package: {
    reason: "依赖炸板池 DB（seal_intraday.db，open_count≥2 的炸板股）",
    fix: "交易日 9:25-15:05 保持后端运行，seal_intraday_collect 自动采集炸板池数据 → 次日有数据",
  },
};

interface Props {
  scoredCandidates?: ScoredCandidate[];
  marketScanScored?: ScoredCandidate[];
  lane: "limitup" | "non-limitup";
  scoredTotal?: number;
}

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
  const evalTotal = scoredTotal ?? candidates.length;
  const subtitle = lane === "limitup"
    ? `战法评估 ${evalTotal} 只 · 7 战法分组 · §44 无 validated edge`
    : `战法评估 ${evalTotal} 只 · 5 战法分组 · §44 未验证`;
  const byCode = groupByStrategyCode(candidates);
  const totalHits = candidates.length;
  const hitStrategies = strategies.filter((s) => (byCode.get(s.code)?.length ?? 0) > 0).length;

  // 紧凑列表：每战法一行（名+触发率+命中数），点击展开候选。② PipelineStep 已包外层折叠（默认收缩）。
  return (
    <div className="space-y-1">
      <div className="text-[10px] text-muted-foreground/70">
        {subtitle} · {hitStrategies}/{strategies.length} 战法命中 · 共 {totalHits} 只
      </div>
      {strategies.map((s) => {
        const hits = byCode.get(s.code) ?? [];
        return <StrategyListRow key={s.code} code={s.code} name={s.name} hits={hits} lane={lane} />;
      })}
    </div>
  );
}

/** 战法列表行：名+触发率+命中数，点击展开候选列表（默认收缩）。无命中→灰行+数据原因。 */
function StrategyListRow({
  code, name, hits, lane,
}: { code: string; name: string; hits: ScoredCandidate[]; lane: "limitup" | "non-limitup" }) {
  const hasHits = hits.length > 0;
  const [open, setOpen] = useState(false);
  const funnel = hits[0]?.strategy_funnel;
  const firePct = funnel && funnel.total_count > 0
    ? Math.round((funnel.fired_count / funnel.total_count) * 100)
    : null;

  if (!hasHits) {
    return (
      <div className="rounded border border-border/20 bg-card/10 px-2 py-1 opacity-60">
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-1.5">
            <span className="text-xs font-medium">{name}</span>
            <span className="font-mono text-[10px] text-muted-foreground/60">{code}</span>
            {lane === "non-limitup" && (
              <span className="rounded bg-muted/30 px-1 text-[9px] text-muted-foreground">§44 未验证</span>
            )}
          </div>
          <Badge variant="default">0 只</Badge>
        </div>
        <StrategyDataHint code={code} />
      </div>
    );
  }

  return (
    <div className="rounded border border-border/30 bg-card/20">
      <button
        type="button"
        onClick={() => setOpen((v) => !v)}
        className="flex w-full items-center justify-between px-2 py-1.5 text-left hover:bg-card/30"
      >
        <div className="flex items-center gap-1.5">
          <span className="text-xs font-semibold">{name}</span>
          <span className="font-mono text-[10px] text-muted-foreground/60">{code}</span>
          {lane === "non-limitup" && (
            <span className="rounded bg-muted/30 px-1 text-[9px] text-muted-foreground">§44 未验证</span>
          )}
          {firePct != null && (
            <span className="text-[10px] text-muted-foreground/60">
              触发 {funnel!.fired_count}/{funnel!.total_count}（{firePct}%）
            </span>
          )}
        </div>
        <div className="flex items-center gap-1.5">
          <Badge variant="info">{hits.length} 只</Badge>
          <span className="text-[10px] text-muted-foreground/60">{open ? "▼" : "▶"}</span>
        </div>
      </button>
      {open && (
        <div className="border-t border-border/20 p-1.5 space-y-1">
          {hits.map((c) => (
            <CandidateRow
              key={`${c.code}-${c.strategy_code}`}
              c={c}
              conditionStates={findFunnelCandidateConditions(funnel, c.code)}
            />
          ))}
        </div>
      )}
    </div>
  );
}

/** 候选行：name + code + strategy_score + 逐条件命中标记。点击跳个股深度页。 */
function CandidateRow({
  c, conditionStates,
}: { c: ScoredCandidate; conditionStates?: StrategyFunnelCandidateCondition[] }) {
  const sector = c.sector as string | undefined;
  const confidence = c.confidence as number | undefined;
  return (
    <Link
      to={`/stock/${c.code}`}
      className="flex items-center justify-between rounded border border-border/30 bg-card/20 px-2 py-1.5 transition-colors hover:border-primary/40 hover:bg-card/40"
    >
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
    </Link>
  );
}

function findFunnelCandidateConditions(
  funnel: ScoredCandidate["strategy_funnel"], code: string,
): StrategyFunnelCandidateCondition[] | undefined {
  if (!funnel) return undefined;
  return funnel.candidates.find((c) => c.code === code)?.conditions;
}

/** 三态条件命中标记：✓ 绿 / ✗ 灰 / — 黄。 */
function ConditionMarker({
  state, conditionId,
}: { state: "hit" | "miss" | "data_unavailable"; conditionId: string }) {
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

/** 无漏斗数据时显示具体原因 + 修复指引。 */
function StrategyDataHint({ code }: { code: string }) {
  const status = STRATEGY_DATA_STATUS[code];
  if (!status) {
    return <span className="text-[10px] text-muted-foreground/50">无漏斗数据（历史快照或无评估）</span>;
  }
  return (
    <div className="flex flex-col gap-0.5">
      <span className="text-[10px] text-yellow-500/80">⚠ {status.reason}</span>
      <span className="text-[10px] text-muted-foreground/50">修复：{status.fix}</span>
    </div>
  );
}
