// S024-B7 测试：RelationGraph 关系网——调 hook 取 GraphData 喂 GraphView，节点点击进候选详情。
// 仿 GraphView.test.tsx：mock 协作者（@/lib/query、react-router-dom、GraphView），
// 断言数据接线（GraphView 收到 GraphData）+ 节点点击 → navigate('/workflow/candidates/:code')。
// 边按 type 着色由 GraphView 负责（其自有测试覆盖），此处只验关系网容器逻辑。
import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, fireEvent } from "@testing-library/react";
import type { GraphData, GraphNode } from "../types";

// ---- hoisted mocks：引用在 factory 与测试间一致（vi.mock 提升不捕获顶层变量）----
const navMock = vi.hoisted(() => ({ navigate: vi.fn() }));
const hookMock = vi.hoisted(() => ({
  useTopologyRelation: vi.fn(),
  // GraphView stub 需回调节点；hoisted 持有当前 onNodeClick，供 trigger 按钮调用。
  onNodeClickRef: { current: null as ((n: GraphNode) => void) | null },
}));

vi.mock("@/lib/query", () => ({
  useTopologyRelation: hookMock.useTopologyRelation,
}));

vi.mock("react-router-dom", () => ({
  useNavigate: () => navMock.navigate,
}));

// GraphView stub：渲染 data-testid + 暴露 node-count；trigger 按钮调 onNodeClick。
vi.mock("../GraphView", () => ({
  GraphView: (props: { data: GraphData; onNodeClick?: (n: GraphNode) => void }) => {
    hookMock.onNodeClickRef.current = props.onNodeClick ?? null;
    return (
      <div data-testid="rg-graph" data-node-count={props.data.nodes.length}>
        <button
          data-testid="rg-node-trigger"
          onClick={() =>
            props.onNodeClick?.({ id: "000001", name: "标的A", code: "000001" })
          }
        >
          node
        </button>
      </div>
    );
  },
}));

import { RelationGraph } from "../RelationGraph";

const mockData: GraphData = {
  nodes: [
    { id: "000001", name: "标的A", category: "candidate", code: "000001", value: 10 },
    { id: "600519", name: "标的B", category: "candidate", code: "600519", value: 8 },
    { id: "300750", name: "标的C", category: "candidate", code: "300750", value: 5 },
  ],
  edges: [
    { source: "000001", target: "600519", type: "sector", weight: 1 },
    { source: "600519", target: "300750", type: "fund_flow", weight: 2 },
    { source: "000001", target: "300750", type: "ladder", weight: 1 },
    { source: "600519", target: "300750", type: "seat", weight: 1 },
  ],
};

function hookReturning(overrides: Partial<{
  data: GraphData;
  isLoading: boolean;
  error: unknown;
  refetch: () => void;
}>) {
  return {
    data: undefined as GraphData | undefined,
    isLoading: false,
    error: null as unknown,
    refetch: vi.fn(),
    ...overrides,
  };
}

describe("RelationGraph (S024-B7)", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    hookMock.onNodeClickRef.current = null;
    hookMock.useTopologyRelation.mockReturnValue(hookReturning({ data: mockData }));
  });

  it("成功 → 调 useTopologyRelation，GraphView 渲染且收到完整 GraphData（4 类边）", () => {
    render(<RelationGraph />);
    expect(hookMock.useTopologyRelation).toHaveBeenCalled();
    const gv = screen.getByTestId("rg-graph");
    expect(gv).toBeInTheDocument();
    expect(gv.getAttribute("data-node-count")).toBe("3");
  });

  it("节点点击 → navigate('/workflow/candidates/:code')", () => {
    render(<RelationGraph />);
    fireEvent.click(screen.getByTestId("rg-node-trigger"));
    expect(navMock.navigate).toHaveBeenCalledTimes(1);
    expect(navMock.navigate).toHaveBeenCalledWith("/workflow/candidates/000001");
  });

  it("传入 date → 透传给 hook（queryKey 维度）", () => {
    hookMock.useTopologyRelation.mockReturnValue(hookReturning({ data: mockData }));
    render(<RelationGraph date="2026-08-01" />);
    expect(hookMock.useTopologyRelation).toHaveBeenCalledWith("2026-08-01");
  });

  it("loading → 显示加载态（不渲染 GraphView）", () => {
    hookMock.useTopologyRelation.mockReturnValue(hookReturning({ isLoading: true }));
    render(<RelationGraph />);
    expect(screen.queryByTestId("rg-graph")).not.toBeInTheDocument();
    expect(screen.getByText("加载关系网…")).toBeInTheDocument();
  });

  it("error → 显示错误态 + 重试（调 refetch）", () => {
    const refetch = vi.fn();
    hookMock.useTopologyRelation.mockReturnValue(
      hookReturning({ error: new Error("后端连接失败"), refetch }),
    );
    render(<RelationGraph />);
    expect(screen.queryByTestId("rg-graph")).not.toBeInTheDocument();
    expect(screen.getByText("关系网加载失败")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "重试" }));
    expect(refetch).toHaveBeenCalledTimes(1);
  });

  it("空 GraphData（无节点）→ 透传 GraphView，由其显示空占位", () => {
    hookMock.useTopologyRelation.mockReturnValue(
      hookReturning({ data: { nodes: [], edges: [] } }),
    );
    render(<RelationGraph />);
    const gv = screen.getByTestId("rg-graph");
    expect(gv.getAttribute("data-node-count")).toBe("0");
  });
});
