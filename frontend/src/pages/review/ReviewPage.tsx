// 多维度 IA: /review — 复盘（验证+策略 2 tab）
// ③ 验证线: 因子→§44 verdict VerdictSpine+信号验证态徽章+调因子 feedback
// ④ 策略线: 战法→回测→前向→调战法 SDD+R3 loop，StrategyPage embed
// 旧 behavior/reports/notes 折入验证 tab 子区（保兼容不丢内容）
import { useSearchParams } from "react-router-dom";
import { Suspense, lazy, type ReactNode, useState } from "react";
import { FlaskConical, Layers, Activity, FileText, NotebookPen, ChevronDown } from "lucide-react";
import { PageHeader } from "@/components/ui/PageHeader";
import { FocusDayStrip } from "@/components/ui/FocusDayStrip";
import { TabBar } from "@/components/ui/TabBar";
import { GlassCard } from "@/components/ui/GlassCard";
import { NextStepBar } from "@/components/ui/NextStepBar";
import { DimensionValidationBadge } from "@/components/ui/DimensionValidationBadge";
import { LineLoopCard } from "@/components/lines/LineLoopCard";
import { RiskBadgeRow } from "@/components/lines/RiskBadge";
import { LINES } from "@/components/lines/lines";
import { useEvaluationSummary } from "@/lib/query/strategy";
import type { DimensionValidation } from "@/lib/candidates";
import BehaviorLoop from "@/pages/BehaviorLoop";
import { MyReports } from "@/pages/MyReports";
import { Notes } from "@/pages/Notes";
import { cn } from "@/lib/utils";

const StrategyPage = lazy(() =>
  import("@/pages/strategy/StrategyPage").then(m => ({ default: m.default }))
);

const Fallback = (
  <div className="flex h-[40vh] items-center justify-center text-sm text-muted-foreground">加载中…</div>
);

type ReviewTabKey = "validation" | "strategy";

const REVIEW_TABS: { key: ReviewTabKey; label: string; icon: ReactNode }[] = [
  { key: "validation", label: "验证", icon: <FlaskConical className="h-3.5 w-3.5" /> },
  { key: "strategy", label: "策略", icon: <Layers className="h-3.5 w-3.5" /> },
];

// Track E A7: dimension_id → edge_type 映射（镜像 M4 backend _DIMENSION_EDGE_TYPE）。
// 后端 evaluation_summary 未序列化 edge_type，前端按 dimension_id 派生（不臆造，
// 映射源 backend/routers/verifier.py M4 commit 0dfb525）。
const DIMENSION_EDGE_TYPE: Record<string, string> = {
  path_lift: "path",
  low_volatility: "population",
  ofi_accumulated: "event",
  seal_sincerity: "event",
  bid_ask_pressure: "event",
  overnight_gap: "overnight_gap",
};

const EDGE_TYPE_OPTIONS: { value: string; label: string }[] = [
  { value: "all", label: "全部 edge-type" },
  { value: "selection", label: "selection（短线选股）" },
  { value: "event", label: "event（中线事件）" },
  { value: "population", label: "population（群体异常）" },
  { value: "overnight_gap", label: "overnight_gap（隔夜缺口）" },
  { value: "path", label: "path（整体路径）" },
];

