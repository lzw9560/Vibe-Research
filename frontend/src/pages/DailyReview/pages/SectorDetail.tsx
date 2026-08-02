/** 板块资金详情页 - 下沉子页 */
import { useMarketOverview } from "@/lib/query";
import { GlassCard } from "@/components/ui/GlassCard";
import { pctColor, cn } from "@/lib/utils";
import { TrendingUp } from "lucide-react";

const fmt = (v: number) => v.toLocaleString("zh-CN", { maximumFractionDigits: 2 });

export function SectorDetail() {
  const { data: overview, isLoading } = useMarketOverview();
  const sectors = overview?.sectors || [];
  
  return (
    <div>
      <div className="mb-4 flex items-center gap-2">
        <TrendingUp className="h-5 w-5 text-muted-foreground" />
        <h2 className="text-lg font-semibold">板块资金详情</h2>
      </div>
      
      {isLoading && (
        <div className="py-8 text-center text-sm text-muted-foreground">加载中…</div>
      )}
      
      {sectors.length === 0 && !isLoading && (
        <div className="py-8 text-center text-sm text-muted-foreground">暂无板块数据</div>
      )}
      
      {sectors.length > 0 && (
        <div className="space-y-4">
          {/* 流入 Top */}
          <GlassCard className="p-4">
            <h3 className="mb-3 text-sm font-semibold text-danger">资金流入 Top 10</h3>
            <div className="space-y-2">
              {sectors.slice(0, 10).map((s) => (
                <div key={s.name} className="flex items-center gap-4 border-b border-border/30 pb-2 last:border-0">
                  <span className="w-6 text-xs text-muted-foreground/50">{sectors.indexOf(s) + 1}</span>
                  <span className="flex-1">{s.name}</span>
                  <span className={cn("font-mono text-sm", pctColor(s.pct))}>{s.pct > 0 ? "+" : ""}{s.pct}%</span>
                  <span className={cn("font-mono text-sm", pctColor(s.net))}>
                    {s.net > 0 ? "+" : ""}{fmt(s.net)} 亿
                  </span>
                </div>
              ))}
            </div>
          </GlassCard>
          
          {/* 流出 Top */}
          <GlassCard className="p-4">
            <h3 className="mb-3 text-sm font-semibold text-success">资金流出 Top 10</h3>
            <div className="space-y-2">
              {[...sectors].slice(-10).reverse().map((s) => (
                <div key={s.name} className="flex items-center gap-4 border-b border-border/30 pb-2 last:border-0">
                  <span className="w-6 text-xs text-muted-foreground/50">{sectors.length - sectors.slice(-10).indexOf(s)}</span>
                  <span className="flex-1">{s.name}</span>
                  <span className={cn("font-mono text-sm", pctColor(s.pct))}>{s.pct > 0 ? "+" : ""}{s.pct}%</span>
                  <span className={cn("font-mono text-sm", pctColor(s.net))}>
                    {s.net > 0 ? "+" : ""}{fmt(s.net)} 亿
                  </span>
                </div>
              ))}
            </div>
          </GlassCard>
          
          {/* 完整列表 */}
          <GlassCard className="p-4">
            <h3 className="mb-3 text-sm font-semibold">全部板块</h3>
            <div className="overflow-x-auto">
              <table className="w-full text-sm">
                <thead>
                  <tr className="border-b border-border/50 text-left text-xs text-muted-foreground">
                    <th className="px-2 py-2">行业</th>
                    <th className="px-2 py-2">涨跌%</th>
                    <th className="px-2 py-2">净流入</th>
                    <th className="px-2 py-2">流入</th>
                    <th className="px-2 py-2">流出</th>
                    <th className="px-2 py-2">家数</th>
                  </tr>
                </thead>
                <tbody>
                  {sectors.map((s) => (
                    <tr key={s.name} className="border-b border-border/30">
                      <td className="px-2 py-2 font-medium">{s.name}</td>
                      <td className={cn("px-2 py-2 font-mono", pctColor(s.pct))}>{s.pct > 0 ? "+" : ""}{s.pct}%</td>
                      <td className={cn("px-2 py-2 font-mono", pctColor(s.net))}>{s.net > 0 ? "+" : ""}{fmt(s.net)} 亿</td>
                      <td className="px-2 py-2 font-mono text-muted-foreground">{fmt(s.inflow)}</td>
                      <td className="px-2 py-2 font-mono text-muted-foreground">{fmt(s.outflow)}</td>
                      <td className="px-2 py-2 font-mono text-muted-foreground">{s.firms}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </GlassCard>
        </div>
      )}
    </div>
  );
}
