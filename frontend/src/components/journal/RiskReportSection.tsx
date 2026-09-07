// S166: 风险账本区——在险资金（R3 诚实标签 centerpiece）+ 风控总报告（权益/纪律/违反）。
// 读 GET /api/risk/at-risk + /api/risk/report。fresh-impl。
// ⚠️ R3 grill #8："edge 来自风控"数学谬误——risk_status 如实呈现 stop 对 gap-down 仪式非保护
// （s144 path_lift<1）/ kill_switch 通知级非阻断 / 真实风控=仓位 sizing + gap-down 诚实标，
// 不宣称"core 风控保护"，UI 原文呈现不软化。
// frontend review fixes: error 解构 + ApiError 横幅（#2 HIGH）；后端 honest label 文本带
// markdown ** → 前端 strip（#11 LOW）；kill_switch_note amber 非灰（contentious#1）；
// cards 接 | undefined 免 as cast fallback（#12 LOW）。
import { GlassCard } from "@/components/ui/GlassCard";
import { ApiError } from "@/lib/api";
import { useAtRisk, useRiskReport } from "@/lib/query";
import type {
  AtRiskReport, RiskReportResponse, HonestRiskLabels,
} from "@/lib/journal-contract";

function pct(v: number | null | undefined, digits = 2): string {
  if (v == null || Number.isNaN(v)) return "—";
  return `${v >= 0 ? "+" : ""}${v.toFixed(digits)}%`;
}
function yuan(v: number | null | undefined): string {
  if (v == null || Number.isNaN(v)) return "—";
  return v.toFixed(0);
}
function wr(v: number | null): string {
  return v == null ? "—" : `${(v * 100).toFixed(1)}%`;
}
// 后端 honest label 文本带 markdown **bold**（at_risk.render 会 strip，但 API 返原样）；
// 前端无 markdown 渲染器，裸显会出字面 **。轻量 strip——不值得引入 markdown 库。
function stripMd(s: string | null | undefined): string {
  return (s ?? "").replace(/\*\*/g, "");
}

function HonestLabels({ rs }: { rs: HonestRiskLabels }) {
  return (
    <div className="space-y-1 rounded bg-amber-500/10 p-2 text-xs text-amber-700 dark:text-amber-400">
      {rs.labels.map((l) => (
        <div key={l.key}>⚠️ {stripMd(l.text)}</div>
      ))}
      {/* kill_switch_note amber（非灰）——R3 诚实消息须醒目，不软化（contentious#1 fix） */}
      <div className="text-amber-600 dark:text-amber-300">{stripMd(rs.kill_switch_note)}</div>
      <div className="font-medium">{stripMd(rs.honest_summary)}</div>
    </div>
  );
}

