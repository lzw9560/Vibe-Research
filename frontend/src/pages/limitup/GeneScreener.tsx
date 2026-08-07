// S029 涨停基因选股 — 接通 GeneScreener 页（条件可配 B1 + 执行检索 + 可展开多层明细 A3）。
// loadData 调真实 /api/limitup/screener；阈值改后保存+trigger 重算；摘要 扫描N/合格M/高基因K。
import { useState, useEffect, useCallback } from "react";
import { Link } from "react-router-dom";
import { PageHeader } from "@/components/ui/PageHeader";
import { GeneFilterForm, type GeneFilterParams } from "./components/GeneFilterForm";
import { GeneResultTable } from "./components/GeneResultTable";
import { Disclaimer } from "@/components/ui/Disclaimer";
import { GlassCard } from "@/components/ui/GlassCard";
import {
  getGeneScreener,
  saveGeneParams,
  triggerGenePrecompute,
  type GeneScreenerParams,
} from "@/lib/limitup";
import type { GeneScore, ScreenerResult } from "@/lib/api";

export function GeneScreener() {
  const [data, setData] = useState<GeneScore[]>([]);
  const [allCount, setAllCount] = useState(0);
  const [qualifiedCount, setQualifiedCount] = useState(0);
  const [highCount, setHighCount] = useState(0);
  const [freshness, setFreshness] = useState<string>("");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [recomputeBusy, setRecomputeBusy] = useState(false);
  const [recomputeMsg, setRecomputeMsg] = useState<string | null>(null);
  const [expandedCode, setExpandedCode] = useState<string | null>(null);

  const doSearch = useCallback(async (params: GeneFilterParams) => {
    setLoading(true);
    setError(null);
    try {
      const result: ScreenerResult = await getGeneScreener(params.date);
      const all = result.gene_scores ?? [];
      const filtered = all.filter(
        (g) => g.total_score >= params.minScore && g.total_score <= params.maxScore,
      );
      // 按得分降序
      filtered.sort((a, b) => b.total_score - a.total_score);
      setData(filtered);
      setAllCount(all.length);
      setQualifiedCount(all.filter((g) => g.qualify).length);
      setHighCount(all.filter((g) => g.high_gene).length);
      setFreshness(result.data_freshness ?? "");
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
      setData([]);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    doSearch({
      minScore: 60,
      maxScore: 100,
      date: new Date().toISOString().slice(0, 10),
    });
  }, [doSearch]);

  const handleRecompute = useCallback(async (params: GeneScreenerParams) => {
    setRecomputeBusy(true);
    setRecomputeMsg(null);
    setError(null);
    try {
      await saveGeneParams(params);
      await triggerGenePrecompute();
      setRecomputeMsg("阈值已保存，后台预计算进行中（~90s 落库）。稍后点「筛选」刷新 qualify/高基因标志。");
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setRecomputeBusy(false);
    }
  }, []);

  const handleToggle = (code: string) => {
    setExpandedCode((prev) => (prev === code ? null : code));
  };

  return (
    <div>
      <PageHeader title="基因筛选" subtitle="Gene Screener（盘前简报的配置伴随页）" actions={<Link to="/workflow/pre-market" className="text-sm text-muted-foreground transition-colors hover:text-primary">← 回盘前简报</Link>} />

      <GeneFilterForm onSearch={doSearch} onRecompute={handleRecompute} recomputeBusy={recomputeBusy} />

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
        {error && (
          <p className="mt-2 text-xs text-warning">检索失败：{error}</p>
        )}
      </GlassCard>

      <GeneResultTable
        data={data}
        loading={loading}
        expandedCode={expandedCode}
        onToggle={handleToggle}
      />

      <Disclaimer />
    </div>
  );
}

export default GeneScreener;
