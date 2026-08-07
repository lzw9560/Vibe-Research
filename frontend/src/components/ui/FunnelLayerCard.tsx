import { type ReactNode } from "react";
import { cn } from "@/lib/utils";
import type { FunnelLayer } from "@/lib/candidates";

// S031 R16/R17：漏斗层公共卡片——conditions + passed + filtered_out + 输入→输出计数。
// 候选池页（FunnelLayers，neutral）与盘前简报因子层（FactorSection，info）共用。
// 候选池的 rerun/downstream 经 footer 槽注入；因子层不用 footer。
interface Props {
  layer: FunnelLayer;
  onPick?: (code: string) => void;
  /** conditions chips 色调：因子层 info（权重公式）/ 候选池 neutral（过滤规则） */
  variant?: "info" | "neutral";
  /** 底部操作槽（候选池 rerun/downstream 注入） */
  footer?: ReactNode;
  className?: string;
}

export function FunnelLayerCard({ layer, onPick, variant = "neutral", footer, className }: Props) {
  const missing = layer.data_status === "未取得";
  return (
    <div className={cn("rounded-lg border border-border/40 bg-card/30 p-3", className)}>
      <div className="flex items-center justify-between">
        <div className="font-medium">
          <span className="mr-2 text-xs text-muted-foreground">{layer.layer_id}</span>
          {layer.name}
        </div>
        <div className="text-xs text-muted-foreground">
          输入 <span className="text-foreground">{layer.input_count}</span> → 输出{" "}
          <span className="text-foreground">{layer.output_count}</span>
        </div>
      </div>

      {missing && layer.data_reason && (
        <div className="mt-2 text-sm text-warning">该层数据未取得：{layer.data_reason}</div>
      )}

      {layer.conditions && layer.conditions.length > 0 && (
        <div className="mt-2 flex flex-wrap gap-1">
          {layer.conditions.map((c, i) => (
            <span
              key={i}
              className={cn(
                "rounded px-2 py-0.5 text-xs",
                variant === "info" ? "bg-primary/10 text-primary" : "bg-muted/40",
              )}
            >
              {c}
            </span>
          ))}
        </div>
      )}

      {!missing && layer.passed && layer.passed.length > 0 && (
        <div className="mt-2">
          <div className="mb-1 text-xs text-muted-foreground">通过候选（{layer.passed.length}）</div>
          <div className="space-y-0.5">
            {layer.passed.slice(0, 15).map((c) => (
              <button
                key={c.code}
                type="button"
                onClick={() => onPick?.(c.code)}
                className="flex w-full justify-between rounded px-2 py-1 text-left text-sm hover:bg-muted/50"
              >
                <span>
                  {c.name} <span className="text-xs text-muted-foreground">{c.code}</span>
                </span>
              </button>
            ))}
            {layer.passed.length > 15 && (
              <div className="text-xs text-muted-foreground">…共 {layer.passed.length} 条</div>
            )}
          </div>
        </div>
      )}

      {layer.filtered_out && layer.filtered_out.length > 0 && (
        <div className="mt-2 grid gap-1 text-xs">
          <div className="text-muted-foreground">被过滤（{layer.filtered_out.length}）：</div>
          {layer.filtered_out.slice(0, 10).map((f) => (
            <div key={f.code} className="flex justify-between">
              <span>{f.name ? `${f.name} ${f.code}` : f.code}</span>
              <span className="text-muted-foreground">{f.reason}</span>
            </div>
          ))}
        </div>
      )}

      {footer && (
        <div className="mt-2 flex flex-wrap items-center gap-2 border-t border-border/40 pt-2">
          {footer}
        </div>
      )}
    </div>
  );
}
