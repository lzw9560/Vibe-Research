// S024-C 漏斗流程拓扑：复用 S023 funnel/layers，构树形 GraphData（节点=漏斗层，
// 边=数据流向 R1→R2→R3→SELF），GraphView tree 布局渲染，节点点击展开该层 passed 候选。
// 复用 ui 组件（GlassCard/SectionHeader/State/Badge）。仿 RelationGraph 数据接线 + KLineChart 模式。
// 合规 §0（弱合规·工程底线）：拓扑只呈现客观数据流向与候选事实，不输出方向结论词。
import { useMemo, useState } from "react";
import { Filter } from "lucide-react";
import { useFunnelLayers } from "@/lib/query";
import type { FunnelLayer } from "@/lib/api";
import { GlassCard } from "@/components/ui/GlassCard";
import { SectionHeader } from "@/components/ui/SectionHeader";
import { LoadingState, ErrorState } from "@/components/ui/State";
import { Badge } from "@/components/ui/Badge";
import { GraphView } from "./GraphView";
import type { GraphData, GraphNode } from "./types";

interface FunnelFlowProps {
  /** ISO 日期；默认今日（后端处理）。 */
  date?: string;
  /** 图高；默认与 GraphView 一致（420）。 */
  height?: number;
}

/** 单层漏斗节点名：层 ID + 层名 + 入/出计数 + 采集状态（客观呈现，不臆造）。 */
function layerNodeName(layer: FunnelLayer): string {
  const base = `${layer.layer_id} · ${layer.name}（入 ${layer.input_count} / 出 ${layer.output_count}）`;
  if (layer.data_status === "未取得") {
    return `${base} · 未取得`;
  }
  return base;
}

/**
 * 纯函数：FunnelLayer[] → 树形 GraphData（C1）。
 * - 节点：每层一节点，id=layer_id，name 含入/出计数，value=output_count。
 * - 边：连续层串联（layer[i]→layer[i+1]），type=flow（数据流向，非方向结论）。
 * 无入边的首层成为 tree 根（GraphView.buildTree 负责）。
 */
export function buildFunnelGraph(layers: FunnelLayer[]): GraphData {
  const nodes: GraphData["nodes"] = layers.map((layer) => ({
    id: layer.layer_id,
    name: layerNodeName(layer),
    category: "funnel",
    value: layer.output_count,
  }));

  const edges: GraphData["edges"] = [];
  for (let i = 0; i < layers.length - 1; i += 1) {
    edges.push({
      source: layers[i].layer_id,
      target: layers[i + 1].layer_id,
      type: "flow",
      weight: 1,
    });
  }

  return { nodes, edges };
}

/** 展开面板：呈现该层筛选条件（可复现依据）+ passed 候选列表（code/name 客观事实）。 */
function PassedCandidatesPanel({ layer }: { layer: FunnelLayer }) {
  const passed = layer.passed ?? [];
  return (
    <div
      data-testid="ff-passed-panel"
      className="mt-3 border-t border-border/40 pt-3"
    >
      <div className="mb-2 flex items-center gap-2">
        <span className="text-sm font-semibold text-foreground">
          {layer.layer_id} · {layer.name}
        </span>
        <Badge variant="info">
          通过 {passed.length}
        </Badge>
        {layer.data_status === "未取得" && (
          <Badge variant="warning">采集失败</Badge>
        )}
      </div>

      {layer.conditions && layer.conditions.length > 0 && (
        <div className="mb-2 flex flex-wrap gap-1.5">
          {layer.conditions.map((c, i) => (
            <Badge key={i} variant="default">
              {c}
            </Badge>
          ))}
        </div>
      )}

      {passed.length === 0 ? (
        <p className="text-xs text-muted-foreground/60">
          该层无通过候选
        </p>
      ) : (
        <ul className="flex flex-col gap-1">
          {passed.map((c) => (
            <li
              key={c.code}
              className="flex items-center gap-2 text-xs font-mono"
            >
              <span className="text-muted-foreground">{c.code}</span>
              <span>{c.name}</span>
            </li>
          ))}
        </ul>
      )}

      {layer.data_reason && (
        <p className="mt-2 text-[11px] text-muted-foreground/50">
          {layer.data_reason}
        </p>
      )}
    </div>
  );
}

/**
 * 漏斗流程容器：复用 S023 funnel/layers 数据，构树形 GraphData 喂 GraphView（tree 布局）。
 * - 调 useFunnelLayers(date) 取 FunnelLayer[]
 * - buildFunnelGraph → tree GraphData（R1→R2→R3→SELF 数据流向）
 * - 节点点击 → toggle 展开该层 passed 候选 + conditions
 * 数据接线/三态由本组件承担；图渲染/边着色由 GraphView 承担。
 */
export function FunnelFlow({ date, height = 420 }: FunnelFlowProps) {
  const { data: layers, isLoading, error, refetch } = useFunnelLayers(date);
  const [expandedLayerId, setExpandedLayerId] = useState<string | null>(null);

  const graphData = useMemo(
    () => buildFunnelGraph(layers ?? []),
    [layers],
  );
  const expandedLayer = layers?.find((l) => l.layer_id === expandedLayerId);

  const handleNodeClick = (node: GraphNode) => {
    setExpandedLayerId((prev) => (prev === node.id ? null : node.id));
  };

  return (
    <GlassCard>
      <SectionHeader
        title="漏斗流程"
        icon={<Filter className="h-4 w-4" aria-hidden="true" />}
        subtitle="漏斗层数据流向（R1→R2→R3→自选），点节点展开通过候选"
      />
      {isLoading ? (
        <LoadingState variant="inline" label="加载漏斗层…" />
      ) : error ? (
        <ErrorState
          message="漏斗层加载失败"
          onRetry={refetch ? () => refetch() : undefined}
        />
      ) : (
        <>
          <GraphView
            data={graphData}
            layout="tree"
            onNodeClick={handleNodeClick}
            height={height}
          />
          {expandedLayer && <PassedCandidatesPanel layer={expandedLayer} />}
        </>
      )}
    </GlassCard>
  );
}
