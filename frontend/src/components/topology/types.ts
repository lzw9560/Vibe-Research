// S024-A2 共用图引擎类型定义。
// 规范：specs/S024-拓扑展示/plan.md §2。
// 拓扑只呈现客观关联，不输出方向词（§0 合规）。

/**
 * 边类型：可扩展枚举（spec R5：新边类型加 provider 不动视图）。
 * - sector: 同板块联动
 * - fund_flow: 共资金流入
 * - ladder: 连板梯队
 * - seat: 共席位
 * - flow: 漏斗层数据流向（R1→R2→R3→SELF，客观流向，非方向结论）
 */
export type EdgeType = "sector" | "fund_flow" | "ladder" | "seat" | "flow";

/**
 * 布局模式：
 * - graph: 力导向图（关系网）
 * - tree: 正交树（漏斗流程 / 连板梯队）
 */
export type LayoutMode = "graph" | "tree";

/**
 * 图节点。id 唯一；name 展示；category 分组着色；
 * value 可用于节点大小映射；code 关联个股代码。
 */
export interface GraphNode {
  id: string;
  name: string;
  category?: string;
  value?: number;
  code?: string;
}

/**
 * 图边。source/target 指向 GraphNode.id；
 * type 区分关联来源；weight 控制线宽/强度。
 */
export interface GraphEdge {
  source: string;
  target: string;
  type: EdgeType;
  weight: number;
}

/**
 * 统一图数据格式，GraphView 的输入契约。
 */
export interface GraphData {
  nodes: GraphNode[];
  edges: GraphEdge[];
}
