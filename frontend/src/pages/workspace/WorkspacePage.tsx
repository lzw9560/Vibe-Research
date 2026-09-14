// 多维度 IA: /workspace — 选股线（盘面工作区）
// 选股 fork: 漏斗/竞价/席位/板块→候选→加自选→盯盘→信号→调参 loop
// 相位 toggle 盘前选股/盘中盯盘（同页切相位不切页）
// 信号诚实化: 子组件内信号卡复用 DimensionValidationBadge
import { Suspense, lazy } from "react";
import { useSearchParams, Link } from "react-router-dom";
import { Filter, Gavel, Users, Layers, Eye, SlidersHorizontal } from "lucide-react";
import { cn } from "@/lib/utils";
import { PageHeader } from "@/components/ui/PageHeader";
import { NextStepBar } from "@/components/ui/NextStepBar";
import { GlassCard } from "@/components/ui/GlassCard";
import { LineLoopCard } from "@/components/lines/LineLoopCard";
import { RiskBadgeRow } from "@/components/lines/RiskBadge";
import { LINES } from "@/components/lines/lines";

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

// 选股 fork 入口（盘前相位下展示）
const SELECTION_FORKS = [
  { icon: <Filter className="h-3.5 w-3.5" />, label: "价值漏斗", desc: "中长线价值筛选", link: "/workspace?phase=premarket" },
  { icon: <Gavel className="h-3.5 w-3.5" />, label: "集合竞价", desc: "9:15-9:25 竞价监控", link: "/bidding" },
  { icon: <Users className="h-3.5 w-3.5" />, label: "龙虎席位", desc: "游资/机构席位追踪", link: "/market" },
  { icon: <Layers className="h-3.5 w-3.5" />, label: "板块轮动", desc: "行业/概念轮动", link: "/market" },
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

  // 选股线步骤环
  const selectionLine = LINES[1];
  const currentStep = phase === "premarket" ? 0 : 5;

  return (
    <div>
      <PageHeader
        title="盘面"
        subtitle={phase === "premarket" ? "盘前 · 漏斗→候选→加自选" : "盘中 · 自选 live+预警"}
      />

      {/* 风控横切徽章 */}
      <div className="mb-4">
        <RiskBadgeRow />
      </div>

      {/* 选股线闭环卡 */}
      <div className="mb-4">
        <LineLoopCard
          title="选股线闭环"
          subtitle="漏斗/竞价/席位/板块→候选→加自选→盯盘→信号→调参→(loop)"
          steps={selectionLine.steps}
          currentStep={currentStep}
          icon={<Filter className="h-3.5 w-3.5 text-muted-foreground" />}
        />
      </div>

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

      {/* 相位内容：盘前=选股 fork+漏斗+候选 / 盘中=cockpit */}
      {phase === "premarket" ? (
        <div>
          {/* 选股 fork 入口卡片 */}
          <div className="mb-4 grid grid-cols-2 gap-2 sm:grid-cols-4">
            {SELECTION_FORKS.map(fork => (
              <Link
                key={fork.label}
                to={fork.link}
                className="flex items-center gap-2 rounded-lg border border-border/40 bg-muted/10 px-3 py-2.5 transition-colors hover:border-primary/30 hover:bg-muted/20"
              >
                <span className="text-muted-foreground">{fork.icon}</span>
                <div className="min-w-0">
                  <div className="truncate text-xs font-medium">{fork.label}</div>
                  <div className="truncate text-[10px] text-muted-foreground">{fork.desc}</div>
                </div>
              </Link>
            ))}
          </div>

          {/* 辅链接 */}
          <div className="mb-3 flex items-center gap-2">
            <Link
              to="/screener"
              className="inline-flex items-center gap-1 text-xs text-muted-foreground transition-colors hover:text-primary"
            >
              <SlidersHorizontal className="h-3 w-3" /> 因子筛选器（辅）→
            </Link>
            <Link
              to="/limitup/premarket"
              className="inline-flex items-center gap-1 text-xs text-muted-foreground transition-colors hover:text-primary"
            >
              <Eye className="h-3 w-3" /> 盘前选股 →
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
