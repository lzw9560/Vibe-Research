import { useState } from "react";
import { Plus, Trash2, RefreshCw } from "lucide-react";
import { PageHeader } from "@/components/ui/PageHeader";
import { GlassCard } from "@/components/ui/GlassCard";
import { Button } from "@/components/ui/Button";
import { Input } from "@/components/ui/Input";
import { Badge } from "@/components/ui/Badge";
import { Disclaimer } from "@/components/ui/Disclaimer";
import { Skeleton } from "@/components/ui/Skeleton";
import {
  useJournalList, useAddTrade, useDeleteTrade, useAtRisk, useEquityBase, useSetEquityBase,
} from "@/lib/query";
import { PLAYBOOKS, type AddTradeBody } from "@/lib/journal";

const today = () => {
  const d = new Date();
  return `${d.getFullYear()}-${`${d.getMonth() + 1}`.padStart(2, "0")}-${`${d.getDate()}`.padStart(2, "0")}`;
};

const pnlColor = (v: number | null | undefined) =>
  v == null ? "text-muted-foreground" : v > 0 ? "text-danger" : v < 0 ? "text-success" : "text-muted-foreground";

/** S149 P3 交易日志页：与 /portfolio 区分（交易日志=成交时序结算，持仓=快照）。
 * ⛔ 个人交易数据——不接入 AI prompt（后端 P3-T1 闭包锁定；前端只读渲染）。 */
