// S061 预测账本 Tab —— 系统判断追踪 + 命中率分桶。
// 合规 §0：客观算账呈现，挂「历史统计特征，市场有风险，研究参考」；不出现「跟单」暗示。
import { useState } from "react";
import { usePredictionLedger, type PredictionEntry, type PredictionStat } from "@/lib/query/prediction-ledger";
import { GlassCard } from "@/components/ui/GlassCard";
import { SectionHeader } from "@/components/ui/SectionHeader";
import { Badge } from "@/components/ui/Badge";
import { Skeleton } from "@/components/ui/Skeleton";

const SOURCE_LABELS: Record<string, string> = {
  funnel_candidate: "漏斗候选",
  strategy_hit: "战法命中",
  manual: "手动录入",
};

const STATUS_LABELS: Record<string, string> = {
  pending: "待验证",
  hit: "命中",
  miss: "未中",
  expired: "过期",
  voided: "缺数据",
};

const STATUS_VARIANTS: Record<string, "default" | "primary" | "success" | "danger" | "warning" | "info"> = {
  pending: "warning",
  hit: "success",
  miss: "danger",
  expired: "default",
  voided: "warning",
};

function StatCard({ stat }: { stat: PredictionStat }) {
  const label = SOURCE_LABELS[stat.source] ?? stat.source;
  const rate = stat.hit_rate == null ? "—" : `${(stat.hit_rate * 100).toFixed(1)}%`;
  const sufficient = stat.sample_sufficient;
  return (
    <div className="rounded-lg border border-border p-3">
      <div className="flex items-center justify-between">
        <span className="text-sm font-medium">{label}</span>
        <Badge variant={sufficient ? "info" : "warning"}>
          {sufficient ? `n=${stat.verified}` : "样本不足"}
        </Badge>
      </div>
      <div className="mt-2 flex items-baseline gap-2">
        <span className="text-2xl font-bold">{rate}</span>
        <span className="text-xs text-muted-foreground">命中率</span>
      </div>
      <div className="mt-1 text-xs text-muted-foreground">
        命中 {stat.hit} / 未中 {stat.miss}
        {stat.voided > 0 && ` / 缺数据 ${stat.voided}`}
        {` · 总 ${stat.total}`}
      </div>
    </div>
  );
}

function EntryRow({ entry }: { entry: PredictionEntry }) {
  const variant = STATUS_VARIANTS[entry.status] ?? "default";
  const sourceLabel = SOURCE_LABELS[entry.source] ?? entry.source;
  const statusLabel = STATUS_LABELS[entry.status] ?? entry.status;
  const actual = entry.actual_return == null
    ? "—"
    : `${entry.actual_return >= 0 ? "+" : ""}${(entry.actual_return * 100).toFixed(2)}%`;
  return (
    <tr className="border-b border-border/50 hover:bg-muted/30">
      <td className="px-2 py-2 text-xs text-muted-foreground">{entry.stated_at}</td>
      <td className="px-2 py-2 text-sm font-medium">{entry.code}</td>
      <td className="px-2 py-2 text-sm text-muted-foreground">{entry.name || "—"}</td>
      <td className="px-2 py-2 text-xs">{sourceLabel}</td>
      <td className="px-2 py-2 text-xs text-muted-foreground">{entry.signal_ref || "—"}</td>
      <td className="px-2 py-2 text-xs">{entry.horizon}d</td>
      <td className="px-2 py-2 text-xs text-muted-foreground">{entry.due_date}</td>
      <td className="px-2 py-2 text-sm font-mono">{actual}</td>
      <td className="px-2 py-2"><Badge variant={variant}>{statusLabel}</Badge></td>
    </tr>
  );
}

export function PredictionLedgerTab() {
  const [days, setDays] = useState(30);
  const { data, isLoading, error } = usePredictionLedger(days);

  return (
    <div className="space-y-4">
      <SectionHeader
        title="预测账本"
        subtitle={`系统判断追踪 · 近 ${days} 天 · 到期自动对账`}
      />

      {/* 命中率分桶 */}
      <div className="grid grid-cols-1 gap-3 sm:grid-cols-3">
        {isLoading ? (
          <Skeleton className="h-24 w-full sm:col-span-3" />
        ) : error ? (
          <GlassCard className="p-4 sm:col-span-3">
            <p className="text-sm text-muted-foreground">账本数据不可用</p>
          </GlassCard>
        ) : data?.stats?.length ? (
          data.stats.map((s) => <StatCard key={s.source} stat={s} />)
        ) : (
          <GlassCard className="p-4 sm:col-span-3">
            <p className="text-sm text-muted-foreground">暂无预测记录</p>
          </GlassCard>
        )}
      </div>

      {/* 列表 */}
      <GlassCard>
        <div className="mb-2 flex items-center justify-between px-1">
          <h3 className="text-sm font-medium">预测明细</h3>
          <select
            value={days}
            onChange={(e) => setDays(Number(e.target.value))}
            className="rounded border border-border bg-background px-2 py-1 text-xs"
          >
            <option value={7}>近 7 天</option>
            <option value={30}>近 30 天</option>
            <option value={90}>近 90 天</option>
            <option value={180}>近 180 天</option>
          </select>
        </div>
        <div className="overflow-x-auto">
          <table className="w-full text-left">
            <thead>
              <tr className="border-b border-border text-xs text-muted-foreground">
                <th className="px-2 py-2">发出日</th>
                <th className="px-2 py-2">代码</th>
                <th className="px-2 py-2">名称</th>
                <th className="px-2 py-2">来源</th>
                <th className="px-2 py-2">信号</th>
                <th className="px-2 py-2">周期</th>
                <th className="px-2 py-2">到期</th>
                <th className="px-2 py-2">实际</th>
                <th className="px-2 py-2">状态</th>
              </tr>
            </thead>
            <tbody>
              {isLoading ? (
                <tr><td colSpan={9} className="px-2 py-4"><Skeleton className="h-6 w-full" /></td></tr>
              ) : data?.data?.length ? (
                data.data.map((e) => <EntryRow key={e.id} entry={e} />)
              ) : (
                <tr><td colSpan={9} className="px-2 py-4 text-center text-sm text-muted-foreground">暂无数据</td></tr>
              )}
            </tbody>
          </table>
        </div>
      </GlassCard>

      <p className="px-1 text-xs text-muted-foreground">
        历史统计特征，市场有风险，研究参考。账本记系统判断（含未执行的），非交易胜率。
      </p>
    </div>
  );
}
