// S087 B3：语境 tab——SentimentContext 决策语境卡（薄）。
// 读 usePreMarketBriefing（sentiment_context + market_emotion），
// 展示天气/熔断软标注/allowed_styles + 市场 4 率——跑选股前的决策语境。
// R13：AskAiButton 携带本 tab 上下文。

import { usePreMarketBriefing } from "@/lib/query";
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

export function ContextTab({ date }: Props) {
  const { data: briefing } = usePreMarketBriefing(date);
  const ctx = briefing?.sentiment_context;
  const me = briefing?.market_emotion;

  const weather = ctx?.weather_state ?? "未取得";
  const fuse = ctx?.fuse_state;
  const fuseState = (fuse as { fuse_state?: string } | null)?.fuse_state ?? "未取得";
  const allowed = (ctx?.allowed_styles ?? []) as string[];
  const forbidden = (ctx?.forbidden_styles ?? []) as string[];
  const composite = ctx?.composite_score;
  // 市场 4 率（market_emotion）
  const ztCount = (me as { zt_count?: number } | null)?.zt_count;
  const dtCount = (me as { dt_count?: number } | null)?.dt_count;
  const maxBoards = (me as { max_boards?: number } | null)?.max_boards;
  const promotionRate = (me as { promotion_rate?: number } | null)?.promotion_rate;

  const askAiContext = [
    `当前页面：语境（SentimentContext）`,
    `天气：${weather} | 熔断：${fuseState} | 综合分：${composite ?? "—"}`,
    `allowed_styles：${allowed.join("、") || "全 12 战法"} | forbidden：${forbidden.join("、") || "无"}`,
    `市场 4 率：涨停${ztCount ?? "—"}/跌停${dtCount ?? "—"}/最高连板${maxBoards ?? "—"}/晋级率${promotionRate ?? "—"}`,
    `S086 R3：暴风雨不再 forbidden（全 allowed，仓位×0.3 软标注建议）`,
  ].join("\n");

  return (
    <div className="space-y-3">
      <GlassCard className="p-4">
        <div className="mb-3 flex items-center gap-2">
          <h3 className="font-semibold">决策语境</h3>
          <Badge variant={weather ? "primary" : "default"}>{weather}</Badge>
        </div>
        <Row label="天气 state" value={weather} ok={!!weather} />
        <Row label="熔断 fuse_state" value={fuseState} ok={fuseState === "normal" || fuseState === "建议降仓"} />
        <Row label="综合情绪分" value={composite != null ? String(composite) : "未取得"} ok={composite != null} />
        <Row label="allowed 战法" value={allowed.length ? `${allowed.length} 项` : "全 12 战法"} ok />
        <Row label="forbidden 战法" value={forbidden.length ? forbidden.join("、") : "无（S086 全 allowed）"} ok={forbidden.length === 0} />
      </GlassCard>

      <GlassCard className="p-4">
        <div className="mb-2 flex items-center gap-2">
          <h3 className="font-semibold">市场 4 率</h3>
        </div>
        <Row label="涨停家数" value={ztCount != null ? String(ztCount) : "未取得"} ok={ztCount != null} />
        <Row label="跌停家数" value={dtCount != null ? String(dtCount) : "未取得"} ok={dtCount != null} />
        <Row label="最高连板" value={maxBoards != null ? `${maxBoards} 板` : "未取得"} ok={maxBoards != null} />
        <Row label="连板晋级率" value={promotionRate != null ? `${promotionRate}` : "未取得"} ok={promotionRate != null} />
      </GlassCard>

      <AskAiButton context={askAiContext} />
    </div>
  );
}
