// S221 gap2: 周度复盘面板——/review weekly tab。
// actual P&L 趋势（manual-trades）+ 4 周对比（按周聚合 mean）+ cap-down 提案（前端推算，mean<0）。
// 前提问题：weekly_review.json 无 GET 端点，cap-down 改由前端从 manual-trades 推算
// （镜像 backend executors/signals.py:478-487 逻辑），诚实标注"前端推算"。
import { Loader2, TrendingDown, TrendingUp, AlertTriangle } from "lucide-react";
import { GlassCard } from "@/components/ui/GlassCard";
import { Disclaimer } from "@/components/ui/Disclaimer";
import { HonestEmptyState } from "@/components/intraday/HonestEmptyState";
import { useSignalsManualTrades, useSignalsStatus, useWeeklyReview } from "@/lib/query/signals";
import type { ManualTradeResponse } from "@/lib/api/types";

/** ISO date → 周一日期 key（YYYY-MM-DD），用于按周分组。 */
function weekKey(iso: string): string {
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return "unknown";
  const day = d.getDay() || 7; // Sunday=0 → 7
  const monday = new Date(d);
  monday.setDate(d.getDate() - day + 1);
  return monday.toISOString().slice(0, 10);
}

/** closed trades → {weeks: [{week, mean, n, wins}], meanAll, nAll, hasLeak} */
function aggregateWeekly(trades: ManualTradeResponse[]) {
  const closed = trades.filter(
    (t) => t.actual_pnl?.status === "closed" && t.actual_pnl?.pnl_pct != null,
  );
  if (closed.length === 0) {
    return { weeks: [], meanAll: null, nAll: 0, hasLeak: false };
  }
  const byWeek = new Map<string, { pnls: number[]; wins: number }>();
  for (const t of closed) {
    const k = weekKey(t.recorded_at);
    const entry = byWeek.get(k) ?? { pnls: [], wins: 0 };
    entry.pnls.push(t.actual_pnl.pnl_pct as number);
    if ((t.actual_pnl.pnl_pct as number) > 0) entry.wins += 1;
    byWeek.set(k, entry);
  }
  const weeks = [...byWeek.entries()]
    .map(([week, { pnls, wins }]) => ({
      week,
      mean: pnls.reduce((a, b) => a + b, 0) / pnls.length,
      n: pnls.length,
      wins,
      wr: wins / pnls.length,
    }))
    .sort((a, b) => a.week.localeCompare(b.week))
    .slice(-4); // 最近 4 周

  const allPnls = closed.map((t) => t.actual_pnl.pnl_pct as number);
  const meanAll = allPnls.reduce((a, b) => a + b, 0) / allPnls.length;
  const hasLeak = closed.some((t) => t.delivery_leak);

  return { weeks, meanAll, nAll: closed.length, hasLeak };
}

