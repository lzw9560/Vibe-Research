// S024-A1 共用图引擎：接收 GraphData，echarts graph（力导向）/tree 渲染，节点点击回调。
// 复用 ScatterChart 初始化模式：useEffect + echarts.init + setOption + resize 监听 + dispose。
// 合规（§0）：拓扑只呈现客观关联（同板块/共流入/梯队/席位），不输出方向词。
import { useEffect, useRef } from "react";
import * as echarts from "echarts";
import type { EdgeType, GraphData, GraphEdge, GraphNode, LayoutMode } from "./types";

/** 边类型 → 着色，客观区分关联来源（不附方向语义）。 */
const EDGE_COLORS: Record<EdgeType, string> = {
  sector: "#60a5fa", // 蓝：同板块联动
  fund_flow: "#34d399", // 绿：共资金流入
  ladder: "#fbbf24", // 琥珀：连板梯队
  seat: "#f87171", // 红：共席位
  flow: "#a78bfa", // 紫：漏斗层数据流向
};

interface GraphViewProps {
  data: GraphData;
  layout?: LayoutMode;
  onNodeClick?: (node: GraphNode) => void;
  height?: number;
}

interface TreeNode {
  id: string;
  name: string;
  value?: number;
  code?: string;
  children: TreeNode[];
}

/** 从扁平 GraphData 构建层级树：source=父, target=子；无入边者为根。 */
function buildTree(data: GraphData): TreeNode[] {
  const childIds = new Set(data.edges.map((e) => e.target));
  const roots = data.nodes.filter((n) => !childIds.has(n.id));
  const fallbackRoots = roots.length > 0 ? roots : data.nodes.slice(0, 1);

  const adjacency = new Map<string, GraphEdge[]>();
  for (const e of data.edges) {
    const arr = adjacency.get(e.source) ?? [];
    arr.push(e);
    adjacency.set(e.source, arr);
  }

  const visited = new Set<string>();
  const build = (node: GraphNode): TreeNode => {
    visited.add(node.id);
    const outEdges = adjacency.get(node.id) ?? [];
    const children = outEdges
      .map((e) => data.nodes.find((n) => n.id === e.target))
      .filter((n): n is GraphNode => !!n && !visited.has(n.id))
      .map(build);
    return {
      id: node.id,
      name: node.name,
      value: node.value,
      code: node.code,
      children,
    };
  };
  return fallbackRoots.map(build);
}

/** echarts 力导向图 option。 */
function buildGraphOption(data: GraphData): echarts.EChartsOption {
  const categoryNames = [
    ...new Set(data.nodes.map((n) => n.category).filter((c): c is string => !!c)),
  ];
  const categories = categoryNames.map((name) => ({ name }));
  const catIndex = (c?: string): number =>
    c ? categoryNames.indexOf(c) : -1;

  return {
    tooltip: { trigger: "item" },
    legend: [{ data: categoryNames }],
    series: [
      {
        type: "graph",
        layout: "force",
        roam: true,
        draggable: true,
        categories,
        data: data.nodes.map((n) => ({
          id: n.id,
          name: n.name,
          value: n.value,
          category: catIndex(n.category),
          code: n.code,
        })),
        links: data.edges.map((e) => ({
          source: e.source,
          target: e.target,
          value: e.weight,
          lineStyle: {
            color: EDGE_COLORS[e.type],
            width: 1 + e.weight,
          },
        })),
        force: { repulsion: 120, edgeLength: 80, gravity: 0.1 },
        label: { show: true, position: "right" },
        emphasis: { focus: "adjacency" },
      },
    ],
  };
}

/** echarts 正交树 option（左→右）。 */
function buildTreeOption(data: GraphData): echarts.EChartsOption {
  const treeData = buildTree(data);
  return {
    tooltip: { trigger: "item" },
    series: [
      {
        type: "tree",
        layout: "orthogonal",
        orient: "LR",
        data: treeData,
        top: "5%",
        left: "12%",
        bottom: "5%",
        right: "18%",
        symbolSize: 10,
        label: {
          position: "left",
          verticalAlign: "middle",
          align: "right",
        },
        leaves: {
          label: {
            position: "right",
            verticalAlign: "middle",
            align: "left",
          },
        },
        roam: true,
      },
    ],
  };
}

/**
 * 共用图引擎：graph（力导向）或 tree（正交树）渲染，节点点击回调。
 * 仿 ScatterChart：useEffect 初始化 → setOption → resize 监听 → dispose 清理。
 */
export function GraphView({
  data,
  layout = "graph",
  onNodeClick,
  height = 420,
}: GraphViewProps) {
  const chartRef = useRef<HTMLDivElement>(null);
  const instanceRef = useRef<echarts.ECharts | null>(null);
  // 用 ref 持有回调/数据，避免其身份变化触发重新 init。
  const onNodeClickRef = useRef(onNodeClick);
  onNodeClickRef.current = onNodeClick;
  const dataRef = useRef(data);
  dataRef.current = data;

  const isEmpty = data.nodes.length === 0;

  useEffect(() => {
    if (!chartRef.current || isEmpty) return;

    const instance = echarts.init(chartRef.current);
    instanceRef.current = instance;

    const option =
      layout === "tree" ? buildTreeOption(data) : buildGraphOption(data);
    instance.setOption(option);

    // 节点点击 → 回查 dataRef 取完整 GraphNode（保留 category/code/value）。
    instance.on("click", (params: unknown) => {
      const p = params as {
        dataType?: string;
        data?: { id?: string; name?: string };
      };
      if (!p || p.dataType !== "node" || !p.data) return;
      const d = p.data;
      const found = dataRef.current.nodes.find((n) => n.id === d.id);
      if (found) {
        onNodeClickRef.current?.(found);
      }
    });

    const onResize = () => instanceRef.current?.resize();
    window.addEventListener("resize", onResize);

    return () => {
      window.removeEventListener("resize", onResize);
      instanceRef.current?.dispose();
      instanceRef.current = null;
    };
    // data/layout 驱动重渲染；回调经 ref 不入依赖。
  }, [data, layout, isEmpty]);

  if (isEmpty) {
    return (
      <div className="flex h-[320px] items-center justify-center text-sm text-muted-foreground/60">
        暂无拓扑数据
      </div>
    );
  }

  return <div ref={chartRef} className="w-full" style={{ height }} />;
}
