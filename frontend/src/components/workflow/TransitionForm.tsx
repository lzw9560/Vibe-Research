// S033 T11/R7：holding/settled 流转表单——买入价/卖出价 + 战法下拉 + 理由，全部可选填。
// 合规：entry_price/exit_price/strategy 是用户自填操作记录，非系统推荐。
import { useState } from "react";
import { Button } from "@/components/ui/Button";
import { Input } from "@/components/ui/Input";
import { STRATEGY_NAMES } from "./statusMeta";
import type { TransitionRequest } from "@/lib/api";

interface Props {
  code: string;
  date?: string;
  /** holding（显示买入价）或 settled（显示卖出价） */
  target: string;
  onSubmit: (req: TransitionRequest) => void;
  onCancel: () => void;
  submitting?: boolean;
}

/** 空串/非法数字 → undefined（COALESCE：后端不覆盖已有值）。 */
function toOptionalNumber(raw: string): number | undefined {
  if (!raw.trim()) return undefined;
  const n = Number(raw);
  return Number.isFinite(n) ? n : undefined;
}

export function TransitionForm({ code, date, target, onSubmit, onCancel, submitting }: Props) {
  const [entryPrice, setEntryPrice] = useState("");
  const [exitPrice, setExitPrice] = useState("");
  const [strategy, setStrategy] = useState("");
  const [reason, setReason] = useState("");

  const handleSubmit = () => {
    onSubmit({
      code,
      date: date ?? "",
      target,
      reason: reason.trim() || undefined,
      entry_price: target === "holding" ? toOptionalNumber(entryPrice) : undefined,
      exit_price: target === "settled" ? toOptionalNumber(exitPrice) : undefined,
      strategy: strategy || undefined,
    });
  };

  return (
    <div className="mt-2 space-y-2 rounded-lg border border-border/40 bg-muted/20 p-3">
      {target === "holding" && (
        <Input
          label="买入价（可选）"
          placeholder="如 12.50"
          inputMode="decimal"
          value={entryPrice}
          onChange={(e) => setEntryPrice(e.target.value)}
        />
      )}
      {target === "settled" && (
        <Input
          label="卖出价（可选）"
          placeholder="如 13.80"
          inputMode="decimal"
          value={exitPrice}
          onChange={(e) => setExitPrice(e.target.value)}
        />
      )}
      <div>
        <label className="mb-1.5 block text-sm font-medium text-muted-foreground" htmlFor="s033-strategy-select">
          战法（可选）
        </label>
        <select
          id="s033-strategy-select"
          value={strategy}
          onChange={(e) => setStrategy(e.target.value)}
          className="w-full rounded-lg border border-border bg-black/20 px-3 py-2 text-sm outline-none transition-colors focus:border-primary/50"
        >
          <option value="">不指定</option>
          {STRATEGY_NAMES.map((s) => (
            <option key={s} value={s}>{s}</option>
          ))}
        </select>
      </div>
      <Input
        label="理由（可选）"
        placeholder="备注（可选）"
        value={reason}
        onChange={(e) => setReason(e.target.value)}
      />
      <div className="flex gap-2 pt-1">
        <Button size="sm" onClick={handleSubmit} disabled={submitting}>确认流转</Button>
        <Button size="sm" variant="ghost" onClick={onCancel} disabled={submitting}>取消</Button>
      </div>
    </div>
  );
}
