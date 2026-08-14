// S029 涨停基因选股 — 接通 GeneScreener 页（条件可配 B1 + 执行检索 + 可展开多层明细 A3）。
// S051 D3：分段视图 qualified/all/custom——doSearch 始终拉全量，按 viewMode 过滤。
import { useState, useCallback } from "react";
import { Link } from "react-router-dom";
import { PageHeader } from "@/components/ui/PageHeader";
import { GeneFilterForm, type GeneFilterParams, type ViewMode } from "./components/GeneFilterForm";
import { GeneResultTable } from "./components/GeneResultTable";
import { Disclaimer } from "@/components/ui/Disclaimer";
import { GlassCard } from "@/components/ui/GlassCard";
import { AskAiButton } from "@/components/ui/AskAiButton";
import {
  getGeneScreener,
  saveGeneParams,
  triggerGenePrecompute,
  type GeneScreenerParams,
} from "@/lib/limitup";
import type { GeneScore, ScreenerResult } from "@/lib/api";

export function GeneScreener() {
  const [data, setData] = useState<GeneScore[]>([]);
  const [allScores, setAllScores] = useState<GeneScore[]>([]);  // S051 D3：全量留底，viewMode 切换不重查
  const [viewMode, setViewMode] = useState<ViewMode>("qualified");
  const [allCount, setAllCount] = useState(0);
  const [qualifiedCount, setQualifiedCount] = useState(0);
  const [highCount, setHighCount] = useState(0);
  const [freshness, setFreshness] = useState<string>("");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [recomputeBusy, setRecomputeBusy] = useState(false);
  const [recomputeMsg, setRecomputeMsg] = useState<string | null>(null);
  const [recomputeWarnings, setRecomputeWarnings] = useState<string[]>([]);
  const [expandedCode, setExpandedCode] = useState<string | null>(null);

  // S051 D3：doSearch 始终拉全量；按 viewMode 过滤（qualified→qualify 标志；all→全量；custom→分数段）
  const applyView = useCallback((all: GeneScore[], mode: ViewMode, params: GeneFilterParams) => {
    let filtered: GeneScore[];
    if (mode === "qualified") {
      filtered = all.filter((g) => g.qualify);
    } else if (mode === "all") {
      filtered = [...all];
    } else {
      filtered = all.filter((g) => g.total_score >= params.minScore && g.total_score <= params.maxScore);
    }
    filtered.sort((a, b) => b.total_score - a.total_score);
    setData(filtered);
  }, []);

  const doSearch = useCallback(async (params: GeneFilterParams, mode: ViewMode) => {
    setLoading(true);
    setError(null);
    setViewMode(mode);
    try {
      const result: ScreenerResult = await getGeneScreener(params.date);
      const all = result.gene_scores ?? [];
      setAllScores(all);
      setAllCount(all.length);
      setQualifiedCount(all.filter((g) => g.qualify).length);
      setHighCount(all.filter((g) => g.high_gene).length);
      setFreshness(result.data_freshness ?? "");
      applyView(all, mode, params);
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
      setData([]);
    } finally {
      setLoading(false);
    }
  }, [applyView]);

  // S051 D3：viewMode 切换不重查（用已拉全量）
  const switchView = useCallback((mode: ViewMode, params: GeneFilterParams) => {
    setViewMode(mode);
    applyView(allScores, mode, params);
  }, [allScores, applyView]);

  const handleRecompute = useCallback(async (params: GeneScreenerParams) => {
    setRecomputeBusy(true);
    setRecomputeMsg(null);
    setRecomputeWarnings([]);
    setError(null);
    try {
      const resp = await saveGeneParams(params);
      await triggerGenePrecompute();
      setRecomputeMsg("阈值已保存，后台预计算进行中（~90s 落库）。稍后点「筛选」刷新 qualify/高基因标志。");
      // S051 D2：sanity warnings 回显
      if (resp?.warnings?.length) {
        setRecomputeWarnings(resp.warnings);
      }
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setRecomputeBusy(false);
    }
  }, []);

  const handleToggle = (code: string) => {
    setExpandedCode((prev) => (prev === code ? null : code));
  };

  // S066 AskAi：注入页面真实数据（扫描/合格/高基因 + top 候选五因子 + 回测）
  const topGenes = [...data].sort((a, b) => b.total_score - a.total_score).slice(0, 10);
  const askAiContext = [
    `当前页面：涨停基因筛选（GeneScreener）`,
    `数据新鲜度：${freshness || "未取得"}`,
    `扫描 ${allCount} 只 / 合格 ${qualifiedCount} 只 / 高基因 ${highCount} 只（视图：${viewMode}）`,
    topGenes.length > 0
      ? `Top 候选：${topGenes.map((g) => `${g.code}(${g.name})分${g.total_score}[qualify=${g.qualify}]`).join("，")}`
      : `候选：无（未检索或空池）`,
    topGenes.length > 0
      ? `五因子示例（${topGenes[0].code}）：${Object.entries(topGenes[0].factors).map(([k, v]) => `${k}=${(v as number).toFixed(1)}`).join("/")}，zt_count_250d=${topGenes[0].zt_count_250d}`
      : ``,
  ].filter(Boolean).join("\n");

  return (
    <div>
      <PageHeader title="基因筛选" subtitle="Gene Screener（盘前简报的配置伴随页）" actions={
        <div className="flex items-center gap-2">
          <AskAiButton context={askAiContext} />
          <Link to="/workflow/pre-market" className="text-sm text-muted-foreground transition-colors hover:text-primary">← 回盘前简报</Link>
        </div>
      } />

      <GeneFilterForm onSearch={doSearch} onSwitchView={switchView} viewMode={viewMode} onRecompute={handleRecompute} recomputeBusy={recomputeBusy} />

      {/* 摘要：扫描 N / 合格 M / 高基因 K + 数据新鲜度 */}
      <GlassCard className="mb-4 p-3">
        <div className="flex flex-wrap items-center gap-x-6 gap-y-1 text-sm">
          <span className="text-muted-foreground">
            扫描 <span className="font-bold text-foreground">{allCount}</span> 只
          </span>
          <span className="text-muted-foreground">
            合格 <span className="font-bold text-blue-400">{qualifiedCount}</span> 只
          </span>
          <span className="text-muted-foreground">
            高基因 <span className="font-bold text-primary">{highCount}</span> 只
          </span>
          {freshness && (
            <span className="text-xs text-muted-foreground/60">数据状态：{freshness}</span>
          )}
        </div>
        {recomputeMsg && (
          <p className="mt-2 text-xs text-primary">{recomputeMsg}</p>
        )}
        {recomputeWarnings.length > 0 && (
          <div className="mt-2 space-y-0.5">
            {recomputeWarnings.map((w, i) => (
              <p key={i} className="text-xs text-warning">⚠ {w}</p>
            ))}
          </div>
        )}
        {error && (
          <p className="mt-2 text-xs text-warning">检索失败：{error}</p>
        )}
      </GlassCard>

      <GeneResultTable
        data={data}
        loading={loading}
        expandedCode={expandedCode}
        onToggle={handleToggle}
        viewMode={viewMode}
      />

      <Disclaimer />
    </div>
  );
}

export default GeneScreener;
