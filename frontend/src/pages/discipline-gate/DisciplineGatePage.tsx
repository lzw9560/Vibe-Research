// pages/discipline-gate/DisciplineGatePage.tsx — S231 打板纪律门禁看板页。
// 风控工具非 edge 基建。cap=0 terminal BLOCK + C1-C7 7 条件展示。
import { PageHeader } from "@/components/ui/PageHeader";
import { Disclaimer } from "@/components/ui/Disclaimer";
import { NextStepBar } from "@/components/ui/NextStepBar";
import { DisciplineGateCard } from "@/components/discipline-gate/DisciplineGateCard";

export function DisciplineGatePage() {
  return (
    <div>
      <PageHeader
        title="打板纪律门禁"
        subtitle="S231 风控工具 · 7 条件门禁 + cap=0 terminal · 非选股 edge"
      />
      <div className="mb-4">
        <DisciplineGateCard />
      </div>
      <Disclaimer />
      <NextStepBar pageCtx="discipline-gate" />
    </div>
  );
}
