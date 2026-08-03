// S024-D2 连板梯队树：调 useBoardLadder 取后端嵌套树（em_zt_topic_pool 涨停池），
// buildLadderGraph 展平为 GraphData（parent→child, type=ladder）喂 GraphView（tree 布局）。
// 树形：根=当日涨停 → 连板高度分层（N板）→ 同题材归枝 → 叶=个股（code/name 如实呈现）。
// 复用 ui 组件（GlassCard/SectionHeader/State）。仿 FunnelFlow 数据接线 + GraphView tree 模式。
// 合规 §0（弱合规·工程底线）：拓扑只呈现客观梯队关联，不输出方向词。
import { useMemo } from "react";
import { Layers } from "lucide-react";
import { useBoardLadder } from "@/lib/query";
import type { BoardLadderNode } from "@/lib/api";
import { GlassCard } from "@/components/ui/GlassCard";
import { SectionHeader } from "@/components/ui/SectionHeader";
import { LoadingState, ErrorState } from "@/components/ui/State";
import { GraphView } from "./GraphView";
import type { GraphData } from "./types";

/** 层级标签（按递归深度）：用于节点 category 元数据（tree 布局不渲染，仅标注客观层级）。 */
const CATEGORY_BY_DEPTH = ["root", "height", "industry", "stock"] as const;

/**
 * 纯函数：嵌套梯队树 → 扁平 GraphData（D2 核心）。
 * - 节点：树中每个节点展平为一 GraphNode，id 为路径（root/index…）保证唯一；
 *   叶节点保留 code/value（后端拼好「code name」存于 name，如实透传）。
 * - 边：parent→child，type=ladder（梯队客观关联，非方向结论），weight=1。
 * 无入边的根（当日涨停）由 GraphView.buildTree 取为 tree 根。
 */
export function buildLadderGraph(tree: BoardLadderNode): GraphData {
  const nodes: GraphData["nodes"] = [];
  const edges: GraphData["edges"] = [];

  const walk = (node: BoardLadderNode, id: string, depth: number): void => {
    const category =
      CATEGORY_BY_DEPTH[Math.min(depth, CATEGORY_BY_DEPTH.length - 1)];
    nodes.push({
      id,
      name: node.name,
      category,
      code: node.code,
      value: node.value,
    });
    const children = node.children ?? [];
    children.forEach((child, idx) => {
      const childId = `${id}/${idx}`;
      edges.push({ source: id, target: childId, type: "ladder", weight: 1 });
      walk(child, childId, depth + 1);
    });
  };

  walk(tree, "root", 0);
  return { nodes, edges };
}

interface BoardLadderProps {
  /** ISO 日期；默认今日（后端处理）。 */
  date?: string;
  /** 图高；默认与 GraphView 一致（420）。 */
  height?: number;
}

/**
 * 连板梯队树容器：em_zt_topic_pool 涨停池，按连板高度分层，同题材归枝。
 * - 调 useBoardLadder(date) 取嵌套树（BoardLadderNode）
 * - buildLadderGraph → 扁平 GraphData（parent→child 梯队边）
 * - 喂 GraphView tree 布局渲染（echarts 正交树）
 * 数据接线/三态由本组件承担；树渲染由 GraphView 承担。
 * 叶节点如实呈现 code/name（公开榜单客观事实，AGENTS.md 允许原始池出口）。
 */
export function BoardLadder({ date, height = 420 }: BoardLadderProps) {
  const { data: tree, isLoading, error, refetch } = useBoardLadder(date);

  const graphData = useMemo<GraphData>(() => {
    if (!tree) return { nodes: [], edges: [] };
    return buildLadderGraph(tree);
  }, [tree]);

  return (
    <GlassCard>
      <SectionHeader
        title="连板梯队"
        icon={<Layers className="h-4 w-4" aria-hidden="true" />}
        subtitle="涨停池按连板高度分层，同题材归枝（叶节点呈现 code/name）"
      />
      {isLoading ? (
        <LoadingState variant="inline" label="加载连板梯队…" />
      ) : error ? (
        <ErrorState
          message="连板梯队加载失败"
          onRetry={refetch ? () => refetch() : undefined}
        />
      ) : (
        <GraphView data={graphData} layout="tree" height={height} />
      )}
    </GlassCard>
  );
}
