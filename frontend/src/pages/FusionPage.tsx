import { useState, type FormEvent } from "react";
import { Search, Loader2, AlertCircle, Sparkles } from "lucide-react";
import { PageHeader } from "@/components/ui/PageHeader";
import { GlassCard } from "@/components/ui/GlassCard";
import { Disclaimer } from "@/components/ui/Disclaimer";
import { authHeaders } from "@/lib/api";

// FE-6（backlog）：S194 fusion 前端展示——输股票代码查融合研判（regime/方向/置信度/信号权重/top 相似 case）。
// 调后端 /api/fusion/{code}（fusion_pipeline.compute_fusion_for_query 最新交易日）。
// ⚠️ S194 Phase 3a 结论：FS2 融合无 validated edge（R5 no_contribution）；本页展示的是融合研判产出（喂 AI），
//    非交易信号——regime/方向/置信度是研究性判断原料，最终决策由用户（§1 弱合规）。
interface FusionOutput {
  regime: string;
  direction: string;
  confidence: number;
  top_similar_cases: { case: { stock: string; entry_date: string; arm: string }; similarity: number; outcome: string }[];
  signal_weights: Record<string, number>;
}
interface FusionResp {
  data: { fusion: FusionOutput; context_text: string };
}

export default function FusionPage() {
  const [code, setCode] = useState("");
  const [result, setResult] = useState<FusionOutput | null>(null);
  const [contextText, setContextText] = useState("");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function handleSearch(e: FormEvent) {
    e.preventDefault();
    const c = code.trim();
    if (!c || loading) return;
    setLoading(true);
    setError(null);
    setResult(null);
    setContextText("");
    try {
      const resp = await fetch(`/api/fusion/${c}`, { headers: { ...authHeaders() } });
      if (!resp.ok) {
        const err = await resp.json().catch(() => ({}));
        throw new Error(err.detail || `HTTP ${resp.status}`);
      }
      const json: FusionResp = await resp.json();
      setResult(json.data.fusion);
      setContextText(json.data.context_text);
    } catch (err) {
      setError(err instanceof Error ? err.message : "融合研判查询失败");
    } finally {
      setLoading(false);
    }
  }

  return (
    <div className="flex flex-col gap-4">
      <PageHeader title="信号融合研判" subtitle="S194：regime/方向/置信度/信号权重/top 相似 case（研究性判断，非交易信号）" />
      <form onSubmit={handleSearch} className="flex items-center gap-2">
        <input
          value={code}
          onChange={(e) => setCode(e.target.value)}
          placeholder="6 位股票代码，如 600519"
          className="w-64 rounded-lg border px-3 py-2 text-sm dark:bg-gray-900 dark:text-gray-100"
        />
        <button type="submit" disabled={loading || !code.trim()} className="rounded-lg bg-primary px-4 py-2 text-sm text-white hover:bg-primary disabled:opacity-50">
          {loading ? <Loader2 className="h-4 w-4 animate-spin" /> : <Search className="h-4 w-4" />}
          <span className="ml-1">查询</span>
        </button>
      </form>

      {error && (
        <GlassCard className="p-3 text-sm text-red-600">
          <AlertCircle className="mr-2 inline h-4 w-4" />{error}
        </GlassCard>
      )}

      {result && (
        <>
          <GlassCard className="p-4">
            <div className="mb-3 flex items-center gap-2 text-sm font-medium">
              <Sparkles className="h-4 w-4" />{code} 融合研判（最新交易日）
            </div>
            <div className="grid grid-cols-2 gap-3 text-sm sm:grid-cols-4">
              <div><div className="text-xs text-muted-foreground">regime</div><div className="font-medium">{result.regime}</div></div>
              <div><div className="text-xs text-muted-foreground">方向</div><div className="font-medium">{result.direction}</div></div>
              <div><div className="text-xs text-muted-foreground">置信度</div><div className="font-medium">{(result.confidence * 100).toFixed(0)}%</div></div>
              <div>
                <div className="text-xs text-muted-foreground">信号权重</div>
                <div className="text-xs">{Object.entries(result.signal_weights).map(([k, v]) => `${k}=${v.toFixed(2)}`).join(" / ") || "（无）"}</div>
              </div>
            </div>
          </GlassCard>

          <GlassCard className="p-4">
            <div className="mb-2 text-sm font-medium">历史相似 case（FS1 检索，不过§44，定性参考）</div>
            {result.top_similar_cases.length === 0 ? (
              <div className="text-sm text-muted-foreground">无相似 case（case 库空或信号值全 0）</div>
            ) : (
              <table className="w-full text-sm">
                <thead className="text-xs text-muted-foreground">
                  <tr><th className="px-2 py-1 text-left">股票</th><th className="px-2 py-1 text-left">入场日</th><th className="px-2 py-1 text-left">arm</th><th className="px-2 py-1 text-right">相似度</th><th className="px-2 py-1 text-left">结果</th></tr>
                </thead>
                <tbody>
                  {result.top_similar_cases.map((c, i) => (
                    <tr key={i} className="border-t dark:border-gray-800">
                      <td className="px-2 py-1 font-mono">{c.case.stock}</td>
                      <td className="px-2 py-1">{c.case.entry_date}</td>
                      <td className="px-2 py-1">{c.case.arm}</td>
                      <td className="px-2 py-1 text-right">{c.similarity.toFixed(2)}</td>
                      <td className="px-2 py-1">{c.outcome}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            )}
          </GlassCard>

          {contextText && (
            <GlassCard className="p-4">
              <div className="mb-2 text-sm font-medium">注入 AI system prompt 的文本块</div>
              <pre className="whitespace-pre-wrap text-xs text-gray-600 dark:text-gray-300">{contextText}</pre>
            </GlassCard>
          )}
        </>
      )}
      <Disclaimer />
    </div>
  );
}
