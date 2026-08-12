// S063 T29：盘中监控主页面重写——PipelineProgressBar → 状态机看板 → Layer1-4 纵向布局。
// 四层辅助决策（spec §3）：分数+色带 / 持仓×情绪联动 / 条件场景推演 / T+1 预判。
import { WorkflowStage } from "./components/WorkflowStage";
import { PipelineProgressBar } from "@/components/workflow/PipelineProgressBar";
import { StateMachineDashboard } from "@/components/intraday/StateMachineDashboard";
import { EmotionTrendChart } from "@/components/intraday/EmotionTrendChart";
import { HoldingsEmotionTable } from "@/components/intraday/HoldingsEmotionTable";
import { ScenarioCards } from "@/components/intraday/ScenarioCards";
import { T1ProjectionPanel } from "@/components/intraday/T1ProjectionPanel";
import { SectionHeader } from "@/components/ui/SectionHeader";
import { GlassCard } from "@/components/ui/GlassCard";

export default function IntradayMonitor() {
  return (
    <WorkflowStage title="盘中监控" subtitle="Intraday Monitor">
      <div className="mb-4">
        <PipelineProgressBar current="intraday" />
      </div>

      {/* 状态机看板 */}
      <div className="mb-6">
        <StateMachineDashboard />
      </div>

      {/* Layer 1：情绪走势图（被动展示） */}
      <section className="mb-6">
        <SectionHeader title="Layer 1 · 情绪走势" subtitle="分数+色带（T-1 基线对比）" />
        <GlassCard className="mt-2 p-4">
          <EmotionTrendChart />
        </GlassCard>
      </section>

      {/* Layer 2：持仓×情绪联动（主动关联） */}
      <section className="mb-6">
        <SectionHeader title="Layer 2 · 持仓×情绪联动" subtitle="双重压力行置顶高亮" />
        <GlassCard className="mt-2 p-4">
          <HoldingsEmotionTable />
        </GlassCard>
      </section>

      {/* Layer 3：条件场景推演（主动推理） */}
      <section className="mb-6">
        <SectionHeader title="Layer 3 · 条件场景推演" subtitle="if-then + 历史参照（标注样本量）" />
        <GlassCard className="mt-2 p-4">
          <ScenarioCards />
        </GlassCard>
      </section>

      {/* Layer 4：T+1 预判（14:30 专项） */}
      <section className="mb-6">
        <SectionHeader title="Layer 4 · T+1 预判" subtitle="14:30 后可用 · 投影非最终判定" />
        <GlassCard className="mt-2 p-4">
          <T1ProjectionPanel />
        </GlassCard>
      </section>
    </WorkflowStage>
  );
}
