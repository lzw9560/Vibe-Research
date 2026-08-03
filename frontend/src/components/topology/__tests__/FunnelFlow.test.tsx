// S024-C 测试：FunnelFlow 漏斗流程拓扑——复用 funnel/layers 构树形 GraphData，
// 节点点击展开该层 passed 候选。仿 RelationGraph.test.tsx：mock 协作者
//（@/lib/query、../GraphView），断言数据接线（tree 布局 + GraphData 含漏斗层节点/流向边）
// + 节点点击 → 展开 passed 候选列表 + 再次点击折叠。
// buildFunnelGraph 为纯函数，单测直接断言节点/边结构（C1）；组件集成测试覆盖展开行为（C2）。
// 合规 §0（弱合规·工程底线）：拓扑只呈现客观数据流向，不输出方向词。
import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, fireEvent, within } from "@testing-library/react";
import type { FunnelLayer } from "@/lib/api";
import type { GraphData, GraphNode } from "../types";

// ---- hoisted mocks：vi.mock 提升不捕获顶层变量，故用 hoisted 持有 ----
const hookMock = vi.hoisted(() => ({
  useFunnelLayers: vi.fn(),
  // GraphView stub 需回调节点；hoisted 持有当前 onNodeClick，供 trigger 按钮调用。
  onNodeClickRef: { current: null as ((n: GraphNode) => void) | null },
}));

vi.mock("@/lib/query", () => ({
  useFunnelLayers: hookMock.useFunnelLayers,
}));

// GraphView stub：渲染 data-testid + 暴露 node-count/layout；trigger 按钮调 onNodeClick。
vi.mock("../GraphView", () => ({
  GraphView: (props: {
    data: GraphData;
    layout?: string;
    onNodeClick?: (n: GraphNode) => void;
  }) => {
    hookMock.onNodeClickRef.current = props.onNodeClick ?? null;
    return (
      <div
        data-testid="ff-graph"
        data-layout={props.layout ?? "graph"}
        data-node-count={props.data.nodes.length}
        data-edge-count={props.data.edges.length}
      >
        <button
          data-testid="ff-node-trigger"
          onClick={() =>
            props.onNodeClick?.({ id: "R2", name: "R2 · 收敛（入 40 / 出 15）" })
          }
        >
          node
        </button>
      </div>
    );
  },
}));

import { buildFunnelGraph, FunnelFlow } from "../FunnelFlow";

// ---- mock 数据：对齐 backend/candidate_funnel/funnel.py（R1 宽源→R2 收敛→R3 定稿→SELF 自选）----
function makeCandidate(code: string, name: string, layer: string) {
  return {
    code,
    name,
    source_factor_id: "f1",
    source_layer: layer,
    hit_rules: ["规则A"],
    detail: {},
  };
}

const mockLayers: FunnelLayer[] = [
  {
    layer_id: "R1",
    name: "宽源",
    as_of: "2026-08-04T09:30:00",
    input_count: 100,
    output_count: 40,
    filtered_out: [],
    output_codes: ["000001", "600519"],
    conditions: ["换手≥8%", "量比≥2"],
    passed: [makeCandidate("000001", "标的A", "R1"), makeCandidate("600519", "标的B", "R1")],
    data_status: null,
    data_reason: null,
  },
  {
    layer_id: "R2",
    name: "收敛",
    as_of: "2026-08-04T09:30:00",
    input_count: 40,
    output_count: 15,
    filtered_out: [],
    output_codes: ["000001"],
    conditions: ["换手≥8%（生效）"],
    passed: [makeCandidate("000001", "标的A", "R2")],
    data_status: null,
    data_reason: null,
  },
  {
    layer_id: "R3",
    name: "定稿",
    as_of: "2026-08-04T09:30:00",
    input_count: 15,
    output_count: 8,
    filtered_out: [],
    output_codes: ["000001"],
    conditions: ["竞价异动 OR 公告催化"],
    passed: [makeCandidate("000001", "标的A", "R3")],
    data_status: null,
    data_reason: null,
  },
  {
    layer_id: "SELF",
    name: "自选/手动",
    as_of: "2026-08-04T09:30:00",
    input_count: 3,
    output_count: 2,
    filtered_out: [],
    output_codes: ["300750"],
    conditions: ["用户手动加入"],
    passed: [makeCandidate("300750", "标的C", "SELF")],
    data_status: null,
    data_reason: null,
  },
];

function hookReturning(overrides: Partial<{
  data: FunnelLayer[];
  isLoading: boolean;
  error: unknown;
  refetch: () => void;
}>) {
  return {
    data: undefined as FunnelLayer[] | undefined,
    isLoading: false,
    error: null as unknown,
    refetch: vi.fn(),
    ...overrides,
  };
}

