import { useState, useEffect } from "react";
import { Loader2, TrendingUp, TrendingDown, ArrowUpDown } from "lucide-react";
import { GlassCard } from "@/components/ui/GlassCard";
import { PageHeader } from "@/components/ui/PageHeader";
import { api, ApiError, type IndustryData } from "@/lib/api";
import { cn } from "@/lib/utils";

const pctColor = (p: number) => (p > 0 ? "text-danger" : p < 0 ? "text-success" : "text-muted-foreground");
const fmt = (v: number) => v.toLocaleString("zh-CN", { maximumFractionDigits: 2 });

export function Industry() {
  const [data, setData] = useState<IndustryData | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [topN, setTopN] = useState(30);
  const [sortBy, setSortBy] = useState<"change_pct" | "up_count" | "down_count">("change_pct");

  const loadData = () => {
    setLoading(true);
    api.industry(topN)
      .then(setData)
      .catch((e) => setError(e instanceof ApiError ? e.message : "行业数据加载失败"))
      .finally(() => setLoading(false));
  };

  useEffect(() => { loadData(); }, [topN]);

  const allRows = data
    ? [...data.top, ...data.bottom].sort((a, b) => {
        if (sortBy === "change_pct") return b.change_pct - a.change_pct;
        if (sortBy === "up_count") return b.up_count - a.up_count;
        return b.down_count - a.down_count;
      })
    : [];

  return (
    <div>
      <PageHeader
        title="行业排行"
        subtitle="全市场行业涨跌幅、上涨/下跌家数一览，按板块维度快速定位强弱"
        actions={
          <div className="flex items-center gap-2">
            <select
              value={topN}
              onChange={(e) => setTopN(Number(e.target.value))}
              className="rounded-lg border border-border bg-black/20 px-3 py-1.5 text-xs outline-none focus:border-primary/50"
            >
              {[15, 20, 30, 50].map((n) => (
                <option key={n} value={n}>TOP {n}</option>
              ))}
            </select>
            <button onClick={loadData} className="text-muted-foreground hover:text-primary" title="刷新">
              <ArrowUpDown className="h-3.5 w-3.5" />
            </button>
          </div>
        }
      />

      <GlassCard className="mb-6">
        {loading ? (
          <div className="flex items-center justify-center py-12">
            <Loader2 className="h-6 w-6 animate-spin text-primary" />
            <span className="ml-3 text-sm text-muted-foreground">加载行业中…</span>
          </div>
        ) : error ? (
          <div className="py-8 text-center text-sm text-destructive">{error}</div>
        ) : allRows.length === 0 ? (
          <div className="py-8 text-center text-sm text-muted-foreground/60">暂无行业数据</div>
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
              <div className="rounded-lg bg-muted/20 p-3 text-center">
                <p className="text-[11px] text-muted-foreground">行业总数</p>
                <p className="mt-0.5 font-mono text-xl font-bold text-foreground">                  {data?.total ?? 0}</p>
              </div>
              <div className="rounded-lg bg-muted/20 p-3 text-center">
                <p className="text-[11px] text-muted-foreground">领涨行业</p>
                <p className="mt-0.5 font-mono text-xl font-bold text-danger">
                  {allRows.filter((r) => r.change_pct > 0).length}
                </p>
              </div>
              <div className="rounded-lg bg-muted/20 p-3 text-center">
                <p className="text-[11px] text-muted-foreground">领跌行业</p>
                <p className="mt-0.5 font-mono text-xl font-bold text-success">
                  {allRows.filter((r) => r.change_pct < 0).length}
                </p>
              </div>
              <div className="rounded-lg bg-muted/20 p-3 text-center">
                <p className="text-[11px] text-muted-foreground">最强行业</p>
                <p className="mt-0.5 truncate font-mono text-sm font-bold text-primary">
                  {allRows[0]?.name ?? "—"}
                </p>
              </div>
            </div>

            {/* 行业表格 */}
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
