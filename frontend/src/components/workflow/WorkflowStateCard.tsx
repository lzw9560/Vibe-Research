// S033 T8/T10/R6/R7：抽屉状态卡——当前态徽标 + 流转历史 timeline（倒序）+ 流转按钮。
// 流转按钮只渲染 allowed_targets（后端 _ALLOWED_TRANSITIONS 校验后的合法目标）。
// watching/monitoring 直接 POST；holding/settled 先出表单（价格/战法可选填）。
import { useState } from "react";
import { GlassCard } from "@/components/ui/GlassCard";
import { Skeleton } from "@/components/ui/Skeleton";
import { cn, pctColor } from "@/lib/utils";
import { useTransitionWorkflowState, useWorkflowState, useWorkflowStateHistory } from "@/lib/query";
import type { TransitionRequest } from "@/lib/api";
import { STATUS_COLORS, STATUS_LABELS } from "./statusMeta";
import { TransitionForm } from "./TransitionForm";

interface Props {
  code: string;
  /** 交易日；不传时后端默认最近交易日（state.trade_date 回填后再流转） */
  date?: string;
}

export function WorkflowStateCard({ code, date }: Props) {
  const { data: state, isLoading } = useWorkflowState(code, date);
  const { data: history } = useWorkflowStateHistory(code, date);
  const transition = useTransitionWorkflowState();
  const [formTarget, setFormTarget] = useState<string | null>(null);

  if (isLoading) {
    return (
      <GlassCard className="p-4">
        <Skeleton variant="rectangular" className="h-16" />
      </GlassCard>
    );
  }
  // 无记录（该日未进工作流）：客观提示，不伪装状态
  if (!state) {
    return (
      <GlassCard className="p-4">
        <h3 className="mb-1 text-sm font-semibold">工作流状态</h3>
        <p className="text-sm text-muted-foreground">该日无工作流状态记录（盘前采集后自动落库）</p>
      </GlassCard>
    );
  }

  // date 未传（路由页直链）时用 state.trade_date 回填，保证 POST transition 有 date
  const effectiveDate = date ?? state.trade_date;
  const targets = state.allowed_targets ?? [];
  const timeline = [...(history ?? [])].reverse();

  const handleDirect = (target: string) => {
    transition.mutate({ code, date: effectiveDate, target } satisfies TransitionRequest);
  };
  const handleFormSubmit = (req: TransitionRequest) => {
    setFormTarget(null);
    transition.mutate(req);
  };

  return (
    <GlassCard className="p-4">
      <div className="flex items-center justify-between">
        <h3 className="text-sm font-semibold">工作流状态</h3>
        <div className="flex items-center gap-2">
          <span className={cn("h-3 w-3 rounded-full", STATUS_COLORS[state.status] ?? "bg-gray-200")} />
          <span className="font-medium">{STATUS_LABELS[state.status] ?? state.status}</span>
        </div>
      </div>

      {(state.entry_price != null || state.exit_price != null || state.strategy) && (
        <p className="mt-1 text-xs text-muted-foreground">
          {state.entry_price != null && <>买入价 {state.entry_price} </>}
          {state.exit_price != null && (
            <>
              卖出价 {state.exit_price}{" "}
              {state.settlement?.exit_price_source === "market" && <span>（市价自动）</span>}
              {state.settlement?.exit_price_source === "manual" && <span>（手动填写）</span>}
            </>
          )}
          {state.strategy && <>战法 {state.strategy}</>}
        </p>
      )}

      {/* S034：settled 行结算摘要（用户自录交易的客观记账，红涨绿跌 A 股口径） */}
      {state.settlement && (
        <p className="mt-1 text-xs">
          <span className={cn("font-medium", pctColor(state.settlement.return_pct))}>
            结算收益 {state.settlement.return_pct > 0 ? "+" : ""}{state.settlement.return_pct}%
          </span>
          <span className="text-muted-foreground">
            {" "}· {state.settlement.won ? "盈" : "亏"} · 持有 {state.settlement.hold_days} 天
          </span>
        </p>
      )}

      {timeline.length > 0 && (
        <div className="mt-3 space-y-1 border-t border-border/40 pt-2">
          {timeline.map((h, i) => (
            <div key={i} className="text-xs text-muted-foreground">
              {STATUS_LABELS[h.from_status] ?? h.from_status} → {STATUS_LABELS[h.to_status] ?? h.to_status}
              {h.reason && <span>（{h.reason}）</span>}
              <span className="ml-1 opacity-60">{h.created_at.replace("T", " ").slice(0, 16)}</span>
            </div>
          ))}
        </div>
      )}

      {targets.length > 0 && (
        <div className="mt-3 flex flex-wrap gap-2 border-t border-border/40 pt-2">
          {targets.map((target) =>
            target === "holding" || target === "settled" ? (
              <button
                key={target}
                type="button"
                onClick={() => setFormTarget(target)}
                className="rounded-lg bg-primary/15 px-3 py-1.5 text-xs font-medium text-primary hover:bg-primary/25"
              >
                → {STATUS_LABELS[target] ?? target}
              </button>
            ) : target === "filtered" && state.status === "candidate" ? (
              // S049 D7：candidate 态"取消选中"→filtered（danger variant）
              <button
                key={target}
                type="button"
                disabled={transition.isPending}
                onClick={() => handleDirect(target)}
                className="rounded-lg bg-warning/15 px-3 py-1.5 text-xs font-medium text-warning hover:bg-warning/25 disabled:opacity-50"
              >
                ✕ 取消选中
              </button>
            ) : target === "candidate" && state.status === "watching" ? (
              // S049 D7：watching 态"取消观察"→candidate（回候选池重审）
              <button
                key={target}
                type="button"
                disabled={transition.isPending}
                onClick={() => handleDirect(target)}
                className="rounded-lg bg-warning/15 px-3 py-1.5 text-xs font-medium text-warning hover:bg-warning/25 disabled:opacity-50"
              >
                取消观察
              </button>
            ) : (
              <button
                key={target}
                type="button"
                disabled={transition.isPending}
                onClick={() => handleDirect(target)}
                className="rounded-lg bg-muted/40 px-3 py-1.5 text-xs font-medium hover:bg-muted/60 disabled:opacity-50"
              >
                → {STATUS_LABELS[target] ?? target}
              </button>
            ),
          )}
        </div>
      )}

      {formTarget && (
        <TransitionForm
          code={code}
          date={effectiveDate}
          target={formTarget}
          submitting={transition.isPending}
          onSubmit={handleFormSubmit}
          onCancel={() => setFormTarget(null)}
        />
      )}
    </GlassCard>
  );
}
