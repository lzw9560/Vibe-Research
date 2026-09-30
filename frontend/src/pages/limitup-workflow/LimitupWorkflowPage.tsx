// pages/limitup-workflow/LimitupWorkflowPage.tsx — S233 打板工作流看板页。
// 5 Stage 闭环：watchlist → 二次确认 → open 买 → -3% stop/close 卖 → 回填归因。
// -3% stop OOS 4 段全正 +1.38% net/笔（180 天 636 只验证）。
import { PageHeader } from "@/components/ui/PageHeader";
import { Disclaimer } from "@/components/ui/Disclaimer";
import { NextStepBar } from "@/components/ui/NextStepBar";
import { WorkflowCard } from "@/components/limitup-workflow/WorkflowCard";

export function LimitupWorkflowPage() {
  return (
    <div>
      <PageHeader
        title="打板工作流"
        subtitle="S233 5 Stage 闭环 · -3% stop OOS +1.38% net · watchlist→二次确认→买→exit→归因"
      />
      <div className="mb-4">
        <WorkflowCard />
      </div>
      <Disclaimer />
      <NextStepBar pageCtx="limitup-workflow" />
    </div>
  );
}
