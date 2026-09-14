// 多维度 IA: /ledger — 持仓+日志合并（策略线"模拟"步）
// PortfolioPage 删空壳 tab 保 holdings/risk + Journal 吞入
// 旧 /portfolio /journal /risk 路由 redirect → /ledger 保兼容
import { Suspense, lazy } from "react";
import { useSearchParams } from "react-router-dom";
import { Wallet, BookOpen } from "lucide-react";
import type { ReactNode } from "react";
import { PageHeader } from "@/components/ui/PageHeader";
import { TabBar } from "@/components/ui/TabBar";
import { GlassCard } from "@/components/ui/GlassCard";
import { NextStepBar } from "@/components/ui/NextStepBar";
import { LineLoopCard } from "@/components/lines/LineLoopCard";
import { RiskBadgeRow } from "@/components/lines/RiskBadge";
import { LINES } from "@/components/lines/lines";

// 懒加载子组件
const PortfolioPage = lazy(() =>
  import("@/pages/portfolio/PortfolioPage").then(m => ({ default: m.PortfolioPage }))
);
const Journal = lazy(() =>
  import("@/pages/Journal").then(m => ({ default: m.Journal }))
);

const Fallback = (
  <div className="flex h-[40vh] items-center justify-center text-sm text-muted-foreground">加载中…</div>
);

type LedgerTab = "holdings" | "journal";

const TABS: { key: LedgerTab; label: string; icon: ReactNode }[] = [
  { key: "holdings", label: "持仓", icon: <Wallet className="h-3.5 w-3.5" /> },
  { key: "journal", label: "日志", icon: <BookOpen className="h-3.5 w-3.5" /> },
];

function isTabKey(v: string | null): v is LedgerTab {
  return v === "holdings" || v === "journal";
}

export function LedgerPage() {
  const [searchParams, setSearchParams] = useSearchParams();
  const tabParam = searchParams.get("tab");
  const active: LedgerTab = isTabKey(tabParam) ? tabParam : "holdings";

  const switchTab = (k: string) => {
    const next = new URLSearchParams(searchParams);
    next.set("tab", k);
    setSearchParams(next, { replace: true });
  };

  const subtitle = active === "holdings"
    ? "持仓管理 + 风险仪表盘（PortfolioPage 2 tab）"
    : "交易日志 + §44 复验待验桩（信号触发记此）";

  // 策略线步骤环（/ledger = "模拟"步）
  const strategyLine = LINES[3];

  return (
    <div>
      <PageHeader title="持仓日志" subtitle={subtitle} />

      {/* 风控横切徽章 */}
      <div className="mb-4">
        <RiskBadgeRow />
      </div>

      {/* 策略线闭环卡（当前在"模拟"步） */}
      <div className="mb-4">
        <LineLoopCard
          title="策略线闭环"
          subtitle="战法→回测§44→模拟→前向R3→复盘→调战法→(loop)"
          steps={strategyLine.steps}
          currentStep={2}
          icon={<Wallet className="h-3.5 w-3.5 text-muted-foreground" />}
        />
      </div>

      <div className="mb-6">
        <TabBar tabs={TABS} activeKey={active} onChange={switchTab} />
      </div>

      {/* 嵌入子页面 */}
      {active === "holdings" && (
        <Suspense fallback={Fallback}>
          <PortfolioPage />
        </Suspense>
      )}
      {active === "journal" && (
        <Suspense fallback={Fallback}>
          <Journal />
        </Suspense>
      )}

      {/* 信号诚实化提示（日志 tab 下） */}
      {active === "journal" && (
        <GlassCard tier="sub" className="mt-4">
          <p className="text-xs text-muted-foreground">
            未验证信号记日志待 §44 复验（非"买入/卖出"）。
            breakout §44 lift 1.36x &lt; 2x 已证否选股力，盘中 60% 未测——须如实标验证态。
            仅 validated 信号 → 记交易。
          </p>
        </GlassCard>
      )}

      {/* CTA 脊 */}
      <NextStepBar pageCtx="ledger" />
    </div>
  );
}
