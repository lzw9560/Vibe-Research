// components/limitup-workflow/WorkflowCard.tsx — S233 打板工作流看板。
// 5 Stage 闭环 + 二次确认触发股 + exit 规则（-3% stop OOS 验证 +1.38% net）。
import { useLimitupWorkflow, type WorkflowStage } from "@/lib/query/limitup_workflow";
import { GlassCard } from "@/components/ui/GlassCard";

const STAGE_EMOJI: Record<string, string> = {
  done: "✅",
  pending: "⏳",
  manual: "👤",
  waiting_t1: "⏳",
};

function StageRow({ s }: { s: WorkflowStage }) {
  return (
    <div className="flex items-start gap-2 py-1.5 border-b border-border last:border-0">
      <span className="text-sm">{STAGE_EMOJI[s.status] ?? "⏳"}</span>
      <div className="flex-1">
        <div className="text-sm font-medium">
          Stage {s.stage} [{s.time}] {s.name}
        </div>
        <div className="text-xs text-muted-foreground">{s.desc}</div>
      </div>
    </div>
  );
}

export function WorkflowCard() {
  const { data, isLoading, error } = useLimitupWorkflow();

  if (isLoading) {
    return (
      <GlassCard className="p-4">
        <p className="text-sm text-muted-foreground">加载打板工作流...</p>
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

  return (
    <GlassCard className="p-4">
      <div className="mb-3">
        <h3 className="text-lg font-semibold">📋 打板工作流（{data.date}）</h3>
        {data.t1_date && (
          <p className="text-xs text-muted-foreground mt-1">T+1 = {data.t1_date}</p>
        )}
      </div>

      <div className="bg-amber-50 border border-amber-200 rounded p-2 mb-3 text-xs text-amber-800">
        ⚠️ {data.honest_caveat}
      </div>

      <div className="mb-3">
        <p className="text-xs font-medium text-muted-foreground mb-1">5 Stage 闭环：</p>
        {data.workflow_stages.map((s) => (
          <StageRow key={s.stage} s={s} />
        ))}
      </div>

      <div className="bg-blue-50 border border-blue-200 rounded p-2 mb-3 text-xs text-blue-700">
        <p className="font-medium">exit 规则（-3% stop OOS 验证）：</p>
        <p>entry: {data.exit_rules.entry}</p>
        <p>exit: {data.exit_rules.exit}</p>
        <p>OOS EV: {data.exit_rules.oos_ev}</p>
      </div>

      {data.confirmed_stocks.length > 0 ? (
        <div className="space-y-1">
          <p className="text-xs font-medium text-muted-foreground mb-1">
            二次确认触发（{data.confirmed_count} 只，gap {data.exit_rules.gap_range}）：
          </p>
          {data.confirmed_stocks.slice(0, 10).map((s) => (
            <div key={s.code} className="py-1 border-b border-border last:border-0 text-xs">
              <span className="font-mono">{s.code}</span>
              <span className="text-muted-foreground ml-2">
                gap={s.gap}% · entry={s.entry_price} · stop={s.stop_price}
              </span>
              <div className="text-muted-foreground">{s.exit_rule}</div>
            </div>
          ))}
        </div>
      ) : (
        <p className="text-xs text-muted-foreground py-2">
          {data.t1_date
            ? "今日无二次确认触发（T+1 gap 不在低开-5%~-2%）"
            : "T+1 未开盘，等 T+1 09:25 看竞价 gap"}
        </p>
      )}

      <div className="mt-3 pt-2 border-t border-border">
        <p className="text-xs font-medium text-muted-foreground mb-1">操作步骤：</p>
        {data.operation_steps.map((step, i) => (
          <p key={i} className="text-xs text-muted-foreground py-0.5">{step}</p>
        ))}
      </div>

      <p className="text-xs text-muted-foreground mt-3 pt-2 border-t border-border">
        ⚠️ 历史统计特征，市场有风险，真钱仓位与止损你最终决策。
      </p>
    </GlassCard>
  );
}
