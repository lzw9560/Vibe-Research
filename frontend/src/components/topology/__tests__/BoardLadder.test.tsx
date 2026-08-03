// S024-D2 测试：BoardLadder 连板梯队树——调 useBoardLadder 取后端嵌套树，
// buildLadderGraph 展平为 GraphData（parent→child, type=ladder）喂 GraphView（tree 布局），
// 叶节点如实呈现 code/name（公开榜单客观事实）。仿 FunnelFlow.test.tsx：mock 协作者
//（@/lib/query、../GraphView），断言数据接线（tree 布局 + 含连板高度分层 + code/name 节点）。
// buildLadderGraph 为纯函数，单测直接断言节点/边结构（D2 核心）；组件集成测试覆盖三态。
// 合规 §0（弱合规·工程底线）：拓扑只呈现客观梯队关联，不输出方向词。
import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, fireEvent } from "@testing-library/react";
import type { BoardLadderNode } from "@/lib/api";
import type { GraphData, GraphNode } from "../types";

// ---- hoisted mocks：vi.mock 提升不捕获顶层变量，故用 hoisted 持有 ----
const hookMock = vi.hoisted(() => ({
  useBoardLadder: vi.fn(),
}));

vi.mock("@/lib/query", () => ({
  useBoardLadder: hookMock.useBoardLadder,
}));

// GraphView stub：渲染 data-testid + 暴露 layout/node-count/edge-count。
// BoardLadder 无节点点击导航（纯呈现），故 stub 不需 onNodeClick trigger。
vi.mock("../GraphView", () => ({
  GraphView: (props: {
    data: GraphData;
    layout?: string;
    onNodeClick?: (n: GraphNode) => void;
  }) => (
    <div
      data-testid="bl-graph"
      data-layout={props.layout ?? "graph"}
      data-node-count={props.data.nodes.length}
      data-edge-count={props.data.edges.length}
    >
      {props.data.nodes
        .filter((n) => n.code)
        .map((n) => (
          <span key={n.id} data-testid="bl-leaf">
            {n.name}
          </span>
        ))}
    </div>
  ),
}));

import { buildLadderGraph, BoardLadder } from "../BoardLadder";

// ---- mock 数据：对齐 backend/tests/test_topology.py（root→height→industry→stock 叶）----
const mockTree: BoardLadderNode = {
  name: "当日涨停",
  children: [
    {
      name: "3板",
      children: [
        {
          name: "白酒",
          children: [
            { name: "600519 贵州茅台", code: "600519", value: 3 },
            { name: "000858 五粮液", code: "000858", value: 3 },
          ],
        },
      ],
    },
    {
      name: "1板",
      children: [
        {
          name: "新能源",
          children: [
            { name: "300750 宁德时代", code: "300750", value: 1 },
          ],
        },
      ],
    },
  ],
};

function hookReturning(overrides: Partial<{
  data: BoardLadderNode;
  isLoading: boolean;
  error: unknown;
  refetch: () => void;
}>) {
  return {
    data: undefined as BoardLadderNode | undefined,
    isLoading: false,
    error: null as unknown,
    refetch: vi.fn(),
    ...overrides,
  };
}

