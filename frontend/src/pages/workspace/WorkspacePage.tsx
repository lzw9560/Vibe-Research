// Track B IA: /workspace — 盘面工作区（选股+盯盘合并，带盘前|盘中相位 toggle）
// 决策1: 相位 toggle 非 2 入口。同 workspace 切相位不切页。
// 盘前相位 = 漏斗+候选(ValueFunnel) / 盘中相位 = 自选 live+预警(IntradayCockpit)
// SplitLayout 由子组件各自管理（IntradayCockpit 已有 SplitLayout）
// 信号诚实化: 子组件内信号卡复用 DimensionValidationBadge
import { Suspense, lazy } from "react";
import { useSearchParams, Link } from "react-router-dom";
import { cn } from "@/lib/utils";
import { PageHeader } from "@/components/ui/PageHeader";
import { NextStepBar } from "@/components/ui/NextStepBar";
import { GlassCard } from "@/components/ui/GlassCard";

// 懒加载子组件（各自带 SplitLayout/Header，保兼容）
const IntradayCockpit = lazy(() =>
  import("@/pages/intraday/IntradayCockpit").then(m => ({ default: m.IntradayCockpit }))
);
const ValueFunnel = lazy(() =>
  import("@/pages/ValueFunnel").then(m => ({ default: m.ValueFunnel }))
);

const Fallback = (
  <div className="flex h-[40vh] items-center justify-center text-sm text-muted-foreground">加载中…</div>
);

const PHASES = [
  { key: "premarket" as const, label: "盘前", desc: "漏斗→候选→加自选" },
  { key: "intraday" as const, label: "盘中", desc: "自选 live+预警" },
];

export function WorkspacePage() {
  const [searchParams, setSearchParams] = useSearchParams();
  const phaseParam = searchParams.get("phase");
  const phase: "premarket" | "intraday" =
    phaseParam === "intraday" ? "intraday" : "premarket";

  const switchPhase = (p: "premarket" | "intraday") => {
    const next = new URLSearchParams(searchParams);
    next.set("phase", p);
    setSearchParams(next, { replace: true });
  };

  return (
    <div>
      <PageHeader
        title="盘面"
        subtitle={phase === "premarket" ? "盘前 · 漏斗→候选→加自选" : "盘中 · 自选 live+预警"}
      />

      {/* 相位 toggle */}
      <div className="mb-4 inline-flex items-center gap-1 rounded-lg bg-muted/40 p-1">
        {PHASES.map(p => (
          <button
            key={p.key}
            onClick={() => switchPhase(p.key)}
            className={cn(
              "rounded-md px-4 py-1.5 text-sm font-medium transition-colors",
              phase === p.key
                ? "bg-primary text-primary-foreground"
                : "text-muted-foreground hover:text-foreground",
            )}
          >
            {p.label}
            <span className="ml-1.5 text-xs opacity-70">{p.desc}</span>
          </button>
        ))}
      </div>

      {/* 相位内容：盘前=漏斗+候选 / 盘中=cockpit */}
      {phase === "premarket" ? (
        <div>
          {/* /value-funnel 作主漏斗（已恢复有候选），/screener 降辅 */}
          <div className="mb-3 flex items-center gap-2">
            <Link
              to="/screener"
              className="text-xs text-muted-foreground transition-colors hover:text-primary"
            >
              因子筛选器（辅）→
            </Link>
            <Link
              to="/bidding"
              className="text-xs text-muted-foreground transition-colors hover:text-primary"
            >
              竞价监控 →
            </Link>
            <Link
              to="/limitup/premarket"
              className="text-xs text-muted-foreground transition-colors hover:text-primary"
            >
              盘前选股 →
            </Link>
          </div>
          <Suspense fallback={Fallback}>
            <ValueFunnel />
          </Suspense>
        </div>
      ) : (
        <div>
          {/* 盘中 honest banner: 60% 未测，信号须标验证态 */}
          <GlassCard tier="sub" className="mb-3">
            <p className="text-xs text-muted-foreground">
              盘中数据 60% 未测，信号标注验证态（lift·待验证 / 已证否·参考 / validated·可执行）。
              未验证信号 CTA → 记日志待 §44 复验，仅 validated → 记交易。
            </p>
          </GlassCard>
          <Suspense fallback={Fallback}>
            <IntradayCockpit />
          </Suspense>
        </div>
      )}

      {/* CTA 脊 */}
      <NextStepBar pageCtx="workspace" />
    </div>
  );
}
