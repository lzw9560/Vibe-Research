// S087 B4：盘前②战法匹配步——票×战法命中 matrix + 按战法分列双视图。
// S094 R24：涨停/非涨停分区（②涨停战法 scored_candidates + ⑦非涨停战法 market_scan_scored 两 region）。
// 数据源：usePreMarketBriefing().scored_candidates + market_scan_scored。
// R6：双视图切换（默认 matrix，可切按战法分列）。R13：AskAiButton。

import { useState } from "react";
import { usePreMarketBriefing } from "@/lib/query";
import { GlassCard } from "@/components/ui/GlassCard";
import { Badge } from "@/components/ui/Badge";
import { Button } from "@/components/ui/Button";
import { AskAiButton } from "@/components/ui/AskAiButton";
import type { ScoredCandidate } from "@/lib/api/types";

interface Props {
  date?: string;
}

// 按票分组：code -> {name, hits, topScore}
function groupByCode(items: ScoredCandidate[]): Map<string, { name: string; hits: ScoredCandidate[]; topScore: number }> {
  const m = new Map<string, { name: string; hits: ScoredCandidate[]; topScore: number }>();
  for (const it of items) {
    const e = m.get(it.code) ?? { name: it.name, hits: [], topScore: 0 };
    e.hits.push(it);
    e.topScore = Math.max(e.topScore, it.strategy_score);
    m.set(it.code, e);
  }
  return m;
}

// 按战法分组：strategy_code -> {name, candidates}
function groupByStrategy(items: ScoredCandidate[]): Map<string, { name: string; candidates: ScoredCandidate[] }> {
  const m = new Map<string, { name: string; candidates: ScoredCandidate[] }>();
  for (const it of items) {
    const e = m.get(it.strategy_code) ?? { name: it.strategy_name, candidates: [] };
    e.candidates.push(it);
    m.set(it.strategy_code, e);
  }
  return m;
}

export function StrategyMatchMatrix({ date }: Props) {
  const { data: briefing, isLoading: briefingLoading } = usePreMarketBriefing(date);
  // S094 R24：涨停 scored_candidates + 非涨停 market_scan_scored 分两 region
  const limitup = briefing?.scored_candidates ?? [];
  const marketScan = briefing?.market_scan_scored ?? [];
  const [view, setView] = useState<"matrix" | "byStrategy">("matrix");

  const limitupCodes = groupByCode(limitup);
  const marketScanCodes = groupByCode(marketScan);
  const allStrats = groupByStrategy([...limitup, ...marketScan]);

  const askAiContext = [
    `当前页面：战法匹配（${view === "matrix" ? "票×战法 matrix" : "按战法分列"}）`,
    `涨停战法 ${limitup.length} 条（${limitupCodes.size} 只候选）| 非涨停战法 ${marketScan.length} 条（${marketScanCodes.size} 只）| 共 ${allStrats.size} 战法`,
    view === "matrix"
      ? `涨停 top10：${Array.from(limitupCodes.entries()).sort((a, b) => b[1].topScore - a[1].topScore).slice(0, 10).map(([c, e]) => `${c}(${e.hits.map((h) => h.strategy_code).join("+")})`).join("、")} | 非涨停 top10：${Array.from(marketScanCodes.entries()).sort((a, b) => b[1].topScore - a[1].topScore).slice(0, 10).map(([c, e]) => `${c}(${e.hits.map((h) => h.strategy_code).join("+")})`).join("、")}`
      : `按战法：${Array.from(allStrats.entries()).map(([s, e]) => `${s}:${e.candidates.length}`).join("、")}`,
  ].join("\n");

  if (briefingLoading) {
    return (
      <GlassCard className="p-4">
        <p className="text-sm text-muted-foreground">战法匹配加载中…</p>
      </GlassCard>
    );
  }
  if (limitup.length === 0 && marketScan.length === 0) {
    return (
      <GlassCard className="p-4">
        <p className="text-sm text-muted-foreground">暂无战法命中数据（briefing 未 done 或无候选），点右上角刷新按钮触发采集</p>
      </GlassCard>
    );
  }

  return (
    <div className="space-y-3">
      <div className="flex gap-2">
        <Button variant={view === "matrix" ? "primary" : "ghost"} size="sm" onClick={() => setView("matrix")}>
          票×战法 matrix
        </Button>
        <Button variant={view === "byStrategy" ? "primary" : "ghost"} size="sm" onClick={() => setView("byStrategy")}>
          按战法分列
        </Button>
      </div>

      {limitup.length > 0 && (
        <ScoredRegion title="涨停战法" scored={limitup} view={view} />
      )}
      {marketScan.length > 0 && (
        <ScoredRegion title="非涨停战法" subtitle="§44 未验证" scored={marketScan} view={view} />
      )}

      <AskAiButton context={askAiContext} />
    </div>
  );
}

/** S094 R24：单个 pipeline 的战法命中区（matrix / byStrategy 双视图）。涨停/非涨停各一实例。 */
function ScoredRegion({
  title,
  subtitle,
  scored,
  view,
}: {
  title: string;
  subtitle?: string;
  scored: ScoredCandidate[];
  view: "matrix" | "byStrategy";
}) {
  const byCode = groupByCode(scored);
  const byStrategy = groupByStrategy(scored);
  const codes = Array.from(byCode.entries()).sort((a, b) => b[1].topScore - a[1].topScore);
  const strats = Array.from(byStrategy.entries());

  return (
    <div className="space-y-2">
      <div className="flex items-center gap-2">
        <h3 className="font-semibold">{title}</h3>
        {subtitle && <span className="rounded bg-muted/30 px-1 text-[10px] text-muted-foreground">{subtitle}</span>}
        <Badge variant="info">{byCode.size} 只候选</Badge>
      </div>
      {view === "matrix" ? (
        <GlassCard className="p-4">
          <p className="mb-3 text-xs text-muted-foreground/60">战法后"分N" = 策略分 strategy_score（0-100，权重集加权），非 confidence</p>
          <div className="space-y-1">
            {codes.map(([code, e]) => (
              <div key={code} className="flex items-center gap-2 py-1.5 text-sm border-b border-border/20 last:border-0">
                <span className="w-24 shrink-0 truncate font-mono text-foreground">{code}</span>
                <span className="w-32 shrink-0 truncate text-muted-foreground/70">{e.name}</span>
                <div className="flex flex-wrap gap-1">
                  {e.hits.map((h) => (
                    <Badge key={h.strategy_code} variant={h.weather_recommended ? "primary" : "default"}>
                      {h.strategy_name} 分{h.strategy_score}
                    </Badge>
                  ))}
                </div>
              </div>
            ))}
          </div>
        </GlassCard>
      ) : (
        <div className="space-y-2">
          {strats.map(([stratCode, e]) => (
            <GlassCard key={stratCode} className="p-4">
              <div className="mb-2 flex items-center gap-2">
                <h3 className="font-semibold">{e.name}</h3>
                <Badge variant="info">{e.candidates.length} 只</Badge>
                <span className="text-xs text-muted-foreground/50">{stratCode}</span>
              </div>
              <div className="flex flex-wrap gap-2">
                {e.candidates.map((c) => (
                  <span key={c.code} className="rounded border border-border/40 px-2 py-0.5 text-xs">
                    {c.name}({c.code}) <span className="text-muted-foreground/60">分{c.strategy_score}</span>
                  </span>
                ))}
              </div>
            </GlassCard>
          ))}
        </div>
      )}
    </div>
  );
}