describe("buildLadderGraph (S024-D2 纯函数)", () => {
  it("根节点 = 当日涨停（无入边 → 根；GraphView.buildTree 据此建树）", () => {
    const g = buildLadderGraph(mockTree);
    const root = g.nodes.find((n) => n.name === "当日涨停");
    expect(root).toBeDefined();
    const incoming = g.edges.filter((e) => e.target === root!.id);
    expect(incoming).toHaveLength(0);
  });

  it("叶节点带 code + name 含 code/name（如实呈现公开榜单）", () => {
    const g = buildLadderGraph(mockTree);
    const leaves = g.nodes.filter((n) => n.code);
    expect(leaves).toHaveLength(3);
    const codes = leaves.map((l) => l.code);
    expect(codes).toEqual(expect.arrayContaining(["600519", "000858", "300750"]));
    // name 同时含 code 与个股名（后端拼好，前端如实透传）
    const maotai = leaves.find((l) => l.code === "600519");
    expect(maotai?.name).toContain("600519");
    expect(maotai?.name).toContain("贵州茅台");
  });

  it("边为 parent→child 且 type=ladder（梯队客观关联，不附方向语义）", () => {
    const g = buildLadderGraph(mockTree);
    expect(g.edges.every((e) => e.type === "ladder")).toBe(true);
    // root→height 边：当日涨停→3板、当日涨停→1板
    const root = g.nodes.find((n) => n.name === "当日涨停")!;
    const rootOut = g.edges.filter((e) => e.source === root.id);
    expect(rootOut).toHaveLength(2);
  });

  it("按连板高度分层：3板与1板均为根的子层", () => {
    const g = buildLadderGraph(mockTree);
    const root = g.nodes.find((n) => n.name === "当日涨停")!;
    const heightIds = g.edges
      .filter((e) => e.source === root.id)
      .map((e) => e.target);
    const heightNames = heightIds.map(
      (id) => g.nodes.find((n) => n.id === id)!.name,
    );
    expect(heightNames).toEqual(expect.arrayContaining(["3板", "1板"]));
  });

  it("8 节点 7 边（root + 2 height + 2 industry + 3 leaf = 8；边=7）", () => {
    const g = buildLadderGraph(mockTree);
    expect(g.nodes).toHaveLength(8);
    expect(g.edges).toHaveLength(7);
  });

  it("空池树（仅根 + 空 children）→ 1 节点 0 边（不崩，如实呈现）", () => {
    const g = buildLadderGraph({ name: "当日涨停", children: [] });
    expect(g.nodes).toHaveLength(1);
    expect(g.edges).toEqual([]);
    expect(g.nodes[0].name).toBe("当日涨停");
  });
});

describe("BoardLadder (S024-D2 组件)", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    hookMock.useBoardLadder.mockReturnValue(hookReturning({ data: mockTree }));
  });

  it("成功 → 调 useBoardLadder，GraphView 以 tree 布局渲染且收到 8 节点 7 边", () => {
    render(<BoardLadder />);
    expect(hookMock.useBoardLadder).toHaveBeenCalled();
    const gv = screen.getByTestId("bl-graph");
    expect(gv).toBeInTheDocument();
    expect(gv.getAttribute("data-layout")).toBe("tree");
    expect(gv.getAttribute("data-node-count")).toBe("8");
    expect(gv.getAttribute("data-edge-count")).toBe("7");
  });

  it("如实呈现叶节点 code/name（600519 + 贵州茅台 等）", () => {
    render(<BoardLadder />);
    const leaves = screen.getAllByTestId("bl-leaf");
    expect(leaves).toHaveLength(3);
    expect(screen.getByText(/600519/)).toBeInTheDocument();
    expect(screen.getByText(/贵州茅台/)).toBeInTheDocument();
    expect(screen.getByText(/300750/)).toBeInTheDocument();
  });

  it("传入 date → 透传给 hook（queryKey 维度）", () => {
    render(<BoardLadder date="2026-08-01" />);
    expect(hookMock.useBoardLadder).toHaveBeenCalledWith("2026-08-01");
  });

  it("loading → 显示加载态（不渲染 GraphView）", () => {
    hookMock.useBoardLadder.mockReturnValue(hookReturning({ isLoading: true }));
    render(<BoardLadder />);
    expect(screen.queryByTestId("bl-graph")).not.toBeInTheDocument();
    expect(screen.getByText(/加载连板梯队/)).toBeInTheDocument();
  });

  it("error → 显示错误态 + 重试（调 refetch）", () => {
    const refetch = vi.fn();
    hookMock.useBoardLadder.mockReturnValue(
      hookReturning({ error: new Error("后端连接失败"), refetch }),
    );
    render(<BoardLadder />);
    expect(screen.queryByTestId("bl-graph")).not.toBeInTheDocument();
    expect(screen.getByText(/连板梯队加载失败/)).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "重试" }));
    expect(refetch).toHaveBeenCalledTimes(1);
  });

  it("空池树（仅根）→ 透传 GraphView（node-count=1，由其渲染单根）", () => {
    hookMock.useBoardLadder.mockReturnValue(
      hookReturning({ data: { name: "当日涨停", children: [] } }),
    );
    render(<BoardLadder />);
    const gv = screen.getByTestId("bl-graph");
    expect(gv.getAttribute("data-node-count")).toBe("1");
    expect(gv.getAttribute("data-edge-count")).toBe("0");
  });
});
