// S173: 闭环 ledger 区——跨臂胜率闭环（模拟/纸面臂 signal→PnL 全链路）。
// 读 GET /api/journal/closed-loop + /api/journal/drawdown-status。
// 与 TradeJournalSection（手动真实成交）分离——闭环臂走 accounting 净口径。
// 不臆造：后端未就绪 → ApiError 横幅；空数据 → 如实呈现"暂无闭环记录"。
import { GlassCard } from "@/components/ui/GlassCard";
import { ApiError } from "@/lib/api";
import { useClosedLoop, useDrawdownStatus } from "@/lib/query";
import type { ArmAggregate, ClosedLoopRecord } from "@/lib/journal-contract";

function yuan(v: number | null | undefined): string {
  if (v == null || Number.isNaN(v)) return "—";
  return `${v >= 0 ? "+" : ""}${v.toFixed(0)}`;
}
function pct(v: number | null | undefined, digits = 2): string {
  if (v == null || Number.isNaN(v)) return "—";
  return `${v >= 0 ? "+" : ""}${v.toFixed(digits)}%`;
}

function statusBadge(status: string): string {
  const map: Record<string, string> = {
    enforced: "bg-green-500/15 text-green-600",
    underpowered: "bg-yellow-500/15 text-yellow-600",
    disabled: "bg-red-500/15 text-red-600",
    bear_exempt: "bg-blue-500/15 text-blue-600",
    floor_exempt_per_arm: "bg-blue-500/15 text-blue-600",
    empty: "bg-gray-500/15 text-gray-500",
  };
  return map[status] ?? "bg-gray-500/15 text-gray-500";
}

function ArmStatCard({ arm, stats }: { arm: string; stats: ArmAggregate }) {
  return (
    <GlassCard className="p-3">
      <div className="mb-2 flex items-center justify-between">
        <span className="text-sm font-medium">{arm}</span>
        <span className={`rounded px-1.5 py-0.5 text-[10px] font-medium ${statusBadge(stats.status)}`}>
          {stats.status}
        </span>
      </div>
      <div className="grid grid-cols-2 gap-x-3 gap-y-1 text-xs">
        <span className="text-muted-foreground">执行胜率</span>
        <span className="text-right font-mono">
          {stats.execution_winrate != null ? `${(stats.execution_winrate * 100).toFixed(1)}%` : "—"}
        </span>
        <span className="text-muted-foreground">Wilson CI</span>
        <span className="text-right font-mono text-[10px]">
          [{(stats.execution_winrate_ci[0] * 100).toFixed(1)}, {(stats.execution_winrate_ci[1] * 100).toFixed(1)}]
        </span>
        <span className="text-muted-foreground">覆盖率</span>
        <span className="text-right font-mono">
          {stats.n_picks + stats.n_unbuyable > 0
            ? `${(stats.signal_coverage_rate * 100).toFixed(1)}%`
            : "—"}
        </span>
        <span className="text-muted-foreground">总净 PnL</span>
        <span className="text-right font-mono">{yuan(stats.total_net_pnl)} CNY</span>
        <span className="text-muted-foreground">盈亏比</span>
        <span className="text-right font-mono">{stats.payoff_ratio != null ? stats.payoff_ratio.toFixed(2) : "—"}</span>
        <span className="text-muted-foreground">Sharpe</span>
        <span className="text-right font-mono">{stats.sharpe != null ? stats.sharpe.toFixed(3) : "—"}</span>
        <span className="text-muted-foreground">DSR</span>
        <span className="text-right font-mono">{stats.dsr != null ? stats.dsr.toFixed(3) : "—"}</span>
        <span className="text-muted-foreground">t-stat</span>
        <span className="text-right font-mono">{stats.t_stat != null ? stats.t_stat.toFixed(2) : "—"}</span>
        <span className="text-muted-foreground">p (BH adj)</span>
        <span className="text-right font-mono">
          {stats.p_adjusted_bh != null
            ? stats.p_adjusted_bh.toFixed(4)
            : stats.p_one_sided != null
            ? stats.p_one_sided.toFixed(4)
            : "—"}
        </span>
        <span className="text-muted-foreground">n_picks / n_days</span>
        <span className="text-right font-mono">{stats.n_picks} / {stats.n_days}</span>
      </div>
    </GlassCard>
  );
}

function RecordRow({ r }: { r: ClosedLoopRecord }) {
  const isDead = r.is_dead_arm === 1;
  return (
    <tr className={isDead ? "opacity-50" : ""}>
      <td className="px-2 py-1 text-xs">
        <span className={`rounded px-1 py-0.5 text-[10px] ${isDead ? "bg-red-500/15 text-red-500" : "bg-blue-500/15 text-blue-500"}`}>
          {r.arm}{isDead ? " (dead)" : ""}
        </span>
      </td>
      <td className="px-2 py-1 text-xs font-mono">{r.stock_code}</td>
      <td className="px-2 py-1 text-xs">{r.entry_date}</td>
      <td className="px-2 py-1 text-xs font-mono">{r.entry_price != null ? r.entry_price.toFixed(2) : "unbuyable"}</td>
      <td className="px-2 py-1 text-xs">{r.exit_date ?? "—"}</td>
      <td className="px-2 py-1 text-xs">{r.exit_reason ?? "—"}</td>
      <td className="px-2 py-1 text-xs font-mono">{r.gross_return != null ? pct(r.gross_return) : "—"}</td>
      <td className="px-2 py-1 text-xs font-mono text-muted-foreground">{r.cost_pct.toFixed(2)}%</td>
      <td className="px-2 py-1 text-xs font-mono">{yuan(r.net_pnl)}</td>
      <td className="px-2 py-1 text-xs">
        {r.is_realized === 0
          ? <span className="text-yellow-500">持仓 {yuan(r.unrealized_pnl)}</span>
          : <span className="text-green-500">已平</span>}
      </td>
    </tr>
  );
}

