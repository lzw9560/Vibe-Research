import { useState } from "react";
import { TrendingUp, TrendingDown, ArrowUpDown } from "lucide-react";
import { GlassCard } from "@/components/ui/GlassCard";
import { PageHeader } from "@/components/ui/PageHeader";
import { SectionHeader } from "@/components/ui/SectionHeader";
import { MetricCard } from "@/components/ui/MetricCard";
import { EmptyState } from "@/components/ui/EmptyState";
import { Skeleton } from "@/components/ui/Skeleton";
import { AskAiButton } from "@/components/ui/AskAiButton";
import { useIndustry } from "@/lib/query";
import { cn, pctColor } from "@/lib/utils";

const fmt = (v: number) => v.toLocaleString("zh-CN", { maximumFractionDigits: 2 });

export function Industry() {
  // T9：原 useState(data/loading/error) + useEffect(loadData, [topN]) → useIndustry(topN)。
  // topN 仍为用户可控状态；queryKey 含 topN，变更自动重新查询，故移除手动 refetch effect。
  // 刷新按钮保留——通过 refetch 手动触发。
  // 注：useIndustry 经 Opts<Awaited<ReturnType<typeof api.industry>>> 参数化，data 已推断为
  // IndustryData | undefined（api.industry 返 IndustryData），无需窄→宽 cast。
  const [topN, setTopN] = useState(30);
  const { data, isLoading, error, refetch } = useIndustry(topN);
  const [sortBy, setSortBy] = useState<"change_pct" | "up_count" | "down_count">("change_pct");

  const allRows = data
    ? [...data.top, ...data.bottom].sort((a, b) => {
        if (sortBy === "change_pct") return b.change_pct - a.change_pct;
        if (sortBy === "up_count") return b.up_count - a.up_count;
        return b.down_count - a.down_count;
      })
    : [];

  const askAiContext = [
    `当前页面：行业排行`,
    `TOP${topN}行业（共${data?.total ?? 0}个）`,
    data && allRows.length > 0
      ? `涨跌幅榜：${allRows.slice(0, 10).map((r) => `${r.name}(${r.change_pct.toFixed(2)}%/涨${r.up_count}/跌${r.down_count})`).join("，")}`
      : `涨跌幅榜：未取得`,
    data && data.bottom.length > 0
      ? `跌幅榜：${data.bottom.slice(0, 5).map((r) => `${r.name}(${r.change_pct.toFixed(2)}%)`).join("，")}`
      : `跌幅榜：未取得`,
  ].join("\n");

  return (
    <div>
      <PageHeader
        title="行业排行"
        subtitle="全市场行业涨跌幅、上涨/下跌家数一览，按板块维度快速定位强弱"
        actions={
          <div className="flex items-center gap-2">
            <AskAiButton context={askAiContext} />
            <select
              value={topN}
              onChange={(e) => setTopN(Number(e.target.value))}
              className="rounded-lg border border-border bg-black/20 px-3 py-1.5 text-xs outline-none focus:border-primary/50"
            >
              {[15, 20, 30, 50].map((n) => (
                <option key={n} value={n}>TOP {n}</option>
              ))}
            </select>
            <button onClick={() => refetch()} className="text-muted-foreground hover:text-primary" title="刷新">
              <ArrowUpDown className="h-3.5 w-3.5" />
            </button>
          </div>
        }
      />

      <GlassCard className="mb-6">
        {isLoading ? (
          <div className="py-12">
            <Skeleton className="mx-auto h-6 w-32" />
          </div>
        ) : error ? (
          <EmptyState
            icon={<TrendingDown className="h-8 w-8 text-destructive/40" />}
            title="加载失败"
            description={error instanceof Error ? error.message : String(error)}
          />
        ) : allRows.length === 0 ? (
          <EmptyState
            icon={<TrendingDown className="h-8 w-8 text-muted-foreground/40" />}
            title="暂无行业数据"
          />
        ) : (
          <>
            {/* 排序控制 */}
            <div className="mb-3 flex items-center gap-2">
              <span className="text-xs text-muted-foreground">排序：</span>
              {[
                { key: "change_pct" as const, label: "涨跌幅", icon: TrendingUp },
                { key: "up_count" as const, label: "上涨家数", icon: TrendingUp },
                { key: "down_count" as const, label: "下跌家数", icon: TrendingDown },
              ].map((s) => (
                <button
                  key={s.key}
                  onClick={() => setSortBy(s.key)}
                  className={cn(
                    "inline-flex items-center gap-1 rounded-md px-3 py-1 text-xs font-medium transition-colors",
                    sortBy === s.key
                      ? "bg-primary/15 text-primary shadow-glow"
                      : "text-muted-foreground hover:bg-muted/40 hover:text-foreground",
                  )}
                >
                  <s.icon className="h-3 w-3" />
                  {s.label}
                </button>
              ))}
            </div>

            {/* 汇总卡片 */}
            <div className="mb-4 grid grid-cols-2 gap-3 sm:grid-cols-4">
              <MetricCard label="行业总数" value={data?.total ?? 0} />
              <MetricCard label="领涨行业" value={allRows.filter((r) => r.change_pct > 0).length} valueClassName="text-danger" />
              <MetricCard label="领跌行业" value={allRows.filter((r) => r.change_pct < 0).length} valueClassName="text-success" />
              <MetricCard label="最强行业" value={allRows[0]?.name ?? "—"} />
            </div>

            {/* 行业表格 */}
            <SectionHeader title="行业明细" />
            <div className="overflow-x-auto">
              <table className="w-full text-sm">
                <thead>
                  <tr className="border-b border-border/50 text-left text-xs text-muted-foreground">
                    <th className="whitespace-nowrap px-3 py-2.5">#</th>
                    <th className="whitespace-nowrap px-3 py-2.5">行业</th>
                    <th className="whitespace-nowrap px-3 py-2.5 text-right">涨跌幅</th>
                    <th className="whitespace-nowrap px-3 py-2.5 text-right">上涨家数</th>
                    <th className="whitespace-nowrap px-3 py-2.5 text-right">下跌家数</th>
                    <th className="whitespace-nowrap px-3 py-2.5 text-right">代码</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-border/20">
                  {allRows.map((row, i) => (
                    <tr key={row.code} className="transition-colors hover:bg-muted/15">
                      <td className="whitespace-nowrap px-3 py-2 font-mono text-xs text-muted-foreground/50">
                        {i + 1}
                      </td>
                      <td className="px-3 py-2 font-medium">{row.name}</td>
                      <td className={cn("whitespace-nowrap px-3 py-2 font-mono text-right", pctColor(row.change_pct))}>
                        {row.change_pct > 0 ? "+" : ""}{fmt(row.change_pct)}%
                      </td>
                      <td className="whitespace-nowrap px-3 py-2 font-mono text-right text-danger">{row.up_count}</td>
                      <td className="whitespace-nowrap px-3 py-2 font-mono text-right text-success">{row.down_count}</td>
                      <td className="whitespace-nowrap px-3 py-2 font-mono text-right text-xs text-muted-foreground/60">{row.code}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </>
        )}
      </GlassCard>
    </div>
  );
}
