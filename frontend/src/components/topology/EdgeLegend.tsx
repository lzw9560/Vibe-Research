// S024-C review #14：graph 模式边色图例。S048 R12：加 hidden/onToggle 变可点击 toggle。
// 仅展示当前数据出现的边类型，颜色/标签取自 edgeColors 单一真源（不重复定义）。
// 无 onToggle 时保持纯展示（兼容他处用法）。客观关联说明，无方向词（§0 弱合规）。
import type { EdgeType, GraphEdge } from "@/lib/api/types";
import { cn } from "@/lib/utils";
import { EDGE_COLORS, EDGE_LABELS } from "./edgeColors";

interface EdgeLegendProps {
  edges: GraphEdge[];
  /** 当前隐藏的边类型（点击图例可切换）。 */
  hidden?: EdgeType[];
  /** 传入即图例项变 button；不传保持纯展示。 */
  onToggle?: (type: EdgeType) => void;
}

/** 固定展示顺序，避免按数据出现顺序乱序。 */
const EDGE_ORDER: EdgeType[] = ["sector", "fund_flow", "ladder", "seat", "flow"];

/** graph 模式边色图例条：按数据出现的边类型生成色块+标签；未出现的不展示。 */
export function EdgeLegend({ edges, hidden, onToggle }: EdgeLegendProps) {
  const present = new Set(edges.map((e) => e.type));
  if (present.size === 0) return null;
  const hiddenSet = new Set(hidden ?? []);
  const items = EDGE_ORDER.filter((t) => present.has(t));
  return (
    <div className="mb-2 flex flex-wrap items-center gap-x-3 gap-y-1 text-[11px] text-muted-foreground/70">
      {items.map((t) => {
        const isHidden = hiddenSet.has(t);
        const swatch = (
          <>
            <span
              className="inline-block h-2 w-2 rounded-full"
              style={{ backgroundColor: EDGE_COLORS[t] }}
              aria-hidden="true"
            />
            {EDGE_LABELS[t]}
          </>
        );
        // S048 R12：无 onToggle 保持纯展示 span；有则可点击 toggle
        return onToggle ? (
          <button
            key={t}
            type="button"
            aria-pressed={!isHidden}
            onClick={() => onToggle(t)}
            className={cn("inline-flex items-center gap-1 transition-opacity", isHidden && "opacity-40")}
          >
            {swatch}
          </button>
        ) : (
          <span key={t} className="inline-flex items-center gap-1">{swatch}</span>
        );
      })}
    </div>
  );
}
