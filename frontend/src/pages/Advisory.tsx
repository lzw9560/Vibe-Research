import { useState, useEffect, useCallback } from "react";
import { Loader2, RefreshCw, Info } from "lucide-react";
import { PageHeader } from "@/components/ui/PageHeader";
import { GlassCard } from "@/components/ui/GlassCard";
import { EmptyState } from "@/components/ui/EmptyState";
import { Disclaimer } from "@/components/ui/Disclaimer";
import { api, type AdvisoryItem, type AdvisorySummary } from "@/lib/api";
import { AskAiButton } from "@/components/ui/AskAiButton";

// S042 建议中心：三场景（推荐/自选/持仓）建议，教育研究式口吻，非交易指令。
// win_rate_source 标注来源（backtest_90d / synthetic / none），透明可审计。

const ACTION_META: Record<AdvisoryItem["action"], { color: string; bg: string; label: string }> = {
  enter: { color: "text-emerald-600", bg: "bg-emerald-50", label: "入场" },
  add: { color: "text-emerald-600", bg: "bg-emerald-50", label: "加仓" },
  hold: { color: "text-gray-600", bg: "bg-gray-50", label: "持有" },
  reduce: { color: "text-amber-600", bg: "bg-amber-50", label: "减仓" },
  close: { color: "text-red-600", bg: "bg-red-50", label: "清仓" },
  no_signal: { color: "text-gray-500", bg: "bg-gray-50", label: "无信号" },
};

const SOURCE_LABEL: Record<AdvisoryItem["win_rate_source"], string> = {
  backtest_90d: "90天回测",
  synthetic: "合成估算",
  none: "无数据",
};

function winRateText(item: AdvisoryItem): string {
  if (item.win_rate === null) return "—";
  return `${(item.win_rate * 100).toFixed(0)}%`;
}

function AdvisoryCard({ item }: { item: AdvisoryItem }) {
  const meta = ACTION_META[item.action] ?? ACTION_META.hold;
  return (
    <GlassCard className="flex flex-col gap-2">
      <div className="flex items-center justify-between">
        <div>
          <div className="text-base font-semibold">{item.name}</div>
          <div className="text-xs text-muted-foreground">{item.code}</div>
        </div>
        <span className={`rounded-full px-2 py-1 text-xs font-medium ${meta.color} ${meta.bg}`}>
          {meta.label}
        </span>
      </div>

      <div className="flex flex-wrap items-center gap-x-3 gap-y-1 text-xs text-muted-foreground">
        <span>
          回测胜率：<span className="font-medium text-foreground">{winRateText(item)}</span>
          <span className="ml-1 text-[10px]">({SOURCE_LABEL[item.win_rate_source]})</span>
        </span>
        {item.matched_strategy && (
          <span>战法：<span className="font-medium text-foreground">{item.matched_strategy}</span></span>
        )}
        {item.scene === "recommendation" && item.suggested_pct !== undefined && (
          <span>研究仓位：<span className="font-medium text-foreground">{(item.suggested_pct * 100).toFixed(0)}%</span></span>
        )}
        {item.scene === "holding" && item.pnl_pct != null && (
          <span>浮动盈亏：<span className="font-medium text-foreground">{item.pnl_pct >= 0 ? "+" : ""}{item.pnl_pct.toFixed(2)}%</span></span>
        )}
        {item.scene === "holding" && item.pnl_pct == null && (
          <span>浮动盈亏：<span className="font-medium text-muted-foreground">数据缺失</span></span>
        )}
        {item.scene === "recommendation" && item.gene_score !== undefined && (
          <span>基因：<span className="font-medium text-foreground">{item.gene_score.toFixed(0)}</span></span>
        )}
      </div>

      <div className="space-y-1">
        {item.reasons.slice(0, 3).map((r, i) => (
          <div key={i} className="text-xs text-muted-foreground">• {r}</div>
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
}

function Section({
  title,
  items,
  loading,
}: {
  title: string;
  items: AdvisoryItem[];
  loading: boolean;
}) {
  return (
    <div className="space-y-2">
      <h2 className="text-sm font-semibold text-muted-foreground">{title}（{items.length}）</h2>
      {items.length > 0 ? (
        <div className="grid gap-3 md:grid-cols-2">
          {items.map((item) => (
            <AdvisoryCard key={`${item.scene}-${item.code}`} item={item} />
          ))}
        </div>
      ) : (
        !loading && (
          <GlassCard>
            <div className="p-4 text-sm text-muted-foreground">暂无数据</div>
          </GlassCard>
        )
      )}
    </div>
  );
}

export default function Advisory() {
  const [summary, setSummary] = useState<AdvisorySummary | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const data = await api.advisorySummary(20);
      setSummary(data);
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : "加载失败");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    load();
  }, [load]);

  // S066 AskAi：注入三场景建议汇总
  const askAiContext = [
    `当前页面：建议中心（Advisory）`,
    summary ? `推荐${summary.recommendations.length}只/自选${summary.watchlist.length}只/持仓${summary.holdings.length}只` : `建议：未取得`,
    summary && summary.recommendations.length > 0
      ? `推荐入场：${summary.recommendations.slice(0, 8).map((r) => `${r.code}(${r.name})${r.action}[胜率${r.win_rate != null ? (r.win_rate * 100).toFixed(0) + "%" : "无"}/${r.matched_strategy ?? "未匹配"}]`).join("，")}`
      : ``,
    summary && summary.holdings.length > 0
      ? `持仓建议：${summary.holdings.slice(0, 5).map((h) => `${h.code}(${h.name})${h.action}盈${(h as any).pnl_pct?.toFixed(1) ?? "?"}%`).join("，")}`
      : ``,
    summary?.partial ? `⚠ 端点超时降级（partial=true），部分场景未返回` : ``,
  ].filter(Boolean).join("\n");

  return (
    <div className="space-y-4">
      <PageHeader
        title="建议中心"
        subtitle="推荐 / 自选 / 持仓三场景建议（基于 90 天回测胜率，教育研究式，非交易指令）"
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

      {summary ? (
        <>
          <Section title="推荐标的入场建议" items={summary.recommendations} loading={loading} />
          <Section title="自选股建议" items={summary.watchlist} loading={loading} />
          <Section title="持仓建议" items={summary.holdings} loading={loading} />
        </>
      ) : (
        !loading &&
        !error && (
          <EmptyState
            icon={<Info className="h-8 w-8 text-muted-foreground/40" />}
            title="暂无建议数据"
            description="未取得建议，稍后再试。"
          />
        )
      )}
    </div>
  );
}
