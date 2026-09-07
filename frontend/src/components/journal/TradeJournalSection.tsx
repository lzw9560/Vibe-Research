// S166: 交易日志区——成交列表 + 录入/删除 + 自我体检 stats。fresh-impl。
// 读 GET /api/journal/list + /api/journal/stats；写 POST /api/journal/add + /delete。
// 不臆造：后端未就绪 → ApiError 诚实横幅；空账本 → 后端 available:False reason 如实呈现。
import { useState } from "react";
import { GlassCard } from "@/components/ui/GlassCard";
import { ApiError } from "@/lib/api";
import {
  useJournalTrades, useJournalStats, useAddTrade, useDeleteTrade,
} from "@/lib/query";
import { PLAYBOOKS, type Playbook, type Fill, type AddTradeInput } from "@/lib/journal-contract";

function pct(v: number | null | undefined, digits = 2): string {
  if (v == null || Number.isNaN(v)) return "—";
  return `${v >= 0 ? "+" : ""}${v.toFixed(digits)}%`;
}
function yuan(v: number | null | undefined): string {
  if (v == null || Number.isNaN(v)) return "—";
  return v.toFixed(0);
}

function FillEditor({ fills, onChange }: {
  fills: Fill[];
  onChange: (f: Fill[]) => void;
}) {
  const addRow = () => onChange([...fills, { side: "buy", date: "", price: 0, shares: 0 }]);
  const upd = (i: number, patch: Partial<Fill>) =>
    onChange(fills.map((f, j) => (j === i ? { ...f, ...patch } : f)));
  const del = (i: number) => onChange(fills.filter((_, j) => j !== i));
  return (
    <div className="space-y-1">
      <div className="text-xs text-muted-foreground">
        成交明细（填了系统自动算加权成本/已实现盈亏/持有天数；不填则用下面的盈亏% 快记）
      </div>
      {fills.map((f, i) => (
        <div key={i} className="flex flex-wrap items-center gap-1 text-xs">
          <select
            value={f.side}
            onChange={(e) => upd(i, { side: e.target.value as Fill["side"] })}
            className="rounded border bg-background px-1 py-0.5"
          >
            <option value="buy">买</option>
            <option value="sell">卖</option>
          </select>
          <input type="date" value={f.date} onChange={(e) => upd(i, { date: e.target.value })}
            className="rounded border bg-background px-1 py-0.5" />
          <input type="number" placeholder="价" value={f.price || ""}
            onChange={(e) => upd(i, { price: Number(e.target.value) })}
            className="w-20 rounded border bg-background px-1 py-0.5" />
          <input type="number" placeholder="股" value={f.shares || ""}
            onChange={(e) => upd(i, { shares: Number(e.target.value) })}
            className="w-20 rounded border bg-background px-1 py-0.5" />
          <button onClick={() => del(i)} className="text-red-500 hover:underline">删</button>
        </div>
      ))}
      <button onClick={addRow} className="text-xs text-blue-500 hover:underline">+ 加一笔成交</button>
    </div>
  );
}

