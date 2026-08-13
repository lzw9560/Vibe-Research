import { useState, useEffect, useCallback } from "react";
import { Flame, Loader2, RefreshCw, Info } from "lucide-react";
import { useQuery } from "@tanstack/react-query";
import { PageHeader } from "@/components/ui/PageHeader";
import { GlassCard } from "@/components/ui/GlassCard";
import { AskAiButton } from "@/components/ui/AskAiButton";
import { Disclaimer } from "@/components/ui/Disclaimer";
import { BombAlertBanner } from "@/components/risk/BombAlertBanner";
import { api } from "@/lib/api";
import { ExpandableTable } from "./limitup/components/ExpandableTable";
import { AuctionScreenerSection } from "./limitup/components/AuctionScreenerSection";
import { SeatEngineSection } from "./limitup/components/SeatEngineSection";
import type { ScreenerResult, LimitUpAnalysis } from "@/lib/api";
// S051 D4：阈值动态化——读 GET /api/limitup/screener/params，不写死 60/75
import { getGeneParams } from "@/lib/limitup";

const fmtPct = (v: number | null | undefined) => v == null ? "—" : `${v.toFixed(1)}%`;

export function LimitUpStrategy() {
  const [screener, setScreener] = useState<ScreenerResult | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [expandedCode, setExpandedCode] = useState<string | null>(null);
  const [expandedData, setExpandedData] = useState<LimitUpAnalysis | null>(null);
  const [expandedLoading, setExpandedLoading] = useState(false);
  const [expandedError, setExpandedError] = useState<string | null>(null);

  // S051 D4：阈值动态化——读 GET /api/limitup/screener/params，不写死 60/75
  const { data: params } = useQuery({
    queryKey: ["limitup", "params"],
    queryFn: () => getGeneParams(),
    staleTime: 5 * 60 * 1000,
  });
  const qualifyThreshold = params?.gene_qualify_threshold ?? 50;
  const highThreshold = params?.gene_high_threshold ?? 60;

  const loadScreener = useCallback(() => {
    setLoading(true);
    setError(null);
    api.limitupScreener()
      .then(setScreener)
      .catch((e) => setError(e instanceof Error ? e.message : "加载失败"))
      .finally(() => setLoading(false));
  }, []);

  useEffect(() => { loadScreener(); }, [loadScreener]);

  const handleToggle = useCallback((code: string) => {
    setExpandedCode((prev) => {
      if (prev === code) {
        setExpandedData(null);
        setExpandedError(null);
        return null;
      }
      setExpandedLoading(true);
      setExpandedError(null);
      setExpandedData(null);
      api.limitupAnalysis(code)
        .then(setExpandedData)
        .catch((e) => setExpandedError(e instanceof Error ? e.message : "加载失败"))
        .finally(() => setExpandedLoading(false));
      return code;
    });
  }, []);

  const aiContext = screener
    ? `【打板策略 - 基因得分清单】\n日期: ${screener.date}\n基因合格: ${screener.qualified.length} 只\n高基因: ${screener.high_gene.length} 只\n\n`
    + screener.gene_scores.map((g) => `  ${g.code} ${g.name}: 总分${g.total_score} | 溢价率${fmtPct(g.factors["次日溢价率"])} | 红盘率${fmtPct(g.factors["红盘率"])}`).join("\n")
    : "";

  const today = new Date().toLocaleDateString("zh-CN", { year: "numeric", month: "2-digit", day: "2-digit" });

  return (
    <div>
      <PageHeader
        title="打板策略"
        subtitle={`${today} · 涨停基因选股 · 策略逻辑教育 · 历史统计特征`}
        actions={
          <div className="flex items-center gap-2">
            <AskAiButton context={aiContext} label="问 AI"
              suggestions={["高基因股的历史统计特征", "基因得分和次日表现关系", "风控规则"]} />
            <button onClick={loadScreener} className="inline-flex items-center gap-1.5 rounded-lg bg-primary/15 px-3 py-1.5 text-sm font-medium text-primary hover:bg-primary/25" title="刷新">
              {loading ? <Loader2 className="h-4 w-4 animate-spin" /> : <RefreshCw className="h-4 w-4" />}
              刷新
            </button>
          </div>
        }
      />

      {/* S055：炸板预警横幅 */}
      <BombAlertBanner />

      {/* 统计摘要 */}
      <div className="mb-6 grid gap-4 sm:grid-cols-2">
        <GlassCard className="p-4">
          <div className="flex items-center gap-2">
            <Flame className="h-5 w-5 text-primary" />
            <h3 className="text-sm font-semibold text-muted-foreground">基因合格</h3>
          </div>
          <p className="mt-2 text-3xl font-bold text-primary">{loading ? <Loader2 className="h-6 w-6 animate-spin" /> : screener?.qualified.length ?? "—"}</p>
          <p className="mt-1 text-xs text-muted-foreground">SCORE ≥ {qualifyThreshold}（合格线）</p>
        </GlassCard>
        <GlassCard className="p-4">
          <div className="flex items-center gap-2">
            <Flame className="h-5 w-5 text-primary" />
            <h3 className="text-sm font-semibold text-muted-foreground">高基因股票</h3>
          </div>
          <p className="mt-2 text-3xl font-bold text-primary">{loading ? <Loader2 className="h-6 w-6 animate-spin" /> : screener?.high_gene.length ?? "—"}</p>
          <p className="mt-1 text-xs text-muted-foreground">SCORE ≥ {highThreshold}（高基因线）</p>
        </GlassCard>
      </div>

      {/* 基因得分清单 */}
      <GlassCard className="mb-6 p-4">
        <div className="mb-3 flex items-center gap-2">
          <h3 className="text-sm font-semibold text-muted-foreground">涨停股基因得分清单</h3>
          <span className="text-[11px] text-muted-foreground/50">客观数据，非推荐</span>
        </div>
        {error ? (
          <div className="flex items-center justify-center py-8 text-sm text-destructive"><Info className="mr-1.5 h-4 w-4" /> {error}</div>
        ) : (
          <ExpandableTable data={screener?.gene_scores ?? []} expandedCode={expandedCode} expandedData={expandedData}
            expandedLoading={expandedLoading} expandedError={expandedError} onToggle={handleToggle} />
        )}
      </GlassCard>

      {/* 子组件 */}
      <AuctionScreenerSection />
      <SeatEngineSection />

      {/* 免责声明 */}
      <div className="flex items-start gap-2 rounded-lg border border-border/40 bg-muted/10 p-2.5 text-[11px] leading-relaxed text-muted-foreground/60">
        <Info className="mt-0.5 h-3 w-3 shrink-0" />
        <span>本页面所有数据基于<strong>历史统计特征</strong>，不代表未来行为，<strong>不构成投资建议</strong>。</span>
      </div>
      <Disclaimer />
    </div>
  );
}

export default LimitUpStrategy;
