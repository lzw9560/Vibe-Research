// S024-C review #14：graph 模式边色图例。
// 仅展示当前数据出现的边类型，颜色/标签取自 edgeColors 单一真源（不重复定义）。
// 客观关联说明，无方向词（§0 弱合规）。
import type { EdgeType, GraphEdge } from "@/lib/api/types";
import { EDGE_COLORS, EDGE_LABELS } from "./edgeColors";

interface EdgeLegendProps {
  edges: GraphEdge[];
}

/** 固定展示顺序，避免按数据出现顺序乱序。 */
const EDGE_ORDER: EdgeType[] = ["sector", "fund_flow", "ladder", "seat", "flow"];

/** graph 模式边色图例条：按数据出现的边类型生成色块+标签；未出现的不展示。 */
export function EdgeLegend({ edges }: EdgeLegendProps) {
  const present = new Set(edges.map((e) => e.type));
  if (present.size === 0) return null;
  const items = EDGE_ORDER.filter((t) => present.has(t));
  return (
    <div className="mb-2 flex flex-wrap items-center gap-x-3 gap-y-1 text-[11px] text-muted-foreground/70">
      {items.map((t) => (
        <span key={t} className="inline-flex items-center gap-1">
          <span
            className="inline-block h-2 w-2 rounded-full"
            style={{ backgroundColor: EDGE_COLORS[t] }}
            aria-hidden="true"
          />
          {EDGE_LABELS[t]}
        </span>
      ))}
    </div>
  );
}
