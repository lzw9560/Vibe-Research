import { useState, useEffect } from "react";
import { Loader2, RefreshCw } from "lucide-react";
import { PageHeader } from "@/components/ui/PageHeader";
import { GlassCard } from "@/components/ui/GlassCard";
import { Disclaimer } from "@/components/ui/Disclaimer";
import { api, type StockRecommendation } from "@/lib/api";
import { AskAiButton } from "@/components/ui/AskAiButton";
import { MultiArmPanel } from "@/components/recommendation/MultiArmPanel";

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
        subtitle="模拟盘跟踪·§44 证否的基因分（无 selection edge）·真盘你定"
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

      {/* S175 R7（SH4 真止血）：§44-falsified 警告横幅——gene_score 已证否无 selection edge */}
      <div className="rounded-lg border border-amber-300/60 bg-amber-50/80 p-3 text-xs leading-relaxed text-amber-800">
        <span className="font-semibold">⚠️ §44 已证否提示：</span>
        本页推荐基于基因得分（gene_score），但 §44v2 12 harness 验证已证否——gene_score 对 path-winrate
        无选股 edge（rho≈0）。此处仅为历史数据呈现，<b>非已验证的 selection 信号</b>。真盘交易由你决策。
        S175 多臂推荐 engine rework 后将替换为各臂 honest_label（floor=外部验证 actionable / breakout=§44证否 paper-only / 等）。
      </div>

      {error && (
        <GlassCard>
          <div className="p-4 text-sm text-red-600">加载失败：{error}</div>
        </GlassCard>
      )}

      <MultiArmPanel />
    </div>
  );
}
