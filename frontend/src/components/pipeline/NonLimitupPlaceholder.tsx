// 非涨停叉 lane（§4.2，调 /api/strategy/non-limitup-funnel 真漏斗）
// §44 Phase 2 未验证因子（relative_strength/ma_bullish/volume_signal/sector_strength），接入标未验证
// 数据本地（baostock industry_map + kline cache），不依赖 datacenter
import { useNonLimitupFunnel } from "@/lib/query/strategy";

export function NonLimitupLane({ date }: { date?: string }) {
  const { data: funnel, isLoading } = useNonLimitupFunnel(date);
  const candidates = funnel?.candidates ?? [];
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
            {candidates.length} 只候选 · {funnel?.sectors_scanned} 板块 · §44 Phase 2 未验证
          </div>
          {candidates.slice(0, 5).map((c) => (
            <div key={c.code} className="rounded-lg border border-dashed border-muted/40 bg-card/20 p-2">
              <div className="text-xs font-medium text-muted-foreground">
                {c.name || c.code} <span className="text-muted-foreground/60">{c.code}</span>
              </div>
              <div className="text-[10px] text-muted-foreground/60">
                {c.sector} · 分 {c.score?.toFixed(1) ?? "—"}
              </div>
            </div>
          ))}
          {candidates.length > 5 && <div className="text-[10px] text-muted-foreground">…共 {candidates.length} 只</div>}
        </>
      ) : (
        <div className="text-[10px] text-muted-foreground/60">
          {funnel?.note || "无候选（§44 Phase 2 未验证，本地 baostock 数据）"}
        </div>
      )}
    </div>
  );
}

const NODE = "rounded-lg border border-dashed border-muted/40 bg-card/20 p-2.5";

// 兼容旧 import
export const NonLimitupPlaceholder = NonLimitupLane;
