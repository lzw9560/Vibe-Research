// S087 B3：语境 tab——SentimentContext 决策语境卡（薄）。
// 读 usePreMarketBriefing（sentiment_context + market_emotion），
// 展示天气/熔断软标注/allowed_styles + 市场 4 率——跑选股前的决策语境。
// R13：AskAiButton 携带本 tab 上下文。

import { usePreMarketBriefing, localTodayStr } from "@/lib/query";
import { useQuery } from "@tanstack/react-query";
import { request } from "@/lib/api/client";
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

  // R19：板块轮动（接 /api/strategy/funnel/sector-rotation，有数据端点；/api/sector/rotation 空弃用）
  const { data: sectorRot } = useQuery({
    queryKey: ["sector-rotation", date ?? "latest"],
    queryFn: () =>
      request<{ date: string; strength_rank: Array<{ industry: string; zt_count_today: number; strength: number; rank: number }> }>(
        `/api/strategy/funnel/sector-rotation?date=${date ?? localTodayStr()}`,
      ),
    retry: false,
  });
  const sectors = sectorRot?.strength_rank ?? [];

  // S088 盘前暴风雨预测（独立于事后 STI 检测）
  const { data: storm } = useQuery({
    queryKey: ["storm-predict", date ?? "latest"],
    queryFn: () =>
      request<{ date: string; probability: number; risk_level: string; suggested_position: number; factors: Array<{ name: string; score: number; detail: string; data_status: string }>; disclaimer?: string }>(
        `/sentiment/storm-predict${date ? `?date=${date}` : ""}`,
      ),
    retry: false,
  });

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
    `当前页面：语境（SentimentContext + S088 盘前暴风雨预测）`,
    `暴风雨预测：概率 ${storm?.probability ?? "—"}/100 风险 ${storm?.risk_level ?? "—"} 建议仓位 ${storm ? `${(storm.suggested_position * 100).toFixed(0)}%` : "—"}`,
    `天气：${weather} | 熔断：${fuseState} | 综合分：${composite ?? "—"}`,
    `allowed_styles：${allowed.join("、") || "全 12 战法"} | forbidden：${forbidden.join("、") || "无"}`,
    `市场 4 率：涨停${ztCount ?? "—"}/跌停${dtCount ?? "—"}/最高连板${maxBoards ?? "—"}/晋级率${promotionRate ?? "—"}`,
    `板块轮动 TOP：${sectors.slice(0, 5).map((s) => `${s.industry}(${s.strength})`).join("、")}`,
    `S086 R3：暴风雨不再 forbidden（全 allowed，仓位×0.3 软标注建议）`,
  ].join("\n");

  return (
    <div className="space-y-3">
      {/* S088 盘前暴风雨预测 */}
      <GlassCard className={"p-4 " + ((storm?.risk_level === "高" || storm?.risk_level === "极高") ? "ring-2 ring-red-500/30" : "")}>
        <div className="mb-2 flex items-center gap-2">
          <h3 className="font-semibold">盘前暴风雨预测</h3>
          <Badge variant={storm?.risk_level === "极高" || storm?.risk_level === "高" ? "warning" : storm?.risk_level === "中" ? "default" : "success"}>
            {storm?.risk_level ?? "—"}
          </Badge>
        </div>
        <div className="flex items-baseline gap-3">
          <span className="text-3xl font-bold font-mono text-red-400">{storm?.probability ?? "—"}</span>
          <span className="text-sm text-muted-foreground/70">/100 暴风雨概率</span>
          <span className="ml-auto text-sm text-muted-foreground">建议仓位 {storm ? `${(storm.suggested_position * 100).toFixed(0)}%` : "—"}</span>
        </div>
        {storm?.factors && storm.factors.length > 0 && (
          <div className="mt-2 space-y-1 text-xs">
            {storm.factors.map((f) => (
              <div key={f.name} className="flex justify-between">
                <span className="text-muted-foreground/70">{f.name}</span>
                <span className={f.data_status === "missing" ? "text-muted-foreground/40" : "text-foreground"}>{f.score} ({f.detail})</span>
              </div>
            ))}
          </div>
        )}
        {storm?.disclaimer && <p className="mt-2 text-[10px] text-muted-foreground/40">{storm.disclaimer}</p>}
      </GlassCard>

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

      <GlassCard className="p-4">
        <h3 className="mb-2 font-semibold">板块轮动（强度 TOP 5）</h3>
        <div className="space-y-1">
          {sectors.slice(0, 5).map((s) => (
            <div key={s.industry} className="flex items-center justify-between py-1 text-sm border-b border-border/20 last:border-0">
              <span className="font-mono text-foreground">{s.rank}. {s.industry}</span>
              <span className="text-muted-foreground/70">涨停{s.zt_count_today} · 强度{s.strength}</span>
            </div>
          ))}
          {sectors.length === 0 && <p className="text-sm text-muted-foreground">板块轮动未取得</p>}
        </div>
      </GlassCard>

      <AskAiButton context={askAiContext} />
    </div>
  );
}
