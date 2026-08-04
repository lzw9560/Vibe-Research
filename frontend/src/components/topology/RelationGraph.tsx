// S024-B7 关系网：调 useTopologyRelation 取 GraphData → 喂 GraphView（graph 布局），
// 节点点击进候选详情（复用 S023 CandidateDetail 路由）。边按 type 着色由 GraphView 负责。
// 复用 TopologyPanel shell（S024-B）+ ui 组件。仿 KLineChart 初始化 + CandidateDetail 数据拉取模式。
// 合规 §0（弱合规·工程底线）：拓扑只呈现客观关联（同板块/共流入/梯队/席位），不输出方向词。
import { useNavigate } from "react-router-dom";
import { Share2 } from "lucide-react";
import { useTopologyRelation } from "@/lib/query";
import { TopologyPanel } from "./TopologyPanel";
import { EdgeLegend } from "./EdgeLegend";
import { GraphView } from "./GraphView";
import type { GraphNode } from "./types";

interface RelationGraphProps {
  /** ISO 日期；默认今日（后端处理）。 */
  date?: string;
  /** 图高；默认与 GraphView 一致（420）。 */
  height?: number;
}

/**
 * 关系网容器：候选标的四类客观关联边（sector/fund_flow/ladder/seat）。
 * - 调 useTopologyRelation(date) 取 GraphData
 * - 喂 GraphView graph 布局渲染
 * - 节点点击 → /workflow/candidates/:code（复用 S023 CandidateDetail）
 * 边着色/布局细节由 GraphView 承担；本组件只做数据接线 + 三态 + 导航。
 */
export function RelationGraph({ date, height = 420 }: RelationGraphProps) {
  const navigate = useNavigate();
  const { data, isLoading, error, refetch } = useTopologyRelation(date);

  const handleNodeClick = (node: GraphNode) => {
    if (node.code) {
      navigate(`/workflow/candidates/${node.code}`);
    }
  };

  return (
    <TopologyPanel
      title="关系网"
      icon={<Share2 className="h-4 w-4" aria-hidden="true" />}
      subtitle="候选标的客观关联（同板块 / 共流入 / 梯队 / 席位）"
      isLoading={isLoading}
      loadingLabel="加载关系网…"
      error={error}
      errorMessage="关系网加载失败"
      refetch={refetch}
    >
      <EdgeLegend edges={data?.edges ?? []} />
      <GraphView data={data ?? { nodes: [], edges: [] }} onNodeClick={handleNodeClick} height={height} />
    </TopologyPanel>
  );
}
