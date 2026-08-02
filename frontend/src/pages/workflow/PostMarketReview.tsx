import { useState, useMemo, useCallback } from "react";
import { BarChart3 } from "lucide-react";
import { WorkflowStage } from "./components/WorkflowStage";
import { usePostMarketReview } from "@/lib/query";
import { GlassCard } from "@/components/ui/GlassCard";
import { Badge } from "@/components/ui/Badge";
import type { SettlementTrade } from "@/lib/api";

const formatPrice = (v: number | string | undefined): string => {
  if (v == null || v === "") return "-";
  const n = typeof v === "string" ? parseFloat(v) : v;
  if (isNaN(n)) return String(v);
  return n.toLocaleString("zh-CN", { minimumFractionDigits: 2, maximumFractionDigits: 2 });
};

const formatPct = (v: number | undefined, sign = true): string => {
  if (v == null) return "-";
  const s = sign && v >= 0 ? "+" : "";
  return `${s}${v.toFixed(2)}%`;
};

type SortKey = keyof SettlementTrade;

export default function PostMarketReview() {
  const [sortKey, setSortKey] = useState<SortKey>("return_pct");
  const [sortDir, setSortDir] = useState<"asc" | "desc">("desc");
  const { data, isLoading, refetch } = usePostMarketReview();
  
  const handleRefresh = useCallback(() => refetch(), [refetch]);
  
  const settlements: SettlementTrade[] = data?.settlements ?? [];
  const sortedSettlements = useMemo(() => {
    return [...settlements].sort((a, b) => {
      const aVal = (a as any)[sortKey] ?? 0;
      const bVal = (b as any)[sortKey] ?? 0;
      return sortDir === "asc" ? aVal - bVal : bVal - aVal;
    });
  }, [settlements, sortKey, sortDir]);

  if (!data) return null;
  
  const toggleSort = (key: SortKey) => {
    if (sortKey === key) {
      setSortDir(d => d === "asc" ? "desc" : "asc");
    } else {
      setSortKey(key);
      setSortDir("desc");
    }
  };

  return (
    <WorkflowStage 
      title="盘后复盘" 
      subtitle="Post-Market Review"
      loading={isLoading}
      onRefresh={handleRefresh}
    >
      {/* 概览 */}
      <div className="mb-6 grid gap-3 sm:grid-cols-4">
        <GlassCard className="p-4">
          <p className="text-xs text-muted-foreground">总交易数</p>
          <p className="mt-1 text-2xl font-bold">{data.total_trades ?? 0}</p>
        </GlassCard>
        <GlassCard className="p-4">
          <p className="text-xs text-muted-foreground">胜率</p>
          <p className={`mt-1 text-2xl font-bold ${((data.win_rate ?? 0) >= 0.5) ? "text-danger" : "text-success"}`}>
            {formatPct(data.win_rate)}
          </p>
        </GlassCard>
        <GlassCard className="p-4">
          <p className="text-xs text-muted-foreground">总收益</p>
          <p className={`mt-1 text-2xl font-bold ${((data.total_return ?? 0) >= 0) ? "text-danger" : "text-success"}`}>
            {formatPct(data.total_return)}
          </p>
        </GlassCard>
        <GlassCard className="p-4">
          <p className="text-xs text-muted-foreground">最大回撤</p>
          <p className="mt-1 text-2xl font-bold text-warning">{formatPct(data.max_drawdown)}</p>
        </GlassCard>
      </div>

      {/* 成交明细 */}
      <div>
        <h3 className="mb-3 flex items-center gap-2 text-sm font-semibold">
          <BarChart3 className="h-4 w-4" /> 成交明细
        </h3>
        <div className="overflow-x-auto">
          <table className="w-full text-sm">
            <thead>
              <tr className="border-b border-border/50 text-left text-xs text-muted-foreground">
                <th className="px-2 py-2 cursor-pointer" onClick={() => toggleSort("code")}>代码</th>
                <th className="px-2 py-2">名称</th>
                <th className="px-2 py-2 cursor-pointer" onClick={() => toggleSort("buy_price")}>买入价</th>
                <th className="px-2 py-2 cursor-pointer" onClick={() => toggleSort("sell_price")}>卖出价</th>
                <th className="px-2 py-2 cursor-pointer" onClick={() => toggleSort("hold_days")}>持仓天数</th>
                <th className="px-2 py-2 cursor-pointer" onClick={() => toggleSort("return_pct")}>收益率</th>
                <th className="px-2 py-2">结果</th>
              </tr>
            </thead>
            <tbody>
              {sortedSettlements.map((s, i) => (
                <tr key={i} className="border-b border-border/30">
                  <td className="px-2 py-2 font-mono text-xs">{s.code}</td>
                  <td className="px-2 py-2 font-medium">{s.name}</td>
                  <td className="px-2 py-2 font-mono">{formatPrice(s.buy_price)}</td>
                  <td className="px-2 py-2 font-mono">{formatPrice(s.sell_price)}</td>
                  <td className="px-2 py-2 font-mono">{s.hold_days ?? "-"}</td>
                  <td className={`px-2 py-2 font-mono font-bold ${((s.return_pct ?? 0) >= 0) ? "text-danger" : "text-success"}`}>
                    {formatPct(s.return_pct)}
                  </td>
                  <td className="px-2 py-2">
                    <Badge variant={s.won ? "success" : "danger"}>
                      {s.won ? "盈利" : "亏损"}
                    </Badge>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>

      <p className="mt-4 text-xs text-muted-foreground/50">
        {data.updated && `更新于 ${data.updated}`}
      </p>
    </WorkflowStage>
  );
}
