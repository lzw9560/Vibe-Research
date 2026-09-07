// S166: 交易日志设置——风险宪法 + 费率 + 账户规模编辑器。fresh-impl。
// 读 GET /api/risk/rules + /api/journal/fees + /api/risk/equity-base；
// 写 POST /api/risk/rules + /api/journal/fees + /api/risk/equity-base。
// 不臆造：is_default 标是否初值（用户未改过）；改费率/规则前可见当前值。
import { useEffect, useState } from "react";
import { GlassCard } from "@/components/ui/GlassCard";
import { ApiError } from "@/lib/api";
import {
  useRiskRules, useSaveRules, useJournalFees, useSaveFees,
  useEquityBase, useSaveEquityBase,
} from "@/lib/query";
import type { RiskRules, Fees, SaveRulesInput, SaveFeesInput } from "@/lib/journal-contract";

const inputCls = "rounded border bg-background px-2 py-1 text-sm";

function RulesEditor() {
  const { data, isLoading, error } = useRiskRules();
  const save = useSaveRules();
  const [v, setV] = useState<RiskRules | null>(null);
  useEffect(() => { if (data) setV(data); }, [data]);
  if (error) return <div className="text-xs text-red-500">后端未就绪：{(error as Error).message}</div>;
  if (isLoading || !v) return <div className="text-xs text-muted-foreground">加载中…</div>;
  const set = (k: keyof SaveRulesInput, val: string) =>
    setV({ ...v, [k]: val === "" ? 0 : Number(val) });
  const fields: { key: keyof SaveRulesInput; label: string }[] = [
    { key: "max_loss_per_trade_pct", label: "单笔最大亏损 %" },
    { key: "max_loss_per_day_pct", label: "单日最大亏损 %" },
    { key: "max_positions", label: "最多同时持仓" },
    { key: "max_trades_per_day", label: "单日最多开仓" },
    { key: "pause_after_losses", label: "连亏几笔后停手" },
    { key: "max_unplanned_ratio", label: "计划外占比上限" },
  ];
  return (
    <div className="space-y-2">
      {v.is_default && (
        <div className="rounded bg-amber-500/10 p-2 text-xs text-amber-600">
          ⚠️ 还在用初值——按你自己的习惯改一遍（不同资金量/打法合理阈值差得远，初值非推荐值）
        </div>
      )}
      <div className="grid grid-cols-2 gap-2">
        {fields.map((f) => (
          <label key={f.key} className="text-xs">
            {f.label}
            <input
              type="number"
              value={(v as unknown as Record<string, number>)[f.key as string] ?? 0}
              onChange={(e) => set(f.key, e.target.value)}
              className={inputCls}
            />
          </label>
        ))}
      </div>
      <button
        onClick={() => save.mutate(v as SaveRulesInput, {
          onError: (e) => alert(e instanceof ApiError ? e.message : String(e)),
        })}
        disabled={save.isPending}
        className="rounded bg-blue-500 px-3 py-1 text-sm text-white disabled:opacity-50"
      >
        {save.isPending ? "保存中…" : "保存规则"}
      </button>
    </div>
  );
}

function FeesEditor() {
  const { data, isLoading, error } = useJournalFees();
  const save = useSaveFees();
  const [v, setV] = useState<Fees | null>(null);
  useEffect(() => { if (data) setV(data); }, [data]);
  if (error) return <div className="text-xs text-red-500">后端未就绪：{(error as Error).message}</div>;
  if (isLoading || !v) return <div className="text-xs text-muted-foreground">加载中…</div>;
  const set = (k: keyof SaveFeesInput, val: string) =>
    setV({ ...v, [k]: val === "" ? 0 : Number(val) });
  const fields: { key: keyof SaveFeesInput; label: string }[] = [
    { key: "commission_rate", label: "佣金费率（双向，万2.5=0.00025）" },
    { key: "commission_min", label: "单笔佣金最低（元）" },
    { key: "stamp_tax_rate", label: "印花税（仅卖出）" },
    { key: "transfer_fee_rate", label: "过户费（双向）" },
  ];
  return (
    <div className="space-y-2">
      {v.is_default && (
        <div className="rounded bg-amber-500/10 p-2 text-xs text-amber-600">
          ⚠️ 还在用初值——按你账户实际费率改（初值非真实费率）
        </div>
      )}
      <div className="grid grid-cols-2 gap-2">
        {fields.map((f) => (
          <label key={f.key} className="text-xs">
            {f.label}
            <input
              type="number"
              value={(v as unknown as Record<string, number>)[f.key as string] ?? 0}
              onChange={(e) => set(f.key, e.target.value)}
              className={inputCls}
            />
          </label>
        ))}
      </div>
      <button
        onClick={() => save.mutate(v as SaveFeesInput, {
          onError: (e) => alert(e instanceof ApiError ? e.message : String(e)),
        })}
        disabled={save.isPending}
        className="rounded bg-blue-500 px-3 py-1 text-sm text-white disabled:opacity-50"
      >
        {save.isPending ? "保存中…" : "保存费率"}
      </button>
    </div>
  );
}

function EquityBaseEditor() {
  const { data, isLoading, error } = useEquityBase();
  const save = useSaveEquityBase();
  const [val, setVal] = useState("");
  useEffect(() => { if (data) setVal(data.equity_base?.toString() ?? ""); }, [data]);
  if (error) return <div className="text-xs text-red-500">后端未就绪：{(error as Error).message}</div>;
  if (isLoading) return <div className="text-xs text-muted-foreground">加载中…</div>;
  return (
    <div className="space-y-2">
      <div className="text-xs text-muted-foreground">
        账户规模（占比的分母；没填就只给绝对金额不给占比。⚠️ 绝不用历史最大投入代替——会把占比算小）
      </div>
      <div className="flex items-center gap-2">
        <input type="number" value={val} onChange={(e) => setVal(e.target.value)} className={inputCls} placeholder="账户本金（元）" />
        <button
          onClick={() => save.mutate({ base: Number(val) }, {
            onError: (e) => alert(e instanceof ApiError ? e.message : String(e)),
          })}
          disabled={save.isPending || !val}
          className="rounded bg-blue-500 px-3 py-1 text-sm text-white disabled:opacity-50"
        >
          {save.isPending ? "保存中…" : "保存"}
        </button>
      </div>
    </div>
  );
}

export function JournalSettings() {
  return (
    <div className="space-y-3">
      <GlassCard className="space-y-2 p-3">
        <div className="text-sm font-medium">风险宪法</div>
        <RulesEditor />
      </GlassCard>
      <GlassCard className="space-y-2 p-3">
        <div className="text-sm font-medium">交易费率</div>
        <FeesEditor />
      </GlassCard>
      <GlassCard className="space-y-2 p-3">
        <div className="text-sm font-medium">账户规模</div>
        <EquityBaseEditor />
      </GlassCard>
    </div>
  );
}
