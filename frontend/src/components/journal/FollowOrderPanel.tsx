// S175 R14/R15 — 跟单 flow（FollowDecisionModal + FollowOrderGap）。
// 系统不碰用户真钱：FollowDecisionModal 只记录用户自报成交价 → POST /api/journal/follow-order
// → 系统算 paper-vs-real gap → FollowOrderGap 显 4 源分解（dormant 标激活条件不可达）。
import { useState } from "react";
import { authHeaders, ApiError } from "@/lib/api";
import type { FollowOrderResponse } from "@/lib/journal-contract";

interface FollowOrderButtonProps {
  signal_id: string;
}

export function FollowOrderButton({ signal_id }: FollowOrderButtonProps) {
  const [open, setOpen] = useState(false);
  const [result, setResult] = useState<FollowOrderResponse | null>(null);

  return (
    <>
      <button
        onClick={() => setOpen(true)}
        className="rounded bg-primary/90 px-2 py-1 text-xs text-primary-foreground hover:bg-primary"
      >
        跟单（真盘你执行）
      </button>
      {open && (
        <FollowDecisionModal
          signal_id={signal_id}
          onClose={() => setOpen(false)}
          onResult={(r) => { setResult(r); setOpen(false); }}
        />
      )}
      {result && <FollowOrderGap data={result} />}
    </>
  );
}

interface FollowDecisionModalProps {
  signal_id: string;
  onClose: () => void;
  onResult: (r: FollowOrderResponse) => void;
}

function FollowDecisionModal({ signal_id, onClose, onResult }: FollowDecisionModalProps) {
  const [realEntry, setRealEntry] = useState("");
  const [realExit, setRealExit] = useState("");
  const [realShares, setRealShares] = useState("100");
  const [realCostPct, setRealCostPct] = useState("0.70");
  const [error, setError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);

  const submit = async () => {
    setSubmitting(true);
    setError(null);
    try {
      const entry = parseFloat(realEntry);
      if (!entry || entry <= 0) throw new Error("买入价须 > 0");
      const resp = await fetch("/api/journal/follow-order", {
        method: "POST",
        headers: { ...authHeaders(), "Content-Type": "application/json" },
        body: JSON.stringify({
          signal_id,
          real_entry_price: entry,
          real_exit_price: realExit ? parseFloat(realExit) : null,
          real_shares: parseFloat(realShares) || 100,
          real_cost_pct: realCostPct ? parseFloat(realCostPct) : null,
        }),
      });
      if (!resp.ok) throw new ApiError(`跟单失败 HTTP ${resp.status}`, resp.status);
      onResult(await resp.json() as FollowOrderResponse);
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/50">
      <div className="w-96 rounded-lg border bg-background p-4">
        <h3 className="text-sm font-semibold">你来定 — 跟单（真盘你执行）</h3>
        <div className="my-2 rounded border border-amber-300/60 bg-amber-50/80 p-2 text-[10px] leading-relaxed text-amber-800">
          <b>纸面 ≠ 真盘：</b>系统模拟 PnL 不等于真盘可执行。真盘交易由你决策执行，
          系统只记录你自报成交价算 gap（不碰你的真钱）。
        </div>
        <div className="space-y-2 text-xs">
          <input value={realEntry} onChange={(e) => setRealEntry(e.target.value)}
            placeholder="实际买入价" className="w-full rounded border px-2 py-1" />
          <input value={realExit} onChange={(e) => setRealExit(e.target.value)}
            placeholder="实际卖出价（可空，填了算 gap）" className="w-full rounded border px-2 py-1" />
          <input value={realShares} onChange={(e) => setRealShares(e.target.value)}
            placeholder="股数" className="w-full rounded border px-2 py-1" />
          <input value={realCostPct} onChange={(e) => setRealCostPct(e.target.value)}
            placeholder="成本占比%（佣金+印花+滑点 / 本金 ×100）" className="w-full rounded border px-2 py-1" />
          <div className="text-[10px] text-muted-foreground">
            成本计算器：(佣金率×本金 + 印花0.05% + 滑点) / 本金 ×100 = 成本占比%。
            没免五小单成本占比更高（5元最低佣金吃净）。
          </div>
        </div>
        {error && <div className="mt-2 text-xs text-red-500">{error}</div>}
        <div className="mt-3 flex gap-2">
          <button onClick={submit} disabled={submitting}
            className="rounded bg-primary px-3 py-1 text-xs text-primary-foreground hover:bg-primary/90 disabled:opacity-60">
            {submitting ? "提交中…" : "确认跟单"}
          </button>
          <button onClick={onClose}
            className="rounded border px-3 py-1 text-xs hover:bg-muted">取消</button>
        </div>
      </div>
    </div>
  );
}

function FollowOrderGap({ data }: { data: FollowOrderResponse }) {
  const b = data.gap_breakdown;
  if (b.dormant) {
    return (
      <div className="mt-2 rounded bg-gray-100 p-2 text-[10px] leading-relaxed text-muted-foreground">
        <b>4 源 gap dormant：</b>{b.dormant_reason}
      </div>
    );
  }
  return (
    <div className="mt-2 rounded border p-2 text-xs">
      <div className="font-medium">跟单 gap：{data.gap != null ? `${data.gap.toFixed(2)} CNY` : "—"}</div>
      <div className="text-[10px] text-muted-foreground">
        纸面 {data.paper_pnl != null ? data.paper_pnl.toFixed(2) : "—"} / 真盘 {data.real_pnl != null ? data.real_pnl.toFixed(2) : "—"}
      </div>
      <div className="mt-1 grid grid-cols-2 gap-1 text-[10px] text-muted-foreground">
        <span>滑点 gap: {b.slippage != null ? b.slippage.toFixed(2) : "—"}</span>
        <span>成本 gap: {b.cost != null ? b.cost.toFixed(2) : "—"}</span>
        <span>unbuyable: {b.unbuyable ?? "—"}</span>
        <span>T+1: {b.t1 ?? "—"}</span>
      </div>
    </div>
  );
}
