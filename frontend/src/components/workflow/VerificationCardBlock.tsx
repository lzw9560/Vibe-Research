// S060：明日验证条件对账卡组件
// 简报市场情绪区下方挂「昨日验证对账」块；三问页展示当晚新生成的条件预览。
import { useEffect, useState } from "react";
import { CheckCircle2, XCircle, MinusCircle, HelpCircle, Clock } from "lucide-react";
import { api, type VerificationCondition, type VerificationStatus } from "@/lib/api";
import { cn } from "@/lib/utils";

const STATUS_META: Record<VerificationStatus, { icon: typeof CheckCircle2; color: string; label: string }> = {
  met_up: { icon: CheckCircle2, color: "text-emerald-600", label: "上行验证" },
  met_down: { icon: XCircle, color: "text-red-600", label: "下行验证" },
  within: { icon: MinusCircle, color: "text-muted-foreground", label: "区间内" },
  data_missing: { icon: HelpCircle, color: "text-amber-600", label: "数据缺失" },
  pending: { icon: Clock, color: "text-blue-500", label: "待验证" },
};

const METRIC_LABELS: Record<string, string> = {
  zt_count: "涨停家数",
  break_rate: "炸板率",
  max_boards: "最高连板",
  seal_rate: "封板率",
  promotion_rate: "晋级率",
  yzt_count: "昨涨停今日表现",
};

function _fmt(v: number | null | undefined, metric: string): string {
  if (v == null) return "—";
  if (metric.includes("rate")) return `${(v * 100).toFixed(1)}%`;
  if (metric === "max_boards") return `${v} 板`;
  return `${v}`;
}

function ConditionRow({ c }: { c: VerificationCondition }) {
  const meta = STATUS_META[c.status] ?? STATUS_META.pending;
  const Icon = meta.icon;
  return (
    <div className="flex items-center justify-between border-b border-border/30 py-1.5 text-sm last:border-0">
      <div className="flex-1">
        <span className="text-muted-foreground">{METRIC_LABELS[c.metric] ?? c.metric}</span>
        <span className="ml-2 text-xs text-muted-foreground/60">{c.note ?? ""}</span>
      </div>
      <div className="flex items-center gap-3 font-mono text-xs">
        <span className="text-muted-foreground">
          基准 {_fmt(c.baseline, c.metric)}
          {c.threshold_up != null && <span className="ml-1">↑{_fmt(c.threshold_up, c.metric)}</span>}
          {c.threshold_down != null && <span className="ml-1">↓{_fmt(c.threshold_down, c.metric)}</span>}
        </span>
        <span className={cn("font-medium", c.actual != null && c.actual > (c.baseline ?? 0) ? "text-emerald-600" : c.actual != null && c.actual < (c.baseline ?? 0) ? "text-red-600" : "text-muted-foreground")}>
          实际 {_fmt(c.actual, c.metric)}
        </span>
        <span className={cn("inline-flex items-center gap-0.5", meta.color)}>
          <Icon className="h-3.5 w-3.5" />
          {meta.label}
        </span>
      </div>
    </div>
  );
}

export function VerificationCardBlock({ date }: { date?: string }) {
  const [conditions, setConditions] = useState<VerificationCondition[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let mounted = true;
    api.verificationCard(date)
      .then((res) => { if (mounted) setConditions(res.conditions); })
      .catch((e) => { if (mounted) setError(e instanceof Error ? e.message : "加载失败"); })
      .finally(() => { if (mounted) setLoading(false); });
    return () => { mounted = false; };
  }, [date]);

  if (loading) return <div className="text-sm text-muted-foreground/60">加载验证对账卡…</div>;
  if (error) return <div className="text-sm text-red-600">{error}</div>;
  if (conditions.length === 0) return null;

  const pending = conditions.filter((c) => c.status === "pending").length;
  const verified = conditions.length - pending;

  return (
    <div className="rounded-lg border border-border/50 p-3" data-testid="verification-card">
      <div className="mb-2 flex items-center justify-between">
        <span className="text-sm font-medium">
          {pending > 0 ? "明日验证条件预览" : "昨日验证对账"}
        </span>
        <span className="text-xs text-muted-foreground/60">
          {verified > 0 ? `${verified}/${conditions.length} 已对账` : `${conditions.length} 条待验证`}
        </span>
      </div>
      <div>
        {conditions.map((c) => (
          <ConditionRow key={`${c.metric}-${c.id}`} c={c} />
        ))}
      </div>
      <div className="mt-2 text-[11px] text-muted-foreground/50">
        条件句式为「若…则确认…」，无涨跌预测；历史统计特征，市场有风险
      </div>
    </div>
  );
}
