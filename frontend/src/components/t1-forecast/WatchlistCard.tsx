// components/t1-forecast/WatchlistCard.tsx — S232 T+1 涨停预测 watchlist 看板。
// 观察池非买入信号。5.28x lift 真但 EV -0.87% 负，二次确认累积 60 天验证中。
// T+1 hit 回填后展示命中/未命中标记 + 命中率汇总。
import { useT1Watchlist, type T1WatchlistStock } from "@/lib/query/t1_forecast";
import { GlassCard } from "@/components/ui/GlassCard";

function StockRow({ s }: { s: T1WatchlistStock }) {
  const ztMark = s.t1_zt === true ? "✅" : s.t1_zt === false ? "❌" : "⏳";
  return (
    <div className="flex items-center justify-between py-1.5 border-b border-border last:border-0">
      <span className="font-mono text-sm">
        {ztMark} {s.code}
      </span>
      <span className="text-xs text-muted-foreground">
        turn={s.turn}% · vr5={s.vr5} · pct={s.pctChg != null ? s.pctChg : "-"}% · close={s.close}
      </span>
    </div>
  );
}

export function WatchlistCard() {
  const { data, isLoading, error } = useT1Watchlist();

  if (isLoading) {
    return (
      <GlassCard className="p-4">
        <p className="text-sm text-muted-foreground">加载 T+1 watchlist...</p>
      </GlassCard>
    );
  }
  if (error) {
    return (
      <GlassCard className="p-4">
        <p className="text-sm text-red-500">加载失败：{String(error)}</p>
      </GlassCard>
    );
  }
  if (!data) return null;

  const isWeakSignal = data.edge_status === "weak-signal-EV-negative";

  // T+1 hit 回填统计
  const hitCount = data.stocks.filter((s) => s.t1_zt === true).length;
  const missCount = data.stocks.filter((s) => s.t1_zt === false).length;
  const backfilled = hitCount + missCount;
  const backfillRate = backfilled > 0 ? ((hitCount / backfilled) * 100).toFixed(2) : null;
  const insufficientSample = backfilled > 0 && backfilled < 30;

  return (
    <GlassCard className="p-4">
      <div className="flex items-start justify-between mb-3">
        <div>
          <h3 className="text-lg font-semibold">📅 {data.date} T+1 涨停预测 watchlist</h3>
          <p className="text-sm text-muted-foreground mt-1">
            信号 <span className="font-mono">{data.signal}</span> · lift{" "}
            <span className="font-semibold">{data.signal_lift}x</span>{" "}
            <span className="text-xs">({data.signal_lift_ci})</span> · 命中率{" "}
            {(data.hit_rate * 100).toFixed(2)}% vs base {(data.base_rate * 100).toFixed(3)}% · 数量{" "}
            {data.count} 只
          </p>
        </div>
        <span
          className={`px-2 py-1 rounded text-xs whitespace-nowrap ${
            isWeakSignal ? "bg-amber-100 text-amber-700" : "bg-green-100 text-green-700"
          }`}
        >
          {data.edge_status}
        </span>
      </div>

      <div className="bg-amber-50 border border-amber-200 rounded p-3 mb-3 text-xs text-amber-800 leading-relaxed">
        ⚠️ {data.honest_caveat}
      </div>

      {backfilled > 0 && (
        <div className="bg-blue-50 border border-blue-200 rounded p-2 mb-3 text-xs text-blue-700">
          📊 T+1 hit 回填：✅ {hitCount} 命中 / ❌ {missCount} 未命中 · 命中率 {backfillRate}%
          {insufficientSample && " · 样本不足（<30）累积 60 天验证"}
        </div>
      )}

      {data.stocks.length > 0 ? (
        <div className="space-y-0.5">
          <p className="text-xs font-medium text-muted-foreground mb-2">
            观察池（非买入信号，二次确认累积验证中）· ✅命中 ❌未命中 ⏳待回填
          </p>
          {data.stocks.slice(0, 20).map((s) => (
            <StockRow key={s.code} s={s} />
          ))}
          {data.stocks.length > 20 && (
            <p className="text-xs text-muted-foreground pt-2">... 共 {data.stocks.length} 只</p>
          )}
        </div>
      ) : (
        <p className="text-sm text-muted-foreground py-4">
          今日无信号股（市场未满足 {data.signal} 条件）
        </p>
      )}

      <p className="text-xs text-muted-foreground mt-3 pt-2 border-t border-border">
        ⚠️ 历史统计特征，市场有风险，真钱仓位与止损你最终决策。
      </p>
    </GlassCard>
  );
}
