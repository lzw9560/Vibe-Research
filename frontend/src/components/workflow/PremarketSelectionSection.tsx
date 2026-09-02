// S090 A：premarket_selection（S071 breakout 弱信号）前端展示——候选表 + 风控 + honest。
// §44 day-cluster lift=1.72x <2x 非 validated；honest_label 标弱信号，edge 主来自风控非对称。
// 前向测试期间不投真金（disclaimer）。
import { usePremarketSelection } from "@/lib/query/premarket";
import { GlassCard } from "@/components/ui/GlassCard";
import { Skeleton } from "@/components/ui/Skeleton";
import { ApiError } from "@/lib/api";
import { cn } from "@/lib/utils";
import { RefreshCw } from "lucide-react";

interface Props {
  /** T 目标日（YYYY-MM-DD）。由三 Tab 容器传入 dateTriplet.forward，不臆造今日。 */
  date?: string;
  topN?: number;
  minScore?: number;
}

export function PremarketSelectionSection({ date, topN = 20, minScore = 0.9 }: Props) {
  // S092 R15 时区 bug 修复：删除 new Date().toISOString() fallback，
  // date 由容器（dateTriplet.forward）注入；usePremarketSelection 内部 enabled: Boolean(date)
  // P7 修复：不在 hook 调用前早退（违反 rules-of-hooks）；传空串兜底，hook 内部 enabled: Boolean(date)
  const { data, isLoading, error, refetch } = usePremarketSelection(date ?? "", topN, minScore);

  if (!date) {
    return (
      <GlassCard className="p-4">
        <p className="text-sm text-muted-foreground">等待 dateTriplet 加载…</p>
      </GlassCard>
    );
  }

  if (isLoading) {
    return (
      <GlassCard className="p-4">
        <Skeleton className="h-32" />
      </GlassCard>
    );
  }
  if (error) {
    return (
      <GlassCard className="p-4">
        <p className="text-sm text-muted-foreground">
          盘前选股加载失败：{error instanceof ApiError ? error.message : "未知错误"}
        </p>
        <button onClick={() => refetch()} className="mt-1 text-xs text-primary hover:underline">
          重试
        </button>
      </GlassCard>
    );
  }
  if (!data || !data.candidates.length) {
    return (
      <GlassCard className="p-4">
        <p className="text-sm text-muted-foreground">
          盘前选股：无候选（breakout 分数 &lt; {minScore}）
        </p>
      </GlassCard>
    );
  }

  return (
    <GlassCard className="space-y-3 p-4">
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-2">
          <h3 className="font-semibold">盘前选股</h3>
          <span className="text-[10px] text-muted-foreground/50">S071 breakout 弱信号</span>
        </div>
        <div className="flex items-center gap-2">
          <span className="rounded bg-amber-500/10 px-1.5 py-0.5 text-[10px] text-amber-300/70">
            {data.honest_label}
          </span>
          <button
            onClick={() => refetch()}
            className="text-muted-foreground/50 hover:text-primary"
            title="刷新"
          >
            <RefreshCw className="h-3 w-3" />
          </button>
        </div>
      </div>

      {/* 风控参数 + 日历倍率 */}
      <div className="flex flex-wrap gap-x-3 gap-y-1 text-xs text-muted-foreground/70">
        <span>仓位 {data.risk_params.position_pct}%</span>
        <span>止损 {data.risk_params.stop_loss_pct}%</span>
        <span>止盈 {data.risk_params.take_profit_pct}%</span>
        <span>最多持 {data.risk_params.max_positions} 只</span>
        <span>持 {data.risk_params.max_hold_days} 日</span>
        {data.calendar_multiplier !== 1 && (
          <span className="text-amber-300/70">
            日历 ×{data.calendar_multiplier}（{data.calendar_reason}）
          </span>
        )}
      </div>
      {data.market_note && (
        <p className="text-xs text-muted-foreground/60">{data.market_note}</p>
      )}

      {/* 候选表 */}
      <div className="overflow-x-auto">
        <table className="w-full text-xs">
          <thead>
            <tr className="border-b border-border/40 text-muted-foreground/70">
              <th className="px-2 py-1 text-left">code</th>
              <th className="px-2 py-1 text-left">名称</th>
              <th className="px-2 py-1 text-right">breakout</th>
              <th className="px-2 py-1 text-right">T-1 close</th>
              <th className="px-2 py-1 text-right">入场参考</th>
              <th className="px-2 py-1 text-right">止损</th>
              <th className="px-2 py-1 text-right">止盈</th>
              <th className="px-2 py-1 text-right">仓位</th>
            </tr>
          </thead>
          <tbody>
            {data.candidates.map((c) => (
              <tr key={c.code} className="border-b border-border/20 hover:bg-muted/10">
                <td className="px-2 py-1 font-mono">{c.code}</td>
                <td className="px-2 py-1 truncate max-w-[6rem]">{c.name}</td>
                <td
                  className={cn(
                    "px-2 py-1 text-right font-mono",
                    c.breakout_binary === 1 ? "text-emerald-400" : "text-muted-foreground",
                  )}
                >
                  {c.breakout_score.toFixed(2)}
                  {c.breakout_binary === 1 ? " ●" : ""}
                </td>
                <td className="px-2 py-1 text-right font-mono">{c.t1_close.toFixed(2)}</td>
                <td className="px-2 py-1 text-right font-mono">{c.entry_ref.toFixed(2)}</td>
                <td className="px-2 py-1 text-right font-mono text-red-400/70">
                  {c.stop_loss.toFixed(2)}
                </td>
                <td className="px-2 py-1 text-right font-mono text-emerald-400/70">
                  {c.take_profit.toFixed(2)}
                </td>
                <td className="px-2 py-1 text-right font-mono">{c.position_pct}%</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      <p className="text-[10px] text-muted-foreground/50">
        §44 naive lift=1.36x &lt;2x 非 validated edge（4 方向特征里最弱），edge 主来自风控非对称。前向测试期间不投真金。
      </p>
    </GlassCard>
  );
}