function AtRiskCard({ data }: { data: AtRiskReport | undefined }) {
  if (!data) return <div className="text-xs text-muted-foreground">加载中…</div>;
  if (!data.available) {
    return <div className="text-xs text-muted-foreground">{data.reason}</div>;
  }
  return (
    <div className="space-y-2">
      <HonestLabels rs={data.risk_status} />
      {data.unbounded_note && (
        <div className="rounded bg-red-500/10 p-2 text-xs text-red-500">⚠️ {stripMd(data.unbounded_note)}</div>
      )}
      <div className="flex flex-wrap gap-3 text-xs">
        <span>持仓 {data.position_count} 只</span>
        <span>占用本金 {yuan(data.total_capital)} 元</span>
        <span>有边界在险合计 {yuan(data.total_at_risk)} 元</span>
        {data.at_risk_of_equity_pct != null && (
          <span>占账户 {data.at_risk_of_equity_pct.toFixed(1)}%</span>
        )}
      </div>
      {data.equity_base_hint && (
        <div className="text-xs text-muted-foreground">{data.equity_base_hint}</div>
      )}
      {data.over_per_trade_limit && data.over_per_trade_limit.length > 0 && (
        <div className="text-xs text-red-500">
          ⚠️ 超单笔上限：{data.over_per_trade_limit.map((p) => `${p.name || p.code} ${p.pct_of_equity.toFixed(1)}%`).join("、")}
        </div>
      )}
      {data.over_position_limit && (
        <div className="text-xs text-red-500">
          ⚠️ 持仓数 {data.over_position_limit.actual} 超过上限 {data.over_position_limit.limit}
        </div>
      )}
      <div className="overflow-x-auto">
        <table className="w-full text-xs">
          <thead>
            <tr className="text-muted-foreground">
              <th className="px-2 text-left">代码</th><th className="px-2 text-left">名称</th>
              <th className="px-2">股数</th><th className="px-2">成本</th>
              <th className="px-2">本金</th><th className="px-2">计划止损</th>
              <th className="px-2">在险</th><th className="px-2">在险%</th>
            </tr>
          </thead>
          <tbody>
            {data.positions.map((p) => (
              <tr key={p.id} className="border-t">
                <td className="px-2 font-mono">{p.code}</td>
                <td className="px-2">{p.name || "—"}</td>
                <td className="px-2 text-center">{p.shares}</td>
                <td className="px-2 text-center">{p.avg_cost.toFixed(2)}</td>
                <td className="px-2 text-center">{yuan(p.capital)}</td>
                <td className="px-2 text-center">
                  {p.planned_stop != null ? p.planned_stop.toFixed(2) : <span className="text-red-500">未设</span>}
                </td>
                <td className="px-2 text-center">
                  {p.bounded ? yuan(p.at_risk) : <span className="text-red-500">未设边界</span>}
                </td>
                <td className="px-2 text-center">{p.bounded ? pct(p.at_risk_pct) : "—"}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}

// cards 接 | undefined：loading 时 undefined（不臆造 fallback EquityCurve 再 as cast）。
function EquityCard({ eq }: { eq: RiskReportResponse["equity"] | undefined }) {
  if (!eq) return <div className="text-xs text-muted-foreground">加载中…</div>;
  if (!eq.available) return <div className="text-xs text-muted-foreground">{eq.reason}</div>;
  return (
    <div className="space-y-2">
      <div className="grid grid-cols-2 gap-2 text-xs sm:grid-cols-4">
        <div>净盈亏 <span className="text-foreground">{yuan(eq.net_pnl)} 元</span></div>
        <div>当前回撤 <span className="text-red-500">{yuan(eq.current_drawdown)}</span></div>
        <div>历史最大回撤 <span className="text-red-500">{yuan(eq.max_drawdown)}</span></div>
        <div>未创新高 <span className="text-foreground">{eq.trades_since_peak} 笔</span></div>
        <div>胜率 <span className="text-foreground">{wr(eq.win_rate)}</span></div>
        <div>盈亏比 <span className="text-foreground">{eq.payoff_ratio ?? "—"}</span></div>
        <div>Profit Factor <span className="text-foreground">{eq.profit_factor ?? "—"}</span></div>
        <div>最长连亏 <span className="text-foreground">{eq.worst_losing_streak} 笔</span></div>
      </div>
      <div className="text-xs text-muted-foreground">
        盈利集中度：最好一笔占净利 {eq.best_trade_share != null ? `${(eq.best_trade_share * 100).toFixed(0)}%` : "—"}；
        去掉最好 1 笔剩 {yuan(eq.net_without_best1)}，去掉最好 3 笔剩 {yuan(eq.net_without_best3)}
      </div>
    </div>
  );
}

function DisciplineCard({ dp }: { dp: RiskReportResponse["discipline"] | undefined }) {
  if (!dp) return <div className="text-xs text-muted-foreground">加载中…</div>;
  if (!dp.available) return <div className="text-xs text-muted-foreground">{dp.reason}</div>;
  const wi = dp.what_if_only_planned;
  return (
    <div className="space-y-2 text-xs">
      <div>执行率 <span className="text-foreground">{dp.execution_rate != null ? `${(dp.execution_rate * 100).toFixed(0)}%` : "—"}</span></div>
      {wi.cost_of_indiscipline != null && (
        <div className="rounded bg-blue-500/10 p-2">
          只做按计划的交易，净盈亏会是 {yuan(wi.planned_only_net)} 元
          （实际 {yuan(wi.actual_net)}，差 {yuan(wi.cost_of_indiscipline)}）—— 纪律值多少钱，一个数说清
        </div>
      )}
      <table className="w-full">
        <thead><tr className="text-muted-foreground">
          <th className="px-2 text-left">分组</th><th className="px-2">笔数</th><th className="px-2">胜率</th><th className="px-2">净盈亏</th>
        </tr></thead>
        <tbody>
          {([["按计划", dp.planned], ["计划外", dp.unplanned], ["未标注", dp.untagged]] as const).map(([k, b]) => (
            <tr key={k} className="border-t">
              <td className="px-2">{k}</td>
              <td className="px-2 text-center">{b.count}</td>
              <td className="px-2 text-center">{wr(b.win_rate)}</td>
              <td className="px-2 text-center">{yuan(b.net_pnl)}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function ViolationsCard({ vi }: { vi: RiskReportResponse["violations"] | undefined }) {
  if (!vi) return <div className="text-xs text-muted-foreground">加载中…</div>;
  if (!vi.available) return <div className="text-xs text-muted-foreground">{vi.reason}</div>;
  return (
    <div className="space-y-2 text-xs">
      <div>违反自设规则 <span className="text-red-500">{vi.violation_count} 次</span>
        {vi.is_default_rules && "（用的还是默认阈值，建议先改一遍）"}</div>
      {vi.unchecked.length > 0 && (
        <div className="text-amber-600">⚠️ 以下规则没查（无数据）：{vi.unchecked.join("、")}</div>
      )}
      {vi.violations.length > 0 && (
        <ul className="list-inside list-disc space-y-0.5">
          {vi.violations.map((v, i) => (
            <li key={i}>
              <span className="text-muted-foreground">{v.date} {v.label}：</span>
              上限 {v.limit}，实际 {v.actual}（{v.detail}）
            </li>
          ))}
        </ul>
      )}
      {vi.after_loss_streak.trades > 0 && (
        <div className="text-amber-600">
          连亏 {vi.after_loss_streak.threshold} 笔后还继续做了 {vi.after_loss_streak.trades} 笔，
          胜率 {wr(vi.after_loss_streak.win_rate)}——历史事实，不下"该停手"结论
        </div>
      )}
    </div>
  );
}

function RollingCard({ ro }: { ro: RiskReportResponse["rolling"] | undefined }) {
  if (!ro) return <div className="text-xs text-muted-foreground">加载中…</div>;
  if (!ro.available) return <div className="text-xs text-muted-foreground">{ro.reason}</div>;
  const w = (n: string) => ro.windows[n];
  const rows: [string, import("@/lib/journal-contract").RollingWindow | undefined][] = [
    ["终身", ro.lifetime],
    ["近10", w("10")],
    ["近20", w("20")],
    ["近50", w("50")],
  ];
  return (
    <div className="space-y-1 text-xs">
      <table className="w-full">
        <thead><tr className="text-muted-foreground">
          <th className="px-2 text-left">窗口</th><th className="px-2">笔数</th><th className="px-2">净盈亏</th>
          <th className="px-2">胜率</th><th className="px-2">PF</th><th className="px-2">执行率</th>
        </tr></thead>
        <tbody>
          {rows.map(([k, s]) => s ? (
            <tr key={k} className="border-t">
              <td className="px-2">{k}</td>
              <td className="px-2 text-center">{s.trades}</td>
              <td className="px-2 text-center">{yuan(s.net_pnl)}</td>
              <td className="px-2 text-center">{wr(s.win_rate ?? null)}</td>
              <td className="px-2 text-center">{s.profit_factor ?? "—"}</td>
              <td className="px-2 text-center">{s.execution_rate != null ? `${(s.execution_rate * 100).toFixed(0)}%` : "—"}</td>
            </tr>
          ) : null)}
        </tbody>
      </table>
      <div className="text-muted-foreground">{ro.note}</div>
    </div>
  );
}

export function RiskReportSection() {
  const { data: atRiskData, error: atRiskErr } = useAtRisk();
  const { data: reportData, error: reportErr } = useRiskReport();
  const err = atRiskErr || reportErr;
  return (
    <div className="space-y-3">
      {err && (
        <div className="rounded bg-red-500/10 p-2 text-xs text-red-500">
          后端未就绪：{err instanceof ApiError ? err.message : String(err)}
        </div>
      )}
      <GlassCard className="space-y-2 p-3">
        <div className="text-sm font-medium">在险资金（⚠️ R3 诚实标签：stop 对隔夜 gap-down 是仪式非保护）</div>
        <AtRiskCard data={atRiskData} />
      </GlassCard>
      <GlassCard className="space-y-2 p-3">
        <div className="text-sm font-medium">权益曲线</div>
        <EquityCard eq={reportData?.equity} />
      </GlassCard>
      <GlassCard className="space-y-2 p-3">
        <div className="text-sm font-medium">滚动窗口（10/20/50 笔对比，看最近退化）</div>
        <RollingCard ro={reportData?.rolling} />
      </GlassCard>
      <GlassCard className="space-y-2 p-3">
        <div className="text-sm font-medium">纪律归因（只做按计划的会怎样）</div>
        <DisciplineCard dp={reportData?.discipline} />
      </GlassCard>
      <GlassCard className="space-y-2 p-3">
        <div className="text-sm font-medium">规则违反（按你自己写的阈值逐条查）</div>
        <ViolationsCard vi={reportData?.violations} />
      </GlassCard>
    </div>
  );
}
