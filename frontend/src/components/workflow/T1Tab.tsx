// S087 B2：T-1 tab——盘前数据就绪检查（薄状态卡）。
// 读 usePreMarketBriefing（/api/workflow/pre-market）+ useWorkflowStatus，
// 展示 gene_scores/STI/天气/derived 是否就绪——跑选股前的输入检查。
// R13：AskAiButton 携带本 tab 上下文。

import { usePreMarketBriefing, useWorkflowStatus } from "@/lib/query";
import { GlassCard } from "@/components/ui/GlassCard";
import { Badge } from "@/components/ui/Badge";
import { AskAiButton } from "@/components/ui/AskAiButton";

interface Props {
  date?: string;
}

function Row({ label, value, ok }: { label: string; value: string; ok?: boolean }) {
  return (
    <div className="flex items-center justify-between py-1.5 text-sm">
      <span className="text-muted-foreground/70">{label}</span>
      <span className={ok ? "text-emerald-400" : "text-muted-foreground"}>{value}</span>
    </div>
  );
}

export function T1Tab({ date }: Props) {
  const { data: briefing } = usePreMarketBriefing(date);
  const { data: status } = useWorkflowStatus();

  const ctx = briefing?.sentiment_context;
  const dataDate = briefing?.data_date;
  const isDone = briefing?.status === "done";
  const weather = ctx?.weather_state;
  const stiScore = ctx?.sti_score;
  const stiPhase = ctx?.sti_phase;
  const sourceDate = ctx?.source_date;
  // derived 分时：_collect done 即 R1 涨停池+derived 已采集；idle/未跑 → missing
  const derivedReady = isDone;

  const askAiContext = [
    `当前页面：T-1 数据就绪检查`,
    `briefing 状态：${briefing?.status ?? "加载中"}（data_date=${dataDate ?? "—"}）`,
    `天气：${weather ?? "未取得"} | STI T-1：score=${stiScore ?? "—"} phase=${stiPhase ?? "—"}`,
    `T-1 source_date：${sourceDate ?? "—"}`,
    `derived 分时：${derivedReady ? "已采集" : "盘前未采集（降级 missing）"}`,
    `后端 stageKey：${status?.stage ?? "—"} | market_status：${status?.market_status ?? "—"}`,
  ].join("\n");

  return (
    <div className="space-y-3">
      <GlassCard className="p-4">
        <div className="mb-3 flex items-center gap-2">
          <h3 className="font-semibold">T-1 数据就绪</h3>
          <Badge variant={isDone ? "success" : "default"}>{briefing?.status ?? "加载中"}</Badge>
        </div>
        <Row label="涨停池 gene_scores" value={dataDate ?? "未取得"} ok={!!dataDate} />
        <Row label="STI T-1 行" value={stiScore != null ? `${stiScore} / ${stiPhase ?? "—"}` : "未取得"} ok={stiScore != null} />
        <Row label="天气 state" value={weather ?? "未取得"} ok={!!weather} />
        <Row label="T-1 source_date" value={sourceDate ?? "—"} ok={!!sourceDate} />
        <Row label="derived 分时" value={derivedReady ? "已采集" : "盘前未采集（降级 missing）"} ok={derivedReady} />
      </GlassCard>
      <AskAiButton context={askAiContext} />
    </div>
  );
}
