// S151 R4/S9：维度验证徽标——色码红/琥珀/绿/灰 + Tooltip + compact/full 双模式。
// 被 HonestyBanner/FunnelLayerCard/SelectionPipeline 三处 import。
import type { DimensionValidation } from "@/lib/candidates";
import { cn } from "@/lib/utils";

const STATUS_COLOR = {
  red: { dot: "bg-red-500", pill: "bg-red-500/10 text-red-500" },
  amber: { dot: "bg-amber-500", pill: "bg-amber-500/10 text-amber-500" },
  green: { dot: "bg-emerald-500", pill: "bg-emerald-500/10 text-emerald-500" },
  gray: { dot: "bg-gray-400", pill: "bg-gray-400/10 text-gray-400" },
} as const;

function colorOf(v: DimensionValidation) {
  // 判定用 weight_multiplier（更稳）：<1→红(0.1)/琥珀(0.5)；==1→看 status 探索→灰，否则绿
  if (v.weight_multiplier < 0.5) return "red" as const;
  if (v.weight_multiplier < 1) return "amber" as const;
  return v.status.includes("探索") || v.status.includes("待复验") ? "gray" as const : "green" as const;
}

function tooltipText(v: DimensionValidation) {
  return `${v.label}：lift ${v.lift != null ? v.lift.toFixed(3) : "—"}（n=${v.n}）\n状态：${v.status} · 权重 ×${v.weight_multiplier}\n${v.note}`;
}

export function DimensionValidationBadge({
  validation,
  compact = false,
  className,
}: {
  validation?: DimensionValidation | null;
  compact?: boolean;
  className?: string;
}) {
  if (!validation) return null;  // 优雅降级
  const c = STATUS_COLOR[colorOf(validation)];
  const title = tooltipText(validation);
  if (compact) {
    // compact（LayerStep 折叠态）：色点 + ×weight，font text-[10px]
    return (
      <span
        className={cn("inline-flex items-center gap-0.5 text-[10px]", c.pill, className)}
        title={title}
      >
        <span className={cn("h-1.5 w-1.5 rounded-full", c.dot)} />
        ×{validation.weight_multiplier}
      </span>
    );
  }
  // full（HonestyBanner/FunnelLayerCard header）：色点 + label + ×weight，font text-xs
  return (
    <span
      className={cn("inline-flex items-center gap-1 text-xs", c.pill, className)}
      title={title}
    >
      <span className={cn("h-2 w-2 rounded-full", c.dot)} />
      {validation.label} ×{validation.weight_multiplier}
    </span>
  );
}