function AddTradeForm() {
  const add = useAddTrade();
  const [date, setDate] = useState("");
  const [code, setCode] = useState("");
  const [name, setName] = useState("");
  const [playbook, setPlaybook] = useState<Playbook>("打板");
  const [pnlPct, setPnlPct] = useState("");
  const [asPlanned, setAsPlanned] = useState<"true" | "false" | "">("");
  const [note, setNote] = useState("");
  const [plannedStop, setPlannedStop] = useState("");
  const [plannedTarget, setPlannedTarget] = useState("");
  const [fills, setFills] = useState<Fill[]>([]);
  const [err, setErr] = useState<string | null>(null);

  function reset() {
    setDate(""); setCode(""); setName(""); setPnlPct(""); setAsPlanned("");
    setNote(""); setPlannedStop(""); setPlannedTarget(""); setFills([]);
  }
  function submit() {
    setErr(null);
    if (!date || !code.trim()) {
      setErr("日期和代码必填");
      return;
    }
    // FillEditor 校验：有 fills 时每笔须 date + price>0 + shares>0（否则后端 ValueError）
    for (let i = 0; i < fills.length; i++) {
      const f = fills[i];
      if (!f.date) { setErr(`第 ${i + 1} 笔成交缺日期`); return; }
      if (!f.price || f.price <= 0) { setErr(`第 ${i + 1} 笔成交价格须 > 0`); return; }
      if (!f.shares || f.shares <= 0) { setErr(`第 ${i + 1} 笔成交股数须 > 0`); return; }
    }
    const body: AddTradeInput = {
      date, code: code.trim().padStart(6, "0"), name, playbook,
      pnl_pct: pnlPct === "" ? null : Number(pnlPct),
      as_planned: asPlanned === "" ? null : asPlanned === "true",
      note, fills: fills.length ? fills : null,
      planned_stop: plannedStop === "" ? null : Number(plannedStop),
      planned_target: plannedTarget === "" ? null : Number(plannedTarget),
    };
    add.mutate(body, {
      onSuccess: reset,
      onError: (e) => setErr(e instanceof ApiError ? e.message : String(e)),
    });
  }

  const inputCls = "rounded border bg-background px-2 py-1 text-sm";
  return (
    <GlassCard className="space-y-2 p-3">
      <div className="text-sm font-medium">记一笔交易</div>
      <div className="flex flex-wrap items-center gap-2">
        <input type="date" value={date} onChange={(e) => setDate(e.target.value)} className={inputCls} />
        <input placeholder="代码" value={code} onChange={(e) => setCode(e.target.value)}
          className={`${inputCls} w-20`} />
        <input placeholder="名称" value={name} onChange={(e) => setName(e.target.value)} className={inputCls} />
        <select value={playbook} onChange={(e) => setPlaybook(e.target.value as Playbook)} className={inputCls}>
          {PLAYBOOKS.map((p) => <option key={p} value={p}>{p}</option>)}
        </select>
        <select value={asPlanned} onChange={(e) => setAsPlanned(e.target.value as "true" | "false" | "")} className={inputCls}>
          <option value="">未标</option>
          <option value="true">按计划</option>
          <option value="false">计划外</option>
        </select>
      </div>
      <div className="flex flex-wrap items-center gap-2">
        <input placeholder="盈亏% (没填成交明细时用)" value={pnlPct} onChange={(e) => setPnlPct(e.target.value)}
          className={`${inputCls} w-44`} />
        <input placeholder="计划止损价" value={plannedStop} onChange={(e) => setPlannedStop(e.target.value)}
          className={`${inputCls} w-28`} />
        <input placeholder="计划目标价" value={plannedTarget} onChange={(e) => setPlannedTarget(e.target.value)}
          className={`${inputCls} w-28`} />
      </div>
      <FillEditor fills={fills} onChange={setFills} />
      <input placeholder="备注" value={note} onChange={(e) => setNote(e.target.value)} className={`${inputCls} w-full`} />
      {err && <div className="text-xs text-red-500">{err}</div>}
      <button
        onClick={submit}
        disabled={add.isPending}
        className="rounded bg-blue-500 px-3 py-1 text-sm text-white disabled:opacity-50"
      >
        {add.isPending ? "记录中…" : "记录"}
      </button>
    </GlassCard>
  );
}

function TradeRow({ trade, onDelete }: {
  trade: { id: string; date: string; code: string; name: string; playbook: string;
    pnl_pct: number | null; as_planned: boolean | null;
    settled: { realized_pnl?: number | null; hold_days?: number; closed?: boolean; open_shares?: number }; };
  onDelete: (id: string) => void;
}) {
  const st = trade.settled || {};
  return (
    <tr className="border-t text-xs">
      <td className="px-2 py-1">{trade.date}</td>
      <td className="px-2 py-1 font-mono">{trade.code}</td>
      <td className="px-2 py-1">{trade.name || "—"}</td>
      <td className="px-2 py-1">{trade.playbook}</td>
      <td className={`px-2 py-1 ${(trade.pnl_pct ?? 0) >= 0 ? "text-emerald-600" : "text-red-500"}`}>
        {pct(trade.pnl_pct)}
      </td>
      <td className="px-2 py-1">
        {trade.as_planned === true ? "按计划" : trade.as_planned === false ? "计划外" : "未标"}
      </td>
      <td className="px-2 py-1">{yuan(st.realized_pnl)}</td>
      <td className="px-2 py-1">{st.hold_days ?? "—"}{st.closed === false && st.open_shares ? " (持)" : ""}</td>
      <td className="px-2 py-1">
        <button onClick={() => onDelete(trade.id)} className="text-red-500 hover:underline">删</button>
      </td>
    </tr>
  );
}