export function WeeklyReviewPanel() {
  const { data: tradesResp, isLoading: tradesLoading } = useSignalsManualTrades(200);
  const { data: status } = useSignalsStatus();
  const { data: weeklyReview } = useWeeklyReview();

  if (tradesLoading) {
    return (
      <GlassCard tier="primary">
        <div className="flex items-center gap-2 text-sm text-muted-foreground">
          <Loader2 className="h-4 w-4 animate-spin" /> 加载周度复盘…
        </div>
      </GlassCard>
    );
  }

  const trades = tradesResp?.trades ?? [];
  const agg = aggregateWeekly(trades);
  const regime = status?.regime?.current ?? "unknown";

  // cap-down：优先读后端 weekly_review.json 真值（cap_down_proposal），
  // 无端点数据（status=no_reports）降级前端推算（镜像 backend 逻辑）。
  const backendCapDown = weeklyReview?.status === "ok" ? weeklyReview?.cap_down_proposal : null;
  const fallbackCapDown =
    agg.meanAll != null && agg.meanAll < 0
      ? {
          from: status?.arms?.consecutive_relay?.weight_override ?? 1.0,
          to: 0.5,
          reason: `实际 P&L mean=${agg.meanAll.toFixed(2)}% < 0（n=${agg.nAll} 笔），触发 cap-down`,
        }
      : null;
  const capDown = backendCapDown ?? fallbackCapDown;
  const capDownSource = backendCapDown ? "后端真值" : "前端推算";

  // 无数据诚实空态
  if (agg.nAll === 0) {
    return (
      <GlassCard tier="primary">
        <h2 className="mb-2 text-sm font-semibold">周度复盘</h2>
        <HonestEmptyState
          message="暂无已录实际交易"
          hint="记录成交后显示实际 P&L 趋势 + cap-down 提案 + 4 周对比"
        />
        <Disclaimer compact />
      </GlassCard>
    );
  }

  const closedTrades = trades.filter(
    (t) => t.actual_pnl?.status === "closed" && t.actual_pnl?.pnl_pct != null,
  );

  return (
    <GlassCard tier="primary">
      <div className="mb-3">
        <h2 className="text-sm font-semibold">周度复盘</h2>
        <p className="text-xs text-muted-foreground">
          regime: {regime} · 已录 {trades.length} 笔（{agg.nAll} 笔已平仓）
        </p>
      </div>

      {/* cap-down 提案（{capDownSource}） */}
      {capDown ? (
        <div className="mb-3 rounded border border-red-200 bg-red-50 px-3 py-2 text-xs text-red-700">
          <div className="flex items-center gap-1.5 font-semibold">
            <AlertTriangle className="h-3.5 w-3.5" /> cap-down 提案
          </div>
          <p className="mt-1">{capDown.reason}</p>
          <p className="mt-0.5">
            建议 ×{capDown.from} → ×{capDown.to}
          </p>
          <p className="mt-0.5 text-xs text-red-600/70">
            来源：{capDownSource}
          </p>
        </div>
      ) : (
        <div className="mb-3 rounded border border-emerald-200 bg-emerald-50 px-3 py-2 text-xs text-emerald-700">
          <div className="flex items-center gap-1.5 font-semibold">
            <TrendingUp className="h-3.5 w-3.5" /> 实际 P&L mean={agg.meanAll?.toFixed(2)}% ≥ 0
          </div>
          <p className="mt-0.5 text-emerald-600/70">无 cap-down 触发（{capDownSource}）</p>
        </div>
      )}

      {/* delivery leak 告警 */}
      {agg.hasLeak && (
        <div className="mb-3 rounded border border-amber-200 bg-amber-50 px-3 py-2 text-xs text-amber-700">
          <AlertTriangle className="mr-1 inline h-3 w-3" />
          检测到 delivery leak（actual 远低于 reference -50%，one-sided edge 未交付）
        </div>
      )}

      {/* 4 周对比 */}
      <div className="mb-3">
        <h3 className="mb-1.5 text-xs font-semibold">4 周对比</h3>
        <div className="grid grid-cols-2 gap-2 sm:grid-cols-4">
          {agg.weeks.map((w) => (
            <div key={w.week} className="rounded bg-muted/30 px-2 py-1.5 text-center">
              <p className="text-xs text-muted-foreground">{w.week.slice(5)}</p>
              <p className={`text-sm font-bold ${w.mean >= 0 ? "text-emerald-600" : "text-red-500"}`}>
                {w.mean >= 0 ? "+" : ""}
                {w.mean.toFixed(2)}%
              </p>
              <p className="text-xs text-muted-foreground">
                {w.n} 笔 · WR {(w.wr * 100).toFixed(0)}%
              </p>
            </div>
          ))}
        </div>
      </div>

      {/* 实际 P&L 趋势 */}
      <div className="mb-3">
        <h3 className="mb-1.5 flex items-center gap-1.5 text-xs font-semibold">
          <TrendingDown className="h-3.5 w-3.5 text-amber-600" /> 实际 P&L 趋势
        </h3>
        <div className="space-y-1.5">
          {closedTrades.slice(0, 20).map((t) => (
            <div
              key={t.trade_id}
              className="flex items-center justify-between rounded border border-border/40 px-3 py-1.5 text-xs"
            >
              <div className="flex items-center gap-2">
                <span className="font-mono font-semibold">{t.code}</span>
                <span className="text-muted-foreground">{t.recorded_at.slice(0, 10)}</span>
                {t.delivery_leak && (
                  <span className="rounded bg-red-50 px-1 py-0.5 text-xs text-red-600">leak</span>
                )}
              </div>
              <div className="flex items-center gap-2">
                <span className={t.actual_pnl.pnl_pct! >= 0 ? "text-emerald-600" : "text-red-500"}>
                  {t.actual_pnl.pnl_pct! >= 0 ? "+" : ""}
                  {t.actual_pnl.pnl_pct!.toFixed(2)}%
                </span>
                {t.reference_pnl?.pnl_pct != null && (
                  <span className="text-muted-foreground">
                    参考 {t.reference_pnl.pnl_pct.toFixed(2)}%
                  </span>
                )}
              </div>
            </div>
          ))}
        </div>
      </div>

      <Disclaimer compact />
    </GlassCard>
  );
}
