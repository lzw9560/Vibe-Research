// lib/query/topology.ts — TanStack Query hooks（S024 拓扑展示只读端点）。
// 仿 limitup.ts 范式：Opts<T> 参数化，data 推断回具体类型。
// 合规 §0：拓扑只取客观关联（无方向结论），hook 仅搬运数据，不附加语义。
import { useQuery } from "@tanstack/react-query";
import { api } from "@/lib/api";
import type { Opts } from "./types";
import type { GraphData } from "@/components/topology/types";
import type { BoardLadderNode, FunnelLayer } from "@/lib/api";

/**
 * 关系网：候选标的四类客观关联边（sector/fund_flow/ladder/seat）。
 * 后端 GET /api/topology/relation 返 {nodes,edges}，契约同 GraphData，故断言收紧。
 * data 直接喂 GraphView（graph 布局）。
 */
export function useTopologyRelation(date?: string, options?: Opts<GraphData>) {
  return useQuery({
    queryKey: ["topology", "relation", date] as const,
    queryFn: () => api.topologyRelation(date) as Promise<GraphData>,
    ...options,
  });
}

/**
 * 漏斗层：复用 S023 GET /api/workflow/funnel/layers，返 FunnelLayer[]（含 conditions/passed）。
 * data 经 buildFunnelGraph 构树形 GraphData 喂 GraphView（tree 布局）。
 * 客观层数据流向（R1→R2→R3→SELF），不输出方向结论。
 */
export function useFunnelLayers(date?: string, options?: Opts<FunnelLayer[]>) {
  return useQuery({
    queryKey: ["funnel", "layers", date] as const,
    queryFn: () => api.funnelLayers(date) as Promise<FunnelLayer[]>,
    ...options,
  });
}

/**
 * 连板梯队树：em_zt_topic_pool 涨停池嵌套树（root→height→industry→stock 叶）。
 * 后端 GET /api/topology/board-ladder 返 BoardLadderNode（嵌套树，非 GraphData），
 * 经 buildLadderGraph 展平为 GraphData 喂 GraphView（tree 布局）。
 * 客观梯队关联（同题材归枝），不输出方向结论。
 */
export function useBoardLadder(date?: string, options?: Opts<BoardLadderNode>) {
  return useQuery({
    queryKey: ["topology", "board-ladder", date] as const,
    queryFn: () => api.boardLadder(date) as Promise<BoardLadderNode>,
    ...options,
  });
}
