// S146：涨停叉内交叉验证摘要——final_candidates(漏斗终选) ∩ scored_candidates(战法命中)。
// breakout 降级研究后 ④ 重定向叉内：涨停∩非涨停 by 构造 disjoint（非涨停=板块TOP非涨停股），
// breakout 曾是唯一可交集的第二输入，现移研究 tab；④ 改涨停叉内双确认（漏斗终选∩战法命中，都涨停股有交集）。
// 三组：双指标重叠 / 仅漏斗终选 / 仅战法命中。保 geneScore/strategyScore 不丢（drop breakoutScore）。
// 类型从 useCrossValidation 共享（CrossValidationGroups）——选股 ④ + 盯盘 WatchlistBoard 同一份 CV 定义。
import { GlassCard } from "@/components/ui/GlassCard";
import type { CrossValidationGroups } from "@/lib/query/useCrossValidation";

const GROUPS = [
  { key: "dual" as const, label: "双指标重叠", desc: "漏斗终选 ∩ 战法命中（§44 未 validated，排序参考非 edge）", icon: "◆", cls: "text-muted-foreground/70" },
  { key: "funnelOnly" as const, label: "仅漏斗终选", desc: "过八项 · 未命中战法", icon: "◆", cls: "text-muted-foreground/50" },
  { key: "strategyOnly" as const, label: "仅战法命中", desc: "命中战法 · 未过八项", icon: "◇", cls: "text-muted-foreground/50" },
];

/** 涨停叉内交叉验证摘要——三组富对象列表 + 详情行（股票名/战法/分数）。 */
export function CrossValidationSummary({ groups }: { groups: CrossValidationGroups }) {
  if (groups.isLoading) {
    return <GlassCard className="mb-3 p-4 text-sm text-muted-foreground">交叉验证计算中…</GlassCard>;
  }
  const hasData = groups.dual.length > 0 || groups.funnelOnly.length > 0 || groups.strategyOnly.length > 0;
  if (!hasData) return <p className="text-[11px] text-muted-foreground/60">无交叉验证数据</p>;

  return (
    <GlassCard className="mb-3 p-4">
      <div className="flex items-center gap-2 border-b border-border/30 pb-2">
        <span className="text-sm font-semibold">交叉验证</span>
        <span className="text-xs text-muted-foreground/70">漏斗终选 ∩ 战法命中 · {groups.dual.length} 双指标重叠（§44 未 validated，非 edge）</span>
      </div>
      <div className="mt-3 space-y-3">
        {GROUPS.map((g) => {
          const items = groups[g.key];
          if (items.length === 0) return null;
          return (
            <div key={g.key}>
              <div className="mb-1.5 flex items-center gap-2">
                <span className={`shrink-0 ${g.cls}`}>{g.icon}</span>
                <span className="rounded bg-muted/30 px-1.5 text-[10px] text-muted-foreground/80">{g.label}</span>
                <span className="text-xs text-muted-foreground/70">{g.desc}</span>
                <span className="text-xs font-bold tabular-nums text-foreground">{items.length} 只</span>
              </div>
              <div className="space-y-1">
                {items.map((item) => (
                  <div key={item.code} className="flex items-center justify-between gap-2 rounded border border-border/20 bg-card/10 px-2 py-1 text-xs">
                    <div className="flex min-w-0 flex-1 items-center gap-1.5">
                      <span className="truncate font-medium text-foreground">{item.name}</span>
                      <span className="shrink-0 font-mono text-[10px] text-muted-foreground/60">{item.code}</span>
                      {item.strategyName && (
                        <span className="shrink-0 rounded bg-muted/30 px-1 text-[10px] text-muted-foreground/80">{item.strategyName}</span>
                      )}
                    </div>
                    <div className="flex shrink-0 items-center gap-2 font-mono text-[10px] tabular-nums text-muted-foreground/70">
                      {item.geneScore != null && <span>基因 {item.geneScore.toFixed(1)}</span>}
                      {item.strategyScore != null && <span>战法 {item.strategyScore.toFixed(1)}</span>}
                    </div>
                  </div>
                ))}
              </div>
            </div>
          );
        })}
      </div>
      <p className="mt-2 text-[10px] text-muted-foreground/60">参考值，非执行指令；市场有风险</p>
    </GlassCard>
  );
}
