// S063 T29：盘中监控主页面重写——PipelineProgressBar → 状态机看板 → Layer1-4 纵向布局。
// 四层辅助决策（spec §3）：分数+色带 / 持仓×情绪联动 / 条件场景推演 / T+1 预判。
// AskAi：注入四层真实数据（latest/holdings/scenarios/t1）作上下文。
import { WorkflowStage } from "./components/WorkflowStage";
import { PipelineProgressBar } from "@/components/workflow/PipelineProgressBar";
import { MarketKillSwitchBanner } from "@/components/workflow/MarketKillSwitchBanner";
import { CalendarFactorHint } from "@/components/workflow/CalendarFactorHint";
import { CandidateStateRail } from "@/components/workflow/CandidateStateRail";
import { EmotionTrendChart } from "@/components/intraday/EmotionTrendChart";
import { HoldingsEmotionTable } from "@/components/intraday/HoldingsEmotionTable";
import { ScenarioCards } from "@/components/intraday/ScenarioCards";
import { T1ProjectionPanel } from "@/components/intraday/T1ProjectionPanel";
import { SectionHeader } from "@/components/ui/SectionHeader";
import { GlassCard } from "@/components/ui/GlassCard";
import { Skeleton } from "@/components/ui/Skeleton";
import { AskAiButton } from "@/components/ui/AskAiButton";
import { useDateTriplet } from "@/lib/query";
import {
  useIntradayLatest,
  useIntradayHoldings,
  useIntradayScenarios,
  useIntradayT1Projection,
} from "@/lib/query";

function buildIntradayContext(
  latest: ReturnType<typeof useIntradayLatest>["data"],
  holdings: ReturnType<typeof useIntradayHoldings>["data"],
  scenarios: ReturnType<typeof useIntradayScenarios>["data"],
  t1: ReturnType<typeof useIntradayT1Projection>["data"],
): string {
  const lines: string[] = ["当前页面：盘中监控"];
  if (latest) {
    lines.push(
      `Layer1 情绪：分数=${latest.score ?? "--"}，趋势=${latest.trend}，色带=${latest.zone}，` +
        `涨停${latest.zt_count ?? "--"}/封板率${latest.seal_rate != null ? latest.seal_rate.toFixed(0) : "--"}%/` +
        `炸板率${latest.break_rate != null ? latest.break_rate.toFixed(0) : "--"}%/涨跌比${latest.ad_ratio != null ? latest.ad_ratio.toFixed(2) : "--"}，` +
        `T-1基线=${latest.t1_baseline ?? "--"}`,
    );
  } else {
    lines.push("Layer1 情绪：未取得");
  }
  if (holdings && holdings.holdings.length > 0) {
    const held = holdings.holdings
      .map((h) => `${h.code}(${h.name}/${h.status}/${h.seal_status}/${h.current_zone}${h.dual_pressure ? "/双重压力" : ""})`)
      .join("，");
    lines.push(`Layer2 持仓情绪：${held}，双重压力数=${holdings.dual_pressure_count}`);
  } else if (holdings) {
    lines.push("Layer2 持仓情绪：无持仓");
  } else {
    lines.push("Layer2 持仓情绪：未取得");
  }
  if (scenarios && scenarios.scenarios.length > 0) {
    const sc = scenarios.scenarios
      .map((s) => `${s.condition}→${s.impact}（${s.suggestion}）`)
      .join("；");
    lines.push(`Layer3 场景推演：${sc}`);
  } else {
    lines.push("Layer3 场景推演：无");
  }
  if (t1 && t1.scenarios && t1.scenarios.length > 0) {
    const proj = t1.scenarios
      .map((s) => `${s.name}:投影分=${s.projected_t1_score}/${s.projected_t1_weather}（${s.assumption}）`)
      .join("，");
    lines.push(`Layer4 T+1预判：${proj}`);
  } else {
    lines.push("Layer4 T+1预判：未到时间或未取得");
  }
  return lines.join("\n");
}

export default function IntradayMonitor() {
  // S092 R15 时区 bug 修复：CalendarFactorHint 的 date 不再用 new Date().toISOString()，
  // 改从 dateTriplet.today 取（后端北京时区锚定）。
  const { data: triplet } = useDateTriplet();
  const latestQ = useIntradayLatest();
  const holdingsQ = useIntradayHoldings();
  const scenariosQ = useIntradayScenarios();
  const t1Q = useIntradayT1Projection();
  const askAiContext = buildIntradayContext(latestQ.data, holdingsQ.data, scenariosQ.data, t1Q.data);

  return (
    <WorkflowStage
      title="盘中监控"
      subtitle="Intraday Monitor"
      actions={<AskAiButton context={askAiContext} />}
    >
      <div className="mb-4">
        <PipelineProgressBar current="intraday" />
      </div>

      {/* S066 §16.4 盘中市场级熔断横幅（指数跌>3% → 不开新仓） */}
      <div className="mb-4">
        <MarketKillSwitchBanner />
      </div>

      {/* S066 §6 盘中日历因子标注（周五/节前降仓提示）。
          S092 R15：date 从 dateTriplet.today 取，不用 new Date().toISOString() */}
      <div className="mb-4">
        {triplet?.today ? (
          <CalendarFactorHint date={triplet.today} />
        ) : (
          <Skeleton className="h-8 w-full" />
        )}
      </div>

      {/* 标的状态 rail（S143，date=triplet.today，修 IntradayMonitor 全零 bug） */}
      <div className="mb-6">
        <CandidateStateRail date={triplet?.today} />
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