export function JournalLedger() {
  const closedLoop = useClosedLoop();
  const drawdown = useDrawdownStatus();

  if (closedLoop.error) {
    const err = closedLoop.error as Error;
    return (
      <div className="p-4 text-sm text-red-500">
        闭环 ledger 后端未就绪：{err instanceof ApiError ? err.message : String(err)}
      </div>
    );
  }
  if (drawdown.error) {
    // drawdown 可降级——不影响主 ledger
    // eslint-disable-next-line no-console
    console.warn("[JournalLedger] drawdown-status error, degrading");
  }

  const records = closedLoop.data?.records ?? [];
  const aggregate = closedLoop.data?.aggregate ?? {};
  const ddStatus = drawdown.data;

  if (closedLoop.isLoading) {
    return <div className="p-4 text-sm text-muted-foreground">加载闭环 ledger…</div>;
  }

  if (records.length === 0) {
    return (
      <div className="space-y-3 p-4">
        <GlassCard className="p-6 text-center">
          <p className="text-sm text-muted-foreground">
            暂无闭环交易记录。运行 <code className="rounded bg-muted px-1">journal_recorder.run_daily()</code> 后此处显示跨臂胜率闭环。
          </p>
          <p className="mt-1 text-[10px] text-muted-foreground">
            S173 闭环账本 · 模拟/纸面臂 signal→PnL 全链路 · accounting 净口径
          </p>
        </GlassCard>
      </div>
    );
  }

  return (
    <div className="space-y-3 p-4">
      {/* 跨臂聚合统计 */}
      <div>
        <h3 className="mb-2 text-sm font-semibold">跨臂聚合统计</h3>
        <div className="grid grid-cols-1 gap-2 md:grid-cols-2 lg:grid-cols-3">
          {Object.entries(aggregate).map(([arm, stats]) => (
            <ArmStatCard key={arm} arm={arm} stats={stats} />
          ))}
          {Object.keys(aggregate).length === 0 && (
            <p className="text-xs text-muted-foreground">无存活臂数据（dead_arm 不参与聚合）</p>
          )}
        </div>
      </div>

      {/* drawdown 熔断状态 */}
      {ddStatus && (
        <div>
          <h3 className="mb-2 text-sm font-semibold">drawdown 熔断</h3>
          <div className="flex flex-wrap gap-2">
            {ddStatus.portfolio && (
              <GlassCard className="px-3 py-2">
                <span className="text-[10px] text-muted-foreground">portfolio</span>
                <div className="text-xs font-mono">
                  equity {ddStatus.portfolio.equity.toFixed(0)} · DD {ddStatus.portfolio.drawdown_pct.toFixed(2)}%
                </div>
                <span className={`rounded px-1 py-0.5 text-[10px] ${statusBadge(ddStatus.portfolio.status)}`}>
                  {ddStatus.portfolio.status} ×{ddStatus.portfolio.size_multiplier}
                </span>
                {ddStatus.portfolio.is_bear_market && (
                  <span className="ml-1 text-[10px] text-blue-500">熊市</span>
                )}
              </GlassCard>
            )}
            {Object.entries(ddStatus.per_arm).map(([arm, s]) => (
              <GlassCard key={arm} className="px-3 py-2">
                <span className="text-[10px] text-muted-foreground">{arm}</span>
                <div className="text-xs font-mono">
                  DD {s.drawdown_pct.toFixed(2)}% · ×{s.size_multiplier}
                </div>
                <span className={`rounded px-1 py-0.5 text-[10px] ${statusBadge(s.status)}`}>{s.status}</span>
              </GlassCard>
            ))}
          </div>
        </div>
      )}

      {/* 闭环记录表 */}
      <div>
        <h3 className="mb-2 text-sm font-semibold">闭环交易记录 ({records.length})</h3>
        <div className="overflow-x-auto">
          <table className="w-full border-collapse">
            <thead>
              <tr className="border-b text-left text-[10px] text-muted-foreground">
                <th className="px-2 py-1">臂</th>
                <th className="px-2 py-1">代码</th>
                <th className="px-2 py-1">入场日</th>
                <th className="px-2 py-1">入场价</th>
                <th className="px-2 py-1">出场日</th>
                <th className="px-2 py-1">原因</th>
                <th className="px-2 py-1">毛收益</th>
                <th className="px-2 py-1">成本</th>
                <th className="px-2 py-1">净 PnL</th>
                <th className="px-2 py-1">状态</th>
              </tr>
            </thead>
            <tbody>
              {records.map((r) => (
                <RecordRow key={r.signal_id} r={r} />
              ))}
            </tbody>
          </table>
        </div>
      </div>
    </div>
  );
}
