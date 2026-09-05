import { useState } from "react";
import { RefreshCw, Info } from "lucide-react";
import { GlassCard } from "@/components/ui/GlassCard";
import { PageHeader } from "@/components/ui/PageHeader";
import { SectionHeader } from "@/components/ui/SectionHeader";
import { MetricCard } from "@/components/ui/MetricCard";
import { EmptyState } from "@/components/ui/EmptyState";
import { Skeleton } from "@/components/ui/Skeleton";
import { TabBar } from "@/components/ui/TabBar";
import { useAuctionTop } from "@/lib/query";
import { AskAiButton } from "@/components/ui/AskAiButton";
import { Monitor925 } from "@/components/auction/Monitor925";


// 页内 Tab key：auction = 竞价预案 TOP N，monitor = 盘中监控 9:25
type AuctionTab = "auction" | "monitor";

const TABS: { key: AuctionTab; label: string }[] = [
  { key: "auction", label: "竞价预案 TOP N" },
  { key: "monitor", label: "盘中监控 9:25" },
];

// ── 主页面：竞价选股（竞价预案 + 盘中监控页内 TabBar）──────────────────
export function AuctionScreener() {
  const [activeTab, setActiveTab] = useState<AuctionTab>("auction");
  const [selectedDate, setSelectedDate] = useState(new Date().toISOString().slice(0, 10));
  // T9：原 useState(result/loading/error) + useCallback(loadAuction) + useEffect([selectedDate])
  // → useAuctionTop(date)。date 在 queryKey 中，切换日期自动重新查询（arg-driven requery），
  // 移除手动 date-change effect；手动刷新走 refetch()。
  // 注：useAuctionTop 经 Opts 参数化 data 已推断为 AuctionScreenerResult | undefined，无需 cast。
  const { data: result, isLoading: loading, error, refetch } = useAuctionTop(selectedDate);
  const errMsg = error instanceof Error ? error.message : error ? String(error) : null;

  // S066 AskAi：注入竞价候选 + STI + 分析数
  const candidates = result?.candidates ?? [];
  const askAiContext = [
    `当前页面：竞价选股（AuctionScreener）`,
    `日期：${selectedDate}`,
    `分析 ${result?.total_analyzed ?? "--"} 只`,
    candidates.length > 0
      ? `竞价候选：${candidates.slice(0, 10).map((c) => `${c.code}(${c.name})评分${c.score}/基因${c.gene_score}/封板率${(c.seal_rate * 100).toFixed(0)}%`).join("，")}`
      : `竞价候选：未取得`,
  ].join("\n");

  return (
    <div className="space-y-4">
      <PageHeader
        title="竞价选股"
        subtitle="竞价选股模型（S072：STI 无 §44 edge 已去噪，honest 标注）与盘中监控"
        actions={
          activeTab === "auction" ? (
            <div className="flex items-center gap-2">
              <AskAiButton context={askAiContext} />
              <input
                type="date"
                value={selectedDate}
                onChange={(e) => setSelectedDate(e.target.value)}
                className="rounded-lg border border-border bg-black/20 px-2 py-1 text-xs outline-none focus:border-primary/50"
              />
              <button
                onClick={() => refetch()}
                className="text-muted-foreground hover:text-primary"
                title="刷新"
              >
                <RefreshCw className="h-3.5 w-3.5" />
              </button>
            </div>
          ) : undefined
        }
      />

      <TabBar
        tabs={TABS}
        activeKey={activeTab}
        onChange={(k) => setActiveTab(k as AuctionTab)}
      />

      {activeTab === "monitor" ? (
        <Monitor925 />
      ) : loading ? (
        <GlassCard>
          <div className="py-8">
            <Skeleton className="mx-auto h-6 w-48" />
          </div>
        </GlassCard>
      ) : (
        <>
          {/* S072 STI 去噪：去 STI 得分/阶段（无 §44 edge），留分析/候选数 */}
          {result && (
            <div className="mb-4 grid grid-cols-2 gap-3 rounded-lg bg-muted/20 p-4">
              <MetricCard label="分析总数" value={result.total_analyzed ?? "—"} />
              <MetricCard label="候选数" value={result.candidates?.length ?? 0} valueClassName="text-primary" />
            </div>
          )}

          {errMsg ? (
            <EmptyState
              icon={<Info className="h-8 w-8 text-destructive/40" />}
              title="加载失败"
              description={errMsg}
            />
          ) : (
            <GlassCard>
              <SectionHeader title="候选标的" />
              <div className="overflow-x-auto">
                <table className="w-full text-sm">
                  <thead>
                    <tr className="border-b border-border/50 bg-muted/20 text-left text-xs text-muted-foreground">
                      <th className="w-8 px-2 py-2.5">#</th>
                      <th className="whitespace-nowrap px-3 py-2.5 font-medium">代码</th>
                      <th className="whitespace-nowrap px-3 py-2.5 font-medium">名称</th>
                      <th className="w-16 whitespace-nowrap px-3 py-2.5 text-center font-medium">竞价得分</th>
                      <th className="w-16 whitespace-nowrap px-3 py-2.5 text-center font-medium">基因得分</th>
                      <th className="w-14 whitespace-nowrap px-3 py-2.5 text-center font-medium">连板数</th>
                      <th className="w-16 whitespace-nowrap px-3 py-2.5 text-center font-medium">封板率</th>
                      <th className="w-20 whitespace-nowrap px-3 py-2.5 text-center font-medium">封单额(万)</th>
                      <th className="w-20 whitespace-nowrap px-3 py-2.5 text-center font-medium">流通盘(亿)</th>
                      <th className="w-20 whitespace-nowrap px-3 py-2.5 text-center font-medium">封单/流通</th>
                      <th className="whitespace-nowrap px-3 py-2.5 font-medium">战法标签</th>
                      <th className="w-16 whitespace-nowrap px-3 py-2.5 text-center font-medium">信号强度</th>
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-border/20">
                    {result?.candidates?.length === 0 ? (
                      <tr>
                        <td colSpan={12} className="py-8">
                          <EmptyState
                            icon={<Info className="h-8 w-8 text-muted-foreground/40" />}
                            title="今日无符合条件的竞价选股标的"
                          />
                        </td>
                      </tr>
                    ) : (
                        result?.candidates?.map((c, i) => (
                          <tr key={c.code} className="transition-colors hover:bg-muted/20">
                            <td className="whitespace-nowrap px-2 py-2.5 font-mono text-xs text-muted-foreground/50">{i + 1}</td>
                            <td className="whitespace-nowrap px-3 py-2.5 font-mono text-xs text-muted-foreground/60">{c.code}</td>
                            <td className="px-3 py-2.5 font-medium">{c.name}</td>
                            <td className="px-3 py-2.5 text-center">
                               <span className={`inline-block rounded-md px-2 py-0.5 font-mono text-sm font-bold ${
                                 c.score >= 75 ? "bg-primary/10 text-primary"
                                 : c.score >= 60 ? "bg-info/10 text-info"
                                 : "bg-muted/20 text-muted-foreground"
                               }`}>
                                {c.score}
                              </span>
                            </td>
                            <td className="whitespace-nowrap px-3 py-2.5 text-center font-mono text-xs">
                              {c.gene_score}
                            </td>
                            <td className="whitespace-nowrap px-3 py-2.5 text-center font-mono text-xs">
                              {c.zt_count_30d}
                            </td>
                            <td className="whitespace-nowrap px-3 py-2.5 text-center font-mono text-xs">
                              {c.seal_rate != null ? `${(c.seal_rate * 100).toFixed(1)}%` : "—"}
                            </td>
                            <td className="whitespace-nowrap px-3 py-2.5 text-center font-mono text-xs">
                              {c.seal_amount > 0 ? `${(c.seal_amount / 10000).toFixed(1)}` : "—"}
                            </td>
                            <td className="whitespace-nowrap px-3 py-2.5 text-center font-mono text-xs">
                              {c.float_shares > 0 ? `${(c.float_shares / 100000000).toFixed(2)}` : "—"}
                            </td>
                            <td className="whitespace-nowrap px-3 py-2.5 text-center font-mono text-xs">
                              {c.seal_to_float_ratio > 0 ? `${(c.seal_to_float_ratio * 100).toFixed(2)}%` : "—"}
                            </td>
                            <td className="px-3 py-2.5">
                              <div className="flex flex-wrap gap-1">
                                {c.strategy_tags?.length > 0
                                  ? c.strategy_tags.map((tag, j) => (
                                      <span key={j} className="rounded bg-primary/10 px-1.5 py-0.5 text-[10px] text-primary">{tag}</span>
                                    ))
                                  : "—"}
                              </div>
                            </td>
                            <td className="whitespace-nowrap px-3 py-2.5 text-center font-mono text-xs">
                              {c.signal_strength != null ? `${(c.signal_strength * 100).toFixed(1)}%` : "—"}
                            </td>
                          </tr>
                        ))
                      )}
                  </tbody>
                </table>
              </div>
            </GlassCard>
          )}

          {result?.updated && (
            <p className="mt-2 text-[11px] text-muted-foreground/50">更新时间: {result.updated}</p>
          )}
        </>
      )}
    </div>
  );
}
