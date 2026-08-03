// S025-C RecordsForm：受控表单 → useWinRateRecords().mutateAsync。
// 必填：stock_code/entry_date/exit_date；其余可选（stock_name/strategy_used/
// entry_price/exit_price/return_pct/is_win/gene_score/sti_label/sector）。
// 成功 → toast + 清空（invalidate 由 hook onSuccess 统一失效 winrate 前缀）；
// 失败(reject) 或 部分失败(error_count>0) → 保留输入 + toast.error 展示 added_count/errors。
import { useState, type FormEvent } from "react";
import { useWinRateRecords } from "@/lib/query";
import { Input } from "@/components/ui/Input";
import { Button } from "@/components/ui/Button";
import { toast } from "sonner";
import type { WinRateRecordInput, WinRateRecordsResponse } from "@/lib/api";

interface RecordsFormProps {
  onSubmitted?: () => void;
}

// 表单态：数值/布尔字段先以字符串/布尔暂存，提交时再 parse，保证受控输入不报 NaN。
interface FormState {
  stock_code: string;
  stock_name: string;
  strategy_used: string;
  entry_date: string;
  entry_price: string;
  exit_date: string;
  exit_price: string;
  return_pct: string;
  is_win: boolean;
  gene_score: string;
  sti_label: string;
  sector: string;
}

const EMPTY_FORM: FormState = {
  stock_code: "",
  stock_name: "",
  strategy_used: "",
  entry_date: "",
  entry_price: "",
  exit_date: "",
  exit_price: "",
  return_pct: "",
  is_win: false,
  gene_score: "",
  sti_label: "",
  sector: "",
};

const REQUIRED: { key: "stock_code" | "entry_date" | "exit_date"; label: string }[] = [
  { key: "stock_code", label: "股票代码" },
  { key: "entry_date", label: "买入日期" },
  { key: "exit_date", label: "卖出日期" },
];

// 空串/非数 → undefined（可选数值字段不传）。
function toNumber(v: string): number | undefined {
  if (v.trim() === "") return undefined;
  const n = Number(v);
  return Number.isNaN(n) ? undefined : n;
}

function getErrorMessage(err: unknown): string {
  if (err instanceof Error) return err.message;
  return "录入失败，请重试";
}

export function RecordsForm({ onSubmitted }: RecordsFormProps) {
  const [form, setForm] = useState<FormState>({ ...EMPTY_FORM });
  const [errors, setErrors] = useState<Record<string, string>>({});
  const { mutateAsync, isPending } = useWinRateRecords();

  const update = <K extends keyof FormState>(field: K, value: FormState[K]) => {
    setForm((prev) => ({ ...prev, [field]: value }));
    // 编辑即清该字段错误（不可变）
    setErrors((prev) => {
      if (!prev[field]) return prev;
      const next = { ...prev };
      delete next[field];
      return next;
    });
  };

  const validate = (): boolean => {
    const next: Record<string, string> = {};
    for (const f of REQUIRED) {
      if (form[f.key].trim() === "") next[f.key] = `${f.label}必填`;
    }
    setErrors(next);
    return Object.keys(next).length === 0;
  };

  // 构造单条录入：可选字段空则 undefined（不传），避免后端误判空串。
  const buildRecord = (): WinRateRecordInput => ({
    stock_code: form.stock_code.trim(),
    stock_name: form.stock_name.trim() || undefined,
    strategy_used: form.strategy_used.trim() || undefined,
    entry_date: form.entry_date,
    entry_price: toNumber(form.entry_price),
    exit_date: form.exit_date,
    exit_price: toNumber(form.exit_price),
    return_pct: toNumber(form.return_pct),
    is_win: form.is_win ? true : undefined,
    gene_score: toNumber(form.gene_score),
    sti_label: form.sti_label.trim() || undefined,
    sector: form.sector.trim() || undefined,
  });

  const handleSubmit = async (e: FormEvent) => {
    e.preventDefault();
    if (!validate()) return;
    try {
      const res: WinRateRecordsResponse = await mutateAsync([buildRecord()]);
      // 部分失败：后端返 error_count>0，保留输入并提示 added_count/errors 详情。
      if (res.error_count > 0) {
        const detail = res.errors.map((x) => x.error).join("; ");
        toast.error(`录入 ${res.added_count} 条成功，${res.error_count} 条失败`, {
          description: detail,
        });
        return;
      }
      toast.success(`已录入 ${res.added_count} 条记录`);
      setForm({ ...EMPTY_FORM });
      setErrors({});
      onSubmitted?.();
    } catch (err) {
      // 网络或其他异常：保留输入，toast 提示错误信息。
      toast.error(getErrorMessage(err));
    }
  };

  return (
    <section className="space-y-3 rounded-lg border border-border/50 p-4">
      <h3 className="text-sm font-semibold text-foreground">记入胜率</h3>
      <form onSubmit={handleSubmit} className="grid grid-cols-2 gap-3 sm:grid-cols-3">
        <Input
          label="股票代码"
          error={errors.stock_code}
          value={form.stock_code}
          onChange={(e) => update("stock_code", e.target.value)}
          placeholder="000001"
        />
        <Input
          label="股票名称"
          value={form.stock_name}
          onChange={(e) => update("stock_name", e.target.value)}
        />
        <Input
          label="使用战法"
          value={form.strategy_used}
          onChange={(e) => update("strategy_used", e.target.value)}
          placeholder="打板"
        />
        <Input
          label="买入日期"
          type="date"
          error={errors.entry_date}
          value={form.entry_date}
          onChange={(e) => update("entry_date", e.target.value)}
        />
        <Input
          label="卖出日期"
          type="date"
          error={errors.exit_date}
          value={form.exit_date}
          onChange={(e) => update("exit_date", e.target.value)}
        />
        <Input
          label="买入价"
          type="number"
          value={form.entry_price}
          onChange={(e) => update("entry_price", e.target.value)}
          placeholder="0.00"
        />
        <Input
          label="卖出价"
          type="number"
          value={form.exit_price}
          onChange={(e) => update("exit_price", e.target.value)}
          placeholder="0.00"
        />
        <Input
          label="收益率(%)"
          type="number"
          value={form.return_pct}
          onChange={(e) => update("return_pct", e.target.value)}
          placeholder="1.5"
        />
        <Input
          label="基因分"
          type="number"
          value={form.gene_score}
          onChange={(e) => update("gene_score", e.target.value)}
          placeholder="0.80"
        />
        <Input
          label="STI标签"
          value={form.sti_label}
          onChange={(e) => update("sti_label", e.target.value)}
        />
        <Input
          label="板块"
          value={form.sector}
          onChange={(e) => update("sector", e.target.value)}
          placeholder="银行"
        />
        <label className="flex items-end gap-2 pb-2 text-sm text-muted-foreground">
          <input
            type="checkbox"
            className="h-4 w-4 rounded border-border"
            checked={form.is_win}
            onChange={(e) => update("is_win", e.target.checked)}
          />
          是否盈利
        </label>
        <div className="col-span-full flex justify-end">
          <Button type="submit" size="sm" disabled={isPending}>
            {isPending ? "提交中…" : "提交"}
          </Button>
        </div>
      </form>
    </section>
  );
}
