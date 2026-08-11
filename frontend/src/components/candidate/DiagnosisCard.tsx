// 个股诊断卡：六类指标 + 活跃度档 + 企稳信号（S002 F3，AC4/AC6）。
// 合规 AC10：不含方向结论词；"交 AI 判断"走 AskAiButton（调 /api/chat，S001 已修）。
import type { DiagnosisCard as Card } from "@/lib/candidates";
import { GlassCard } from "@/components/ui/GlassCard";
import { AskAiButton } from "@/components/ui/AskAiButton";

const row = (label: string, v: number | string | null | undefined, unit = "") =>
  v == null ? null : (
    <div className="flex justify-between text-sm">
      <span className="text-muted-foreground">{label}</span>
      <span>{typeof v === "string" ? v : `${v}${unit}`}</span>
    </div>
  );

export function DiagnosisCardView({ card }: { card: Card }) {
  const ind = card.indicators;
  const missing = Object.entries(ind.missing);
  return (
    <GlassCard className="p-4 space-y-4">
      <div className="flex items-center justify-between">
        <div className="font-medium">{ind.name} <span className="text-muted-foreground">{ind.code}</span></div>
        <span className="text-sm text-muted-foreground">{card.as_of}</span>
      </div>

      <div className="flex items-center gap-2 text-sm">
        <span className="text-muted-foreground">活跃度：</span>
        <span className="font-medium">{card.activity.tier}</span>
        {card.activity.rules_applied.length > 0 && (
          <span className="text-muted-foreground">（{card.activity.rules_applied.join("，")}）</span>
        )}
      </div>

      <div className="grid grid-cols-2 gap-x-6 gap-y-1">
        {row("换手", ind.turnover_pct, "%")}
        {row("量比", ind.vol_ratio)}
        {row("成交额", ind.amount_yi, "亿")}
        {row("振幅", ind.amplitude_pct, "%")}
        {row("连板数", ind.consec_boards)}
        {row("主力净流", ind.main_net_inflow, "万")}
        {row("5日主力", ind.main_net_5d, "万")}
        {row("龙虎榜机构", ind.dragon_tiger_inst_net, "万")}
        {row("北向", ind.northbound, "万")}
        {row("竞价开盘", ind.auction_open_pct != null ? `${(ind.auction_open_pct * 100).toFixed(2)}%` : null)}
        {row("板块资金", ind.sector_flow)}
      </div>

      <div className="text-sm">
        <div className="text-muted-foreground mb-1">企稳信号：</div>
        <div className="grid grid-cols-2 gap-x-6 gap-y-1">
          {sig("跌停减少", card.stabilization.fewer_limit_downs)}
          {sig("量能止跌", card.stabilization.volume_stop_falling)}
          {sig("主力转正", card.stabilization.main_flow_turning_positive)}
          {sig("连板上升", card.stabilization.board_height_rising)}
        </div>
      </div>

      {(ind.announcements.length > 0 || ind.concepts.length > 0) && (
        <div className="text-sm">
          <div className="text-muted-foreground mb-1">催化剂：</div>
          {ind.announcements.slice(0, 5).map((a) => (
            <div key={`${a.date}-${a.title.slice(0, 12)}`}>{a.date} · {a.title}</div>
          ))}
          {ind.concepts.length > 0 && (
            <div className="text-muted-foreground mt-1">板块：{ind.concepts.join("、")}</div>
          )}
        </div>
      )}

      {card.risk_flags.length > 0 && (
        <div className="text-sm text-warning">风险标注：{card.risk_flags.join("、")}</div>
      )}

      {missing.length > 0 && (
        <div className="text-sm text-warning">
          <div className="mb-1">未取得：</div>
          {missing.map(([k, v]) => (
            <div key={k}>{k} — {v}</div>
          ))}
        </div>
      )}

      <div className="pt-2 border-t border-border">
        <span className="text-xs text-muted-foreground">方向判断交用户 AI，系统不输出结论</span>
        <div className="mt-2">
          <AskAiButton context={`${ind.name} ${ind.code} 诊断卡：活跃度${card.activity.tier}，规则 ${card.activity.rules_applied.join("、")}`} />
        </div>
      </div>
    </GlassCard>
  );
}

function sig(label: string, v: boolean | null | undefined) {
  if (v == null) return null;
  return (
    <div className="flex justify-between">
      <span className="text-muted-foreground">{label}</span>
      <span>{v ? "命中" : "未命中"}</span>
    </div>
  );
}
