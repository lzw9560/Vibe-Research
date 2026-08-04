// S024-A2 共用图引擎类型定义。
// 规范：specs/S024-拓扑展示/plan.md §2。
// 拓扑只呈现客观关联，不输出方向词（§0 合规）。
//
// 数据契约类型（EdgeType/GraphNode/GraphEdge/GraphData）已移至共享契约层
// @/lib/api/types（S024-C review #3：API 层直接返 GraphData，消除 query 层 as cast）。
// 此处仅留视图层 LayoutMode + 重新导出契约类型供 GraphView 本地引用。

export type { EdgeType, GraphData, GraphEdge, GraphNode } from "@/lib/api/types";

/**
 * 布局模式：
 * - graph: 力导向图（关系网）
 * - tree: 正交树（漏斗流程 / 连板梯队）
 */
export type LayoutMode = "graph" | "tree";