function StatsSummary({ stats, error }: {
  stats: import("@/lib/journal-contract").StatsResponse | undefined;
  error: unknown;
}) {
  if (error) {
    return <div className="text-xs text-red-500">后端未就绪：{error instanceof ApiError ? error.message : String(error)}</div>;
  }
  if (!stats || !stats.available) {
    return <div className="text-xs text-muted-foreground">{stats?.reason || "统计未就绪"}</div>;
  }
  const o = stats.overall;
  const rows = Object.entries(stats.by_playbook);
  return (
    <div className="space-y-2">
      <div className="flex flex-wrap gap-3 text-xs">
        <span>总 {o.count} 笔（已评分 {o.scored}）</span>
        <span>胜率 {o.win_rate != null ? `${(o.win_rate * 100).toFixed(1)}%` : "—"}</span>
        <span>均值 {pct(o.avg)}</span>
        <span>净盈亏 {yuan(o.net_pnl)} 元</span>
      </div>
      <table className="text-xs">
        <thead><tr><th className="px-2 text-left">打法</th><th className="px-2">笔数</th><th className="px-2">胜率</th><th className="px-2">净盈亏</th></tr></thead>
        <tbody>
          {rows.map(([k, v]) => (
            <tr key={k} className="border-t">
              <td className="px-2">{k}</td>
              <td className="px-2 text-center">{v.count}</td>
              <td className="px-2 text-center">{v.win_rate != null ? `${(v.win_rate * 100).toFixed(0)}%` : "—"}</td>
              <td className="px-2 text-center">{yuan(v.net_pnl)}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

export function TradeJournalSection() {
  const { data, isLoading, error } = useJournalTrades(200);
  const { data: stats, error: statsError } = useJournalStats();
  const del = useDeleteTrade();
  const [delErr, setDelErr] = useState<string | null>(null);
  const trades = data?.trades ?? [];

  return (
    <div className="space-y-3">
      <AddTradeForm />
      <GlassCard className="p-3">
        <div className="mb-2 text-sm font-medium">成交列表（{trades.length}{data ? `/${data.total}` : ""}）</div>
        {delErr && <div className="mb-2 text-xs text-red-500">删除失败：{delErr}</div>}
        {error ? (
          <div className="rounded bg-red-500/10 p-2 text-xs text-red-500">
            后端未就绪：{error instanceof ApiError ? error.message : String(error)}
          </div>
        ) : isLoading ? (
          <div className="text-xs text-muted-foreground">加载中…</div>
        ) : trades.length === 0 ? (
          <div className="text-xs text-muted-foreground">还没有交易记录</div>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full">
              <thead>
                <tr className="text-xs text-muted-foreground">
                  <th className="px-2 text-left">日期</th>
                  <th className="px-2 text-left">代码</th>
                  <th className="px-2 text-left">名称</th>
                  <th className="px-2 text-left">打法</th>
                  <th className="px-2 text-left">盈亏</th>
                  <th className="px-2 text-left">计划</th>
                  <th className="px-2 text-left">已实现</th>
                  <th className="px-2 text-left">持有</th>
                  <th className="px-2"></th>
                </tr>
              </thead>
              <tbody>
                {trades.map((t) => (
                  <TradeRow key={t.id} trade={t} onDelete={(id) => {
                    setDelErr(null);
                    del.mutate(id, {
                      onError: (e) => setDelErr(e instanceof ApiError ? e.message : String(e)),
                    });
                  }} />
                ))}
              </tbody>
            </table>
          </div>
        )}
      </GlassCard>
      <GlassCard className="p-3">
        <div className="mb-2 text-sm font-medium">自我体检</div>
        <StatsSummary stats={stats} error={statsError} />
      </GlassCard>
    </div>
  );
}
