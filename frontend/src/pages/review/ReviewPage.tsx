// Track B IA: /review — 复盘·回测（§44 verdict 为脊）
// 合并 review+strategy+topology+forward-test，§44 verdict 为脊
// L2 tabs: 行为对照 | 研报 | 记录 | 回测§44
// 旧 /strategy /backtest /verifier-records /topology 路由 redirect → /review 保兼容
import { useSearchParams } from "react-router-dom";
import { Suspense, lazy, type ReactNode } from "react";
import { Activity, FileText, NotebookPen, FlaskConical } from "lucide-react";
import { PageHeader } from "@/components/ui/PageHeader";
import { TabBar } from "@/components/ui/TabBar";
import { GlassCard } from "@/components/ui/GlassCard";
import { NextStepBar } from "@/components/ui/NextStepBar";
import { useEvaluationSummary } from "@/lib/query/strategy";
import type { DimensionValidation } from "@/lib/candidates";
import BehaviorLoop from "@/pages/BehaviorLoop";
import { MyReports } from "@/pages/MyReports";
import { Notes } from "@/pages/Notes";

const StrategyPage = lazy(() =>
  import("@/pages/strategy/StrategyPage").then(m => ({ default: m.default }))
);

const Fallback = (
  <div className="flex h-[40vh] items-center justify-center text-sm text-muted-foreground">加载中…</div>
);

type ReviewTabKey = "behavior" | "reports" | "notes" | "backtest";

const REVIEW_TABS: { key: ReviewTabKey; label: string; icon: ReactNode }[] = [
  { key: "behavior", label: "行为模式", icon: <Activity className="h-3.5 w-3.5" /> },
  { key: "reports", label: "研报管理", icon: <FileText className="h-3.5 w-3.5" /> },
  { key: "notes", label: "研究记录", icon: <NotebookPen className="h-3.5 w-3.5" /> },
  { key: "backtest", label: "回测§44", icon: <FlaskConical className="h-3.5 w-3.5" /> },
];

function isTabKey(v: string | null): v is ReviewTabKey {
  return v === "behavior" || v === "reports" || v === "notes" || v === "backtest";
}

// §44 verdict 紧凑表（Decision 4: 盘面紧凑徽章 + 复盘全量）
function VerdictSpine() {
  const { data: evaluation, isLoading } = useEvaluationSummary();

  if (isLoading) {
    return <p className="text-sm text-muted-foreground">加载 §44 verdict…</p>;
  }

  if (!evaluation || !evaluation.dimensions || evaluation.dimensions.length === 0) {
    return (
      <GlassCard className="p-6">
        <p className="text-sm text-muted-foreground">
          §44 评价层数据待积累。verdict 需 ≥60 天 forward_test 数据。
        </p>
      </GlassCard>
    );
  }

  return (
    <GlassCard tier="primary">
      <div className="mb-3">
        <h2 className="text-sm font-semibold">§44 Verdict（全量）</h2>
        <p className="text-xs text-muted-foreground">
          {evaluation.honest_label ?? "—"} · 冻结 commit: {evaluation.frozen_commit?.slice(0, 8) ?? "—"}
        </p>
      </div>
      <div className="overflow-x-auto">
        <table className="w-full text-sm">
          <thead>
            <tr className="border-b border-border/50 text-left text-xs text-muted-foreground">
              <th className="py-2 pr-4">维度</th>
              <th className="py-2 pr-4">lift</th>
              <th className="py-2 pr-4">n</th>
              <th className="py-2 pr-4">状态</th>
              <th className="py-2 pr-4">权重</th>
              <th className="py-2">说明</th>
            </tr>
          </thead>
          <tbody>
            {evaluation.dimensions.map((dim: DimensionValidation) => (
              <tr key={dim.dimension_id} className="border-b border-border/30">
                <td className="py-2 pr-4 font-medium">{dim.label}</td>
                <td className="py-2 pr-4 font-mono">
                  {dim.lift != null ? dim.lift.toFixed(3) : "—"}
                </td>
                <td className="py-2 pr-4 font-mono">{dim.n}</td>
                <td className="py-2 pr-4">
                  <span className={
                    dim.status.includes("validated") ? "text-emerald-500"
                    : dim.status.includes("证否") || dim.status.includes("劣") ? "text-red-500"
                    : "text-amber-500"
                  }>
                    {dim.status}
                  </span>
                </td>
                <td className="py-2 pr-4 font-mono">×{dim.weight_multiplier}</td>
                <td className="py-2 text-xs text-muted-foreground">{dim.note}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      {evaluation.pending_dims.length > 0 && (
        <p className="mt-3 text-xs text-amber-500">
          待验证维度: {evaluation.pending_dims.join(", ")}
        </p>
      )}
    </GlassCard>
  );
}

export function ReviewPage() {
  const [searchParams, setSearchParams] = useSearchParams();
  const tabParam = searchParams.get("tab");
  const active: ReviewTabKey = isTabKey(tabParam) ? tabParam : "behavior";

  const switchTab = (k: string): void => {
    const next = new URLSearchParams(searchParams);
    next.set("tab", k);
    setSearchParams(next, { replace: true });
  };

  const subtitle =
    active === "behavior"
      ? "影子对照·三桶算账·独立性基线——系统建议单 vs 感觉单 vs 漏掉候选"
      : active === "reports"
        ? "研报归档·按行业分类·只存本地不上传"
        : active === "notes"
          ? "AI 复盘/要点/问答沉淀本地·随时回看"
          : "§44 verdict 为脊·假设→回测→前向→verdict→调参闭环";

  return (
    <div>
      <PageHeader title="复盘" subtitle={subtitle} />

      <div className="mb-6">
        <TabBar tabs={REVIEW_TABS} activeKey={active} onChange={switchTab} />
      </div>

      {active === "behavior" && <BehaviorLoop />}
      {active === "reports" && <MyReports />}
      {active === "notes" && <Notes />}
      {active === "backtest" && (
        <div>
          {/* §44 verdict 全量表（Decision 4: 复盘全量） */}
          <VerdictSpine />

          {/* 策略+前向测试嵌入 */}
          <div className="mt-6">
            <Suspense fallback={Fallback}>
              <StrategyPage />
            </Suspense>
          </div>

          {/* CTA: 调参回盘面 */}
          <GlassCard tier="sub" className="mt-4">
            <p className="text-xs text-muted-foreground">
              verdict → 调参 → 重跑 = 闭环。validated 信号可记可执行交易（→ /ledger?tab=journal），
              证否/provisional → 调漏斗参数回盘面重跑。
            </p>
          </GlassCard>
        </div>
      )}

      {/* CTA 脊 */}
      <NextStepBar pageCtx="review" />
    </div>
  );
}