describe("buildFunnelGraph (S024-C1)", () => {
  it("四层 → 四节点（按 layer_id 命名，含 input/output 标注）", () => {
    const g = buildFunnelGraph(mockLayers);
    expect(g.nodes).toHaveLength(4);
    expect(g.nodes[0].id).toBe("R1");
    expect(g.nodes[0].name).toContain("宽源");
    expect(g.nodes[0].name).toContain("100");
    expect(g.nodes[0].name).toContain("40");
    expect(g.nodes[3].id).toBe("SELF");
  });

  it("边为数据流向：R1→R2→R3→SELF（连续层串联，type=flow）", () => {
    const g = buildFunnelGraph(mockLayers);
    expect(g.edges).toHaveLength(3);
    expect(g.edges[0]).toMatchObject({ source: "R1", target: "R2", type: "flow" });
    expect(g.edges[1]).toMatchObject({ source: "R2", target: "R3", type: "flow" });
    expect(g.edges[2]).toMatchObject({ source: "R3", target: "SELF", type: "flow" });
  });

  it("空 layers → 空 GraphData（无节点无边）", () => {
    const g = buildFunnelGraph([]);
    expect(g.nodes).toEqual([]);
    expect(g.edges).toEqual([]);
  });

  it("单层 → 单节点无边（根）", () => {
    const g = buildFunnelGraph([mockLayers[0]]);
    expect(g.nodes).toHaveLength(1);
    expect(g.edges).toEqual([]);
  });

  it("节点 value 映射 output_count（候选规模）", () => {
    const g = buildFunnelGraph(mockLayers);
    expect(g.nodes[0].value).toBe(40);
    expect(g.nodes[1].value).toBe(15);
  });

  it("data_status=未取得 → 节点 name 标注采集失败（客观呈现，不臆造）", () => {
    const failed = mockLayers.map((l, i) =>
      i === 1 ? { ...l, data_status: "未取得", data_reason: "R2 收敛采集失败" } : l,
    );
    const g = buildFunnelGraph(failed);
    expect(g.nodes[1].name).toContain("未取得");
  });
});

describe("FunnelFlow (S024-C2)", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    hookMock.onNodeClickRef.current = null;
    hookMock.useFunnelLayers.mockReturnValue(hookReturning({ data: mockLayers }));
  });

  it("成功 → 调 useFunnelLayers，GraphView 以 tree 布局渲染且收到 4 节点 3 边", () => {
    render(<FunnelFlow />);
    expect(hookMock.useFunnelLayers).toHaveBeenCalled();
    const gv = screen.getByTestId("ff-graph");
    expect(gv).toBeInTheDocument();
    expect(gv.getAttribute("data-layout")).toBe("tree");
    expect(gv.getAttribute("data-node-count")).toBe("4");
    expect(gv.getAttribute("data-edge-count")).toBe("3");
  });

  it("节点点击 → 展开该层 passed 候选列表（含 code/name）", () => {
    render(<FunnelFlow />);
    // 初始无展开面板
    expect(screen.queryByTestId("ff-passed-panel")).not.toBeInTheDocument();
    fireEvent.click(screen.getByTestId("ff-node-trigger"));
    const panel = screen.getByTestId("ff-passed-panel");
    expect(panel).toBeInTheDocument();
    // R2 的 passed = [标的A(000001)]
    expect(within(panel).getByText(/000001/)).toBeInTheDocument();
    expect(within(panel).getByText(/标的A/)).toBeInTheDocument();
  });

  it("展开面板呈现该层 conditions（可复现筛选依据）", () => {
    render(<FunnelFlow />);
    fireEvent.click(screen.getByTestId("ff-node-trigger"));
    const panel = screen.getByTestId("ff-passed-panel");
    // R2 conditions = ["换手≥8%（生效）"]
    expect(within(panel).getByText(/换手/)).toBeInTheDocument();
  });

  it("再次点击同节点 → 折叠（toggle）", () => {
    render(<FunnelFlow />);
    fireEvent.click(screen.getByTestId("ff-node-trigger"));
    expect(screen.getByTestId("ff-passed-panel")).toBeInTheDocument();
    fireEvent.click(screen.getByTestId("ff-node-trigger"));
    expect(screen.queryByTestId("ff-passed-panel")).not.toBeInTheDocument();
  });

  it("传入 date → 透传给 hook（queryKey 维度）", () => {
    render(<FunnelFlow date="2026-08-01" />);
    expect(hookMock.useFunnelLayers).toHaveBeenCalledWith("2026-08-01");
  });

  it("loading → 显示加载态（不渲染 GraphView）", () => {
    hookMock.useFunnelLayers.mockReturnValue(hookReturning({ isLoading: true }));
    render(<FunnelFlow />);
    expect(screen.queryByTestId("ff-graph")).not.toBeInTheDocument();
    expect(screen.getByText(/加载漏斗层/)).toBeInTheDocument();
  });

  it("error → 显示错误态 + 重试（调 refetch）", () => {
    const refetch = vi.fn();
    hookMock.useFunnelLayers.mockReturnValue(
      hookReturning({ error: new Error("后端连接失败"), refetch }),
    );
    render(<FunnelFlow />);
    expect(screen.queryByTestId("ff-graph")).not.toBeInTheDocument();
    expect(screen.getByText(/漏斗层加载失败/)).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "重试" }));
    expect(refetch).toHaveBeenCalledTimes(1);
  });

  it("空 layers → 透传 GraphView 空数据（由其显示空占位）", () => {
    hookMock.useFunnelLayers.mockReturnValue(hookReturning({ data: [] }));
    render(<FunnelFlow />);
    const gv = screen.getByTestId("ff-graph");
    expect(gv.getAttribute("data-node-count")).toBe("0");
    expect(gv.getAttribute("data-edge-count")).toBe("0");
  });
});