export function Journal() {
  const listQ = useJournalList(200);
  const atRiskQ = useAtRisk({ refetchInterval: 60 * 1000 });
  const equityQ = useEquityBase();
  const addM = useAddTrade();
  const delM = useDeleteTrade();
  const setEquityM = useSetEquityBase();

  // add form state
  const [form, setForm] = useState({
    date: today(), code: "", name: "", playbook: "打板" as string,
    buyPrice: "", buyShares: "", plannedStop: "", note: "",
  });
  const [equityInput, setEquityInput] = useState("");

  const handleAdd = () => {
    const fills = form.buyPrice && form.buyShares
      ? [{ side: "buy" as const, date: form.date, price: Number(form.buyPrice), shares: Number(form.buyShares) }]
      : undefined;
    const body: AddTradeBody = {
      date: form.date, code: form.code, name: form.name, playbook: form.playbook,
      fills, planned_stop: form.plannedStop ? Number(form.plannedStop) : null, note: form.note,
    };
    addM.mutate(body, {
      onSuccess: () => setForm({ ...form, code: "", name: "", buyPrice: "", buyShares: "", plannedStop: "", note: "" }),
    });
  };

  const trades = listQ.data?.trades ?? [];
  const atRisk = atRiskQ.data as { available?: boolean; total_at_risk?: number; position_count?: number; unbounded_count?: number; unbounded_note?: string; at_risk_of_equity_pct?: number | null; reason?: string } | undefined;

  return (
    <div className="space-y-4">
      <PageHeader title="交易日志" subtitle="成交时序结算 · 在险资金 · 自我复盘" />

      {/* 在险资金概览 */}
      <GlassCard className="p-4">
        <div className="flex items-center justify-between mb-2">
          <h3 className="text-sm font-medium text-foreground">在险资金</h3>
          {equityQ.data && (
            <span className="text-xs text-foreground/50">
              账户规模：{equityQ.data.equity_base ? `${equityQ.data.equity_base.toLocaleString()} 元` : "未填"}
            </span>
          )}
        </div>
        {atRisk?.available ? (
          <div className="grid grid-cols-3 gap-3 text-sm">
            <div><p className="text-xs text-foreground/50">在场持仓</p><p className="font-medium">{atRisk.position_count} 笔</p></div>
            <div><p className="text-xs text-foreground/50">合计在险</p><p className="font-medium text-danger">{(atRisk.total_at_risk ?? 0).toLocaleString()} 元</p></div>
            <div><p className="text-xs text-foreground/50">占账户</p><p className="font-medium">{atRisk.at_risk_of_equity_pct != null ? `${atRisk.at_risk_of_equity_pct}%` : "—"}</p></div>
          </div>
        ) : (
          <p className="text-xs text-foreground/40">{atRisk?.reason ?? "暂无未平仓持仓"}</p>
        )}
        {atRisk?.unbounded_note && (
          <p className="text-[10px] text-amber-400 mt-2">⚠️ {atRisk.unbounded_note.replace(/\*\*/g, "")}</p>
        )}
        {/* 账户规模设置 */}
        <div className="mt-3 pt-3 border-t border-border flex gap-2 items-center">
          <Input value={equityInput} onChange={(e) => setEquityInput(e.target.value)}
                 placeholder="设置账户规模（元）" className="h-8 text-xs" type="number" />
          <Button size="sm" className="h-8"
                  disabled={!equityInput || setEquityM.isPending}
                  onClick={() => equityInput && setEquityM.mutate(Number(equityInput))}>
            {setEquityM.isPending ? "保存中…" : "保存"}
          </Button>
        </div>
      </GlassCard>

      {/* 记录一笔 */}
      <GlassCard className="p-4">
        <h3 className="text-sm font-medium text-foreground mb-3">记录一笔交易</h3>
        <div className="grid grid-cols-2 md:grid-cols-4 gap-2">
          <Input value={form.date} onChange={(e) => setForm({ ...form, date: e.target.value })} placeholder="日期 YYYY-MM-DD" className="h-8 text-xs" />
          <Input value={form.code} onChange={(e) => setForm({ ...form, code: e.target.value })} placeholder="代码 6 位" className="h-8 text-xs" />
          <Input value={form.name} onChange={(e) => setForm({ ...form, name: e.target.value })} placeholder="名称" className="h-8 text-xs" />
          <select value={form.playbook} onChange={(e) => setForm({ ...form, playbook: e.target.value })}
                  className="h-8 text-xs rounded bg-foreground/5 border border-border px-2">
            {PLAYBOOKS.map((p) => <option key={p} value={p}>{p}</option>)}
          </select>
          <Input value={form.buyPrice} onChange={(e) => setForm({ ...form, buyPrice: e.target.value })} placeholder="买入价" type="number" className="h-8 text-xs" />
          <Input value={form.buyShares} onChange={(e) => setForm({ ...form, buyShares: e.target.value })} placeholder="买入股数" type="number" className="h-8 text-xs" />
          <Input value={form.plannedStop} onChange={(e) => setForm({ ...form, plannedStop: e.target.value })} placeholder="计划止损价" type="number" className="h-8 text-xs" />
          <Input value={form.note} onChange={(e) => setForm({ ...form, note: e.target.value })} placeholder="备注" className="h-8 text-xs" />
        </div>
        <div className="mt-2 flex items-center gap-2">
          <Button size="sm" onClick={handleAdd} disabled={addM.isPending || !form.code}>
            <Plus className="h-3.5 w-3.5 mr-1" /> {addM.isPending ? "记录中…" : "记录"}
          </Button>
          {addM.isError && <span className="text-xs text-red-400">失败：{(addM.error as Error).message}</span>}
        </div>
      </GlassCard>

      {/* 交易列表 */}
      <GlassCard className="p-4">
        <div className="flex items-center justify-between mb-3">
          <h3 className="text-sm font-medium text-foreground">交易记录（{listQ.data?.total ?? 0}）</h3>
          <Button variant="ghost" size="sm" onClick={() => listQ.refetch()} className="h-7">
            <RefreshCw className={`h-3 w-3 ${listQ.isFetching ? "animate-spin" : ""}`} />
          </Button>
        </div>
        {listQ.isLoading ? (
          <Skeleton className="h-40 w-full" />
        ) : trades.length === 0 ? (
          <p className="text-xs text-foreground/40">还没有交易记录</p>
        ) : (
          <div className="space-y-1.5">
            {trades.map((t) => (
              <div key={t.id} className="flex items-center justify-between p-2 rounded bg-foreground/5 text-xs">
                <div className="flex items-center gap-2 flex-wrap">
                  <span className="text-foreground/50 tabular-nums">{t.date}</span>
                  <span className="text-foreground">{t.code} {t.name}</span>
                  <Badge variant="default" className="text-[9px]">{t.playbook}</Badge>
                  {t.settled?.closed && <Badge variant="success" className="text-[9px]">已平仓</Badge>}
                  {t.stock?.in_limit_up && <Badge variant="warning" className="text-[9px]">{t.stock.boards ?? 1}板</Badge>}
                </div>
                <div className="flex items-center gap-2">
                  <span className={`tabular-nums font-medium ${pnlColor(t.pnl_pct)}`}>
                    {t.pnl_pct != null ? `${t.pnl_pct > 0 ? "+" : ""}${t.pnl_pct}%` : "—"}
                  </span>
                  <button onClick={() => delM.mutate(t.id)} className="text-foreground/40 hover:text-red-400">
                    <Trash2 className="h-3.5 w-3.5" />
                  </button>
                </div>
              </div>
            ))}
          </div>
        )}
      </GlassCard>

      <Disclaimer compact />
    </div>
  );
}