// §44 verdict 全量表（验证线核心）
function VerdictSpine() {
  const { data: evaluation, isLoading } = useEvaluationSummary();
  const [edgeFilter, setEdgeFilter] = useState("all");

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

  // 派生 edge_type + 按 filter 筛选（不可变：filter 产新数组）
  const withEdge = evaluation.dimensions.map((dim: DimensionValidation) => ({
    ...dim,
    edge_type: dim.edge_type ?? DIMENSION_EDGE_TYPE[dim.dimension_id] ?? "selection",
  }));
  const filtered = edgeFilter === "all"
    ? withEdge
    : withEdge.filter((d) => d.edge_type === edgeFilter);

  return (
    <GlassCard tier="primary">
      <div className="mb-3">
        <h2 className="text-sm font-semibold">§44 Verdict（全量）</h2>
        <p className="text-xs text-muted-foreground">
          {evaluation.honest_label ?? "—"} · 冻结 commit: {evaluation.frozen_commit?.slice(0, 8) ?? "—"}
        </p>
      </div>

      {/* A7: edge-type 筛选器 */}
      <div className="mb-3 flex items-center gap-2">
        <label htmlFor="edge-filter" className="text-xs text-muted-foreground">edge-type 筛：</label>
        <select
          id="edge-filter"
          value={edgeFilter}
          onChange={(e) => setEdgeFilter(e.target.value)}
          className="rounded border border-border/50 bg-background px-2 py-1 text-xs"
        >
          {EDGE_TYPE_OPTIONS.map((o) => (
            <option key={o.value} value={o.value}>{o.label}</option>
          ))}
        </select>
        <span className="text-[10px] text-muted-foreground/70">
          {filtered.length}/{withEdge.length} 维度
        </span>
      </div>

      <div className="overflow-x-auto">
        <table className="w-full text-sm">
          <thead>
            <tr className="border-b border-border/50 text-left text-xs text-muted-foreground">
              <th className="py-2 pr-4">维度</th>
              <th className="py-2 pr-4">edge-type</th>
              <th className="py-2 pr-4">lift</th>
              <th className="py-2 pr-4">n</th>
              <th className="py-2 pr-4">状态</th>
              <th className="py-2 pr-4">权重</th>
              <th className="py-2 pr-4">徽章</th>
              <th className="py-2">说明</th>
            </tr>
          </thead>
          <tbody>
            {filtered.map((dim) => (
              <tr key={dim.dimension_id} className="border-b border-border/30">
                <td className="py-2 pr-4 font-medium">{dim.label}</td>
                <td className="py-2 pr-4">
                  <span className="rounded bg-primary/10 px-1.5 py-0.5 text-[10px] text-primary">
                    {dim.edge_type}
                  </span>
                </td>
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
                <td className="py-2 pr-4">
                  <DimensionValidationBadge validation={dim} compact />
                </td>
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

// 信号验证态说明（验证线辅）
function SignalValidationLegend() {
  return (
    <GlassCard tier="sub" className="mt-4">
      <h3 className="mb-2 text-xs font-semibold">信号验证态说明</h3>
      <div className="grid grid-cols-1 gap-2 sm:grid-cols-3">
        <div className="flex items-start gap-2">
          <span className="mt-0.5 h-2 w-2 shrink-0 rounded-full bg-emerald-500" />
          <div>
            <div className="text-xs font-medium text-emerald-500">validated · 可执行</div>
            <div className="text-[10px] text-muted-foreground">§44 过 lift≥2x，可记交易</div>
          </div>
        </div>
        <div className="flex items-start gap-2">
          <span className="mt-0.5 h-2 w-2 shrink-0 rounded-full bg-amber-500" />
          <div>
            <div className="text-xs font-medium text-amber-500">待验证 · 参考用</div>
            <div className="text-[10px] text-muted-foreground">lift&lt;2x 或 n 不足，记日志待复验</div>
          </div>
        </div>
        <div className="flex items-start gap-2">
          <span className="mt-0.5 h-2 w-2 shrink-0 rounded-full bg-red-500" />
          <div>
            <div className="text-xs font-medium text-red-500">已证否 · 不交易</div>
            <div className="text-[10px] text-muted-foreground">§44 证否选股力，仅参考</div>
          </div>
        </div>
      </div>
    </GlassCard>
  );
}

// 折叠子区（behavior/reports/notes 保兼容）
function CollapsibleSection({ title, icon, children }: { title: string; icon: ReactNode; children: ReactNode }) {
  const [open, setOpen] = useState(false);
  return (
    <div className="mt-4">
      <button
        onClick={() => setOpen(!open)}
        className="flex w-full items-center gap-2 text-xs text-muted-foreground transition-colors hover:text-foreground"
      >
        {icon}
        <span className="flex-1 text-left font-medium">{title}</span>
        <ChevronDown className={cn("h-3.5 w-3.5 transition-transform", open && "rotate-180")} />
      </button>
      {open && <div className="mt-2">{children}</div>}
    </div>
  );
}

export function ReviewPage() {
  const [searchParams, setSearchParams] = useSearchParams();
  const tabParam = searchParams.get("tab");
  // 兼容旧 tab 值: backtest/behavior/reports/notes → validation
  const active: ReviewTabKey =
    tabParam === "strategy" ? "strategy" : "validation";

  const switchTab = (k: string): void => {
    const next = new URLSearchParams(searchParams);
    next.set("tab", k);
    setSearchParams(next, { replace: true });
  };

  const subtitle =
    active === "validation"
      ? "因子→§44 verdict→信号验证态→交易/记日志→调因子（§44v2 闭环）"
      : "战法→回测§44→模拟→前向R3→复盘→调战法（SDD+R3 闭环）";

  // 线步骤环
  const validationLine = LINES[2];
  const strategyLine = LINES[3];

  return (
    <div>
      <PageHeader
        title="复盘"
        subtitle={subtitle}
        actions={<FocusDayStrip />}
      />

      {/* 风控横切徽章 */}
      <div className="mb-4">
        <RiskBadgeRow />
      </div>

      <div className="mb-6">
        <TabBar tabs={REVIEW_TABS} activeKey={active} onChange={switchTab} />
      </div>

      {active === "validation" && (
        <div>
          {/* 验证线闭环卡 */}
          <div className="mb-4">
            <LineLoopCard
              title="验证线闭环"
              subtitle="因子→信号验证态→§44 verdict→交易/记日志→调因子→(loop)"
              steps={validationLine.steps}
              currentStep={2}
              icon={<FlaskConical className="h-3.5 w-3.5 text-muted-foreground" />}
            />
          </div>

          {/* §44 verdict 全量表 */}
          <VerdictSpine />

          {/* 信号验证态说明 */}
          <SignalValidationLegend />

          {/* 调因子 feedback */}
          <GlassCard tier="sub" className="mt-4">
            <p className="text-xs text-muted-foreground">
              verdict → 调因子 → 重跑 = 闭环。validated 信号可记可执行交易（→ /ledger?tab=journal），
              证否/provisional → 调漏斗参数回盘面重跑。
              <br />
              §44v2 应用规约：回溯模块主场（R3 30/60天复验），短窗 days_robust&lt;60 挂 provisional cap ×0.5。
            </p>
          </GlassCard>

          {/* 旧 behavior/reports/notes 折叠保兼容 */}
          <CollapsibleSection title="行为模式（影子对照·三桶算账）" icon={<Activity className="h-3.5 w-3.5" />}>
            <BehaviorLoop />
          </CollapsibleSection>
          <CollapsibleSection title="研报管理" icon={<FileText className="h-3.5 w-3.5" />}>
            <MyReports />
          </CollapsibleSection>
          <CollapsibleSection title="研究记录" icon={<NotebookPen className="h-3.5 w-3.5" />}>
            <Notes />
          </CollapsibleSection>
        </div>
      )}

      {active === "strategy" && (
        <div>
          {/* 策略线闭环卡 */}
          <div className="mb-4">
            <LineLoopCard
              title="策略线闭环"
              subtitle="战法→回测§44→模拟→前向R3→复盘→调战法→(loop)"
              steps={strategyLine.steps}
              currentStep={1}
              icon={<Layers className="h-3.5 w-3.5 text-muted-foreground" />}
            />
          </div>

          {/* 策略+前向测试嵌入 */}
          <Suspense fallback={Fallback}>
            <StrategyPage />
          </Suspense>

          {/* SDD+R3 说明 */}
          <GlassCard tier="sub" className="mt-4">
            <p className="text-xs text-muted-foreground">
              SDD（规范驱动开发）+ R3（30/60天前向复验）= 策略闭环。
              战法定义 → spec → 回测§44 → 模拟盘 → 前向R3 enforce → 复盘 → 调战法。
              <br />
              days_robust &lt; 60 → provisional cap ×0.5（不全权重），60 天后 R3 复验升降级。
            </p>
          </GlassCard>
        </div>
      )}

      {/* CTA 脊 */}
      <NextStepBar pageCtx="review" />
    </div>
  );
}
