// S072 §44 诚实标注层 + S151 评价层动态维度表（替换硬编码 bullet）。
// 前向 verdict（lift/winrate vs random）+ 评价层 dimensions[]（5 维度降权梯度）。
// candidates 漏斗页与盘前简报(briefing)共用。prop 优先，hook 兜底。
import { useForwardTestSummary, useEvaluationSummary } from "@/lib/query/strategy";
import { DimensionValidationBadge } from "@/components/ui/DimensionValidationBadge";
import type { EvaluationSummary } from "@/lib/candidates";

export function HonestyBanner({ evaluationSummary }: { evaluationSummary?: EvaluationSummary | null }) {
  const { data: ft, isLoading } = useForwardTestSummary();
  const { data: hookSummary } = useEvaluationSummary();
  const evalSummary = evaluationSummary ?? hookSummary ?? null;
  // win_rate 单位防御：>1 当百分比，否则 ×100
  const pct = (v?: number) => (v == null ? "—" : `${(v > 1 ? v : v * 100).toFixed(1)}%`);
  const lift = ft?.lift;
  return (
    <div className="rounded-lg border border-amber-500/40 bg-amber-500/10 p-3 text-sm">
      <div className="font-semibold text-amber-200">⚠ §44 诚实标注：选股层无 validated 维度，edge 待盘中验证</div>
      {evalSummary ? (
        <ul className="mt-1 space-y-0.5 text-xs text-amber-100/80">
          {[...evalSummary.dimensions].sort((a, b) => a.weight_multiplier - b.weight_multiplier).map((d) => (
            <li key={d.dimension_id} className="flex items-center gap-1">
              <DimensionValidationBadge validation={d} />
              <span>lift {d.lift != null ? d.lift.toFixed(3) : "—"}（n={d.n}）· {d.note}</span>
            </li>
          ))}
          <li className="text-[10px] text-amber-100/50">frozen_commit={evalSummary.frozen_commit}</li>
        </ul>
      ) : (
        <div className="mt-1 text-xs text-amber-100/60">选股层无 validated 维度，edge 待盘中验证（评价层数据未取得）</div>
      )}
      {ft && (
        <div className="mt-2 text-xs text-amber-100/90">
          前向测试（{ft.total_days}天 / {ft.settled_count}已结算）：策略 {pct(ft.win_rate)} vs 随机{" "}
          {pct(ft.random_baseline_win_rate)}，lift {lift != null ? lift.toFixed(3) : "—"}
          （{ft.passed ? "通过" : "未通过"}{ft.is_exploratory ? "，探索性" : ""}）
          {ft.note ? `；${ft.note}` : ""}
        </div>
      )}
      {isLoading && <div className="mt-2 text-xs text-amber-100/60">前向 verdict 加载中…</div>}
    </div>
  );
}
