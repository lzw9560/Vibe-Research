import { useState, useEffect } from "react";
import { Loader2, RefreshCw, Info } from "lucide-react";
import { PageHeader } from "@/components/ui/PageHeader";
import { GlassCard } from "@/components/ui/GlassCard";
import { EmptyState } from "@/components/ui/EmptyState";
import { Disclaimer } from "@/components/ui/Disclaimer";
import { api, type StockRecommendation, type RecommendationLevel } from "@/lib/api";
import { AskAiButton } from "@/components/ui/AskAiButton";

const LEVEL_META: Record<RecommendationLevel, { color: string; bg: string; label: string }> = {
  "高质量关注": { color: "text-emerald-600", bg: "bg-emerald-50", label: "HIGH" },
  "中等质量关注": { color: "text-amber-600", bg: "bg-amber-50", label: "MEDIUM" },
  "低质量关注": { color: "text-gray-600", bg: "bg-gray-50", label: "LOW" },
  "策略逻辑上回避": { color: "text-red-600", bg: "bg-red-50", label: "AVOID" },
};

export default function Recommendation() {
  const [items, setItems] = useState<StockRecommendation[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const load = async () => {
    setLoading(true);
    setError(null);
    try {
      const data = await api.recommendationToday(20);
      setItems(data);
    } catch (e: any) {
      setError(e?.message ?? "加载失败");
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    load();
  }, []);

  // S066 AskAi：注入推荐关注清单
  const askAiContext = [
    `当前页面：推荐关注（Recommendation）`,
    `共 ${items.length} 只`,
    items.length > 0
      ? `推荐：${items.slice(0, 10).map((i) => `${i.code}(${i.name})${i.level}/基因${i.gene_score}/仓位${i.position_suggestion}`).join("，")}`
      : `推荐：未取得`,
  ].join("\n");

  return (
    <div className="space-y-4">
      <PageHeader
        title="推荐关注"
        subtitle="基于基因得分的教育研究式关注清单（非交易建议）"
        actions={
          <div className="flex items-center gap-2">
            <AskAiButton context={askAiContext} />
            <button
              onClick={load}
              disabled={loading}
              className="inline-flex items-center gap-2 rounded-lg bg-primary/90 px-3 py-2 text-sm text-primary-foreground hover:bg-primary disabled:opacity-60"
            >
              {loading ? <Loader2 className="h-4 w-4 animate-spin" /> : <RefreshCw className="h-4 w-4" />}
              刷新
            </button>
          </div>
        }
      />

      <Disclaimer compact />

      {error && (
        <GlassCard>
          <div className="p-4 text-sm text-red-600">加载失败：{error}</div>
        </GlassCard>
      )}

      <div className="grid gap-3 md:grid-cols-2">
        {items.map((item) => {
          const meta = LEVEL_META[item.level] ?? LEVEL_META["低质量关注"];
          return (
            <GlassCard key={item.code} className="flex flex-col gap-2">
              <div className="flex items-center justify-between">
                <div>
                  <div className="text-base font-semibold">{item.name}</div>
                  <div className="text-xs text-muted-foreground">{item.code}</div>
                </div>
                <span className={`rounded-full px-2 py-1 text-xs font-medium ${meta.color} ${meta.bg}`}>
                  {meta.label}
                </span>
              </div>

              <div className="flex items-center gap-3 text-xs text-muted-foreground">
                <span>基因得分：<span className="font-medium text-foreground">{item.gene_score.toFixed(1)}</span></span>
                <span>研究仓位：<span className="font-medium text-foreground">{item.position_suggestion}</span></span>
              </div>

              <div className="space-y-1">
                {item.reasoning.slice(0, 2).map((r, i) => (
                  <div key={`reason-${i}-${r.slice(0, 12)}`} className="text-xs text-muted-foreground">• {r}</div>
                ))}
              </div>

              {item.risk_notes.length > 0 && (
                <div className="flex items-start gap-1 rounded-lg bg-amber-50 p-2 text-xs text-amber-700">
                  <Info className="mt-0.5 h-3.5 w-3.5 shrink-0" />
                  <span>{item.risk_notes[0]}</span>
                </div>
              )}
            </GlassCard>
          );
        })}
      </div>

      {!loading && items.length === 0 && (
        <EmptyState
          icon={<Info className="h-8 w-8 text-muted-foreground/40" />}
          title="暂无推荐数据"
          description="当前没有符合条件的关注标的，稍后再试。"
        />
      )}
    </div>
  );
}
