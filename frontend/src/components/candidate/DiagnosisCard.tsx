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
        {/* S084 R4.1/R4.2/R4.3：tencent_quote 扩展 + 板块资金 + 前日成交额 */}
        {row("昨收", ind.last_close)}
        {row("开盘", ind.open)}
        {row("涨跌额", ind.change_amt)}
        {row("市盈率TTM", ind.pe_ttm)}
        {row("总市值", ind.mcap_yi, "亿")}
        {row("市净率", ind.pb)}
        {row("板块净流入", ind.sector_net_inflow, "万")}
        {row("板块流入", ind.sector_inflow, "万")}
        {row("板块流出", ind.sector_outflow, "万")}
        {row("前日成交", ind.prev_amount_yi, "亿")}
      </div>

      {/* S084 Q6=B：3 子对象——选股池一站式战法盘前因子 */}
      {card.gene_score && <GeneScoreBlock data={card.gene_score} evaluation={card.evaluation} />}
      {card.pool_item && <PoolItemBlock data={card.pool_item} />}
      {card.derived && <DerivedBlock data={card.derived} />}

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

      {/* S148 R7：ST carve-out 正向标（摘帽/重组/扭亏），radar 白名单 re-include 的 ST 股 */}
      {card.st_play && (
        <div className="text-sm text-emerald-600">ST-play：{card.st_play}（carve-out 保留）</div>
      )}

      {/* S148 Phase 2：首板 9 维分析（§44 未 validated，描述性 context，非买卖信号） */}
      {card.first_board_analysis && (
        <div className="text-sm">
          <div className="text-muted-foreground mb-1">
            首板 9 维分析 <span className="text-warning">（§44 未 validated，仅参考）</span>：
          </div>
          <div className="grid grid-cols-3 gap-x-4 gap-y-1">
            {Object.entries(card.first_board_analysis.scores).map(([dim, score]) => (
              <div key={dim} className="flex justify-between">
                <span className="text-muted-foreground">{dim}</span>
                <span>{(score as number) < 0 ? "—" : String(score)}</span>
              </div>
            ))}
          </div>
          {card.first_board_analysis.total != null && (
            <div className="mt-1 text-xs text-warning">
              复合分 {card.first_board_analysis.total}（§44 未 validated，不作物买卖信号）
            </div>
          )}
        </div>
      )}

      {missing.length > 0 && (
        <div className="text-sm text-warning">
          <div className="mb-1">未取得：</div>
          {missing.map(([k, v]) => (
            <div key={k}>{k} — {v}</div>
          ))}
        </div>
      )}

      {card.eight_standards && (
        <div className="text-sm">
          <div className="text-muted-foreground mb-1">八项标准：</div>
          <div className="grid grid-cols-1 gap-y-1">
            {card.eight_standards.items.map((it) => (
              <div key={it.key} className="flex justify-between gap-2">
                <span className="text-muted-foreground">{it.label}</span>
                <span className={
                  it.status === "pass" ? "text-emerald-600" :
                  it.status === "fail" ? "text-red-600" :
                  "text-muted-foreground/60"
                }>
                  {it.status === "pass" ? "通过" : it.status === "fail" ? "未过" : "—"}
                  {it.actual ? `（${it.actual}）` : ""}
                </span>
              </div>
            ))}
          </div>
          {card.capped && card.cap_reason && (
            <div className="mt-2 rounded-lg bg-amber-50 p-2 text-xs text-amber-700">
              封顶标记：{card.cap_reason}
            </div>
          )}
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

// S084 Q6=B：3 子对象展示块（gene_score/pool_item/derived）+ S151 §44 标签+降权 pill
function GeneScoreBlock({ data, evaluation }: { data: Record<string, unknown>; evaluation?: { score_weight: number; demoted_dims: string[]; validation_note: string } | null }) {
  const gs = data as { total_score?: number; zt_count_250d?: number; high_gene?: boolean; qualify?: boolean; factors?: Record<string, number | null> };
  const factorEntries = gs.factors ? Object.entries(gs.factors) : [];
  return (
    <div className="text-sm">
      <div className="text-muted-foreground mb-1">涨停基因（GeneScore）<span className="text-amber-500">（§44 rho≈0，无方向性）</span>{evaluation?.demoted_dims?.includes("gene_score") && <span className="ml-1 text-[10px] text-red-500" title={evaluation.validation_note}>×{evaluation.score_weight}</span>}：</div>
      <div className="grid grid-cols-2 gap-x-6 gap-y-1">
        {row("基因总分", gs.total_score)}
        {row("250日涨停", gs.zt_count_250d)}
        {row("高基因", gs.high_gene == null ? null : gs.high_gene ? "是" : "否")}
        {row("合格", gs.qualify == null ? null : gs.qualify ? "是" : "否")}
      </div>
      {factorEntries.length > 0 && (
        <div className="mt-1 text-xs text-muted-foreground">
          因子：{factorEntries.map(([k, v]) => `${k}=${v ?? "—"}`).join(" · ")}
        </div>
      )}
    </div>
  );
}

function PoolItemBlock({ data }: { data: Record<string, unknown> }) {
  const p = data as { lbc?: number; zbc?: number; fbt?: string; zdp?: number; zje?: number; hybk?: string };
  return (
    <div className="text-sm">
      <div className="text-muted-foreground mb-1">涨停池原始 dict（pool_item）：</div>
      <div className="grid grid-cols-2 gap-x-6 gap-y-1">
        {row("连板数", p.lbc)}
        {row("炸板次数", p.zbc)}
        {row("首封时间", p.fbt)}
        {row("涨幅%", p.zdp)}
        {row("涨停价", p.zje)}
        {row("行业", p.hybk)}
      </div>
    </div>
  );
}

function DerivedBlock({ data }: { data: Record<string, unknown> }) {
  const d = data as { broken_duration_min?: number; max_drop_pct?: number; last_lock_time?: string; data_status?: string };
  return (
    <div className="text-sm">
      <div className="text-muted-foreground mb-1">S070 R7 分时派生（derived，T-1 昨日）：</div>
      <div className="grid grid-cols-2 gap-x-6 gap-y-1">
        {row("炸板时长(分)", d.broken_duration_min)}
        {row("最大回撤%", d.max_drop_pct)}
        {row("最后封死", d.last_lock_time)}
        {row("数据状态", d.data_status)}
      </div>
    </div>
  );
}
