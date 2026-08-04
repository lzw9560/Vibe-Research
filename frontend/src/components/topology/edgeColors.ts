// S024-C review #4/#14：边色 + 边标签单一真源。
// graph 模式着色（GraphView）与图例（EdgeLegend）共用此模块，避免颜色重复定义漂移。
// 抽独立文件而非放 GraphView：RelationGraph.test mock 了 ../GraphView，
// 图例若从 GraphView 取色会拿到 undefined；独立模块不受组件 mock 影响。
import type { EdgeType } from "@/lib/api/types";

/** 边类型 → 着色，客观区分关联来源（不附方向语义）。 */
export const EDGE_COLORS: Record<EdgeType, string> = {
  sector: "#60a5fa", // 蓝：同板块联动
  fund_flow: "#34d399", // 绿：共资金流入
  ladder: "#fbbf24", // 琥珀：连板梯队
  seat: "#f87171", // 红：共席位
  flow: "#a78bfa", // 紫：漏斗层数据流向
};

/** 边类型 → 中文短标签（图例用，客观，无方向词）。 */
export const EDGE_LABELS: Record<EdgeType, string> = {
  sector: "同板块",
  fund_flow: "共流入",
  ladder: "梯队",
  seat: "共席位",
  flow: "数据流向",
};

/** 未知边类型兜底色（review #4：后端新增 type 前端未注册时不静默褪色）。 */
export const EDGE_COLOR_FALLBACK = "#94a3b8";
