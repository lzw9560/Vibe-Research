// 非涨停叉 lane（§4.2，调 /api/strategy/non-limitup-funnel 真漏斗）
// §44 Phase 2 未验证因子（relative_strength/ma_bullish/volume_signal/sector_strength），接入标未验证
// 数据本地（baostock industry_map + kline cache），不依赖 datacenter
import { useNonLimitupFunnel } from "@/lib/query/strategy";
import type { ScoredCandidate } from "@/lib/api";

interface NonLimitupLaneProps {
  date?: string;
  /** S094 T17/R28：briefing 透传的 market_scan_scored（若提供则直接用，不调独立端点）。 */
  candidates?: ScoredCandidate[];
}

export function NonLimitupLane({ date, candidates: briefingCandidates }: NonLimitupLaneProps) {
  // S094 T17/R28：briefing market_scan_scored 优先（前端双 pipeline 分区消费，一调用拿双 pipeline）；
  // 未提供时 fallback 独立端点 /api/strategy/non-limitup-funnel（Candidates 页等 on-demand 场景）。
  const skipFetch = briefingCandidates != null;
  const { data: funnel, isLoading } = useNonLimitupFunnel(date, { enabled: !skipFetch });
  const candidates: ScoredCandidate[] = skipFetch
    ? (briefingCandidates ?? [])
    : ((funnel?.candidates as unknown as ScoredCandidate[]) ?? []);
  const sectorsScanned = skipFetch ? undefined : funnel?.sectors_scanned;
  const note = skipFetch ? undefined : funnel?.note;
  return (
    <div className="space-y-1.5 opacity-60">
      <div className="flex items-center gap-2">
        <span className="text-xs font-semibold tracking-wide text-muted-foreground uppercase">非涨停叉</span>
        <span className="rounded bg-muted/30 px-1 text-[10px] text-muted-foreground">§44 未验证</span>
      </div>
      {isLoading ? (
        <div className={`${NODE} text-xs text-muted-foreground`}>非涨停漏斗扫描中…（板块成分股 + 形态扫描）</div>
      ) : candidates.length > 0 ? (
        <>
          <div className="text-[10px] text-muted-foreground">
            {candidates.length} 只候选{sectorsScanned != null ? ` · ${sectorsScanned} 板块` : ""} · §44 Phase 2 未验证
          </div>
          {candidates.slice(0, 5).map((c) => (
            <div key={c.code} className="rounded-lg border border-dashed border-muted/40 bg-card/20 p-2">
              <div className="text-xs font-medium text-muted-foreground">
                {c.name} <span className="text-muted-foreground/60">{c.code}</span>
              </div>
              <div className="text-[10px] text-muted-foreground/60">
                {c.sector as string | undefined} · 分 {c.strategy_score?.toFixed(1) ?? "—"}
              </div>
            </div>
          ))}
          {candidates.length > 5 && <div className="text-[10px] text-muted-foreground">…共 {candidates.length} 只</div>}
        </>
      ) : (
        <div className="text-[10px] text-muted-foreground/60">
          {note || "无候选（§44 Phase 2 未验证，本地 baostock 数据）"}
        </div>
      )}
    </div>
  );
}

const NODE = "rounded-lg border border-dashed border-muted/40 bg-card/20 p-2.5";

// 兼容旧 import
export const NonLimitupPlaceholder = NonLimitupLane;
