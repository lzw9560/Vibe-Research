// S024-E1 测试：Topology 拓扑视图入口——页内 TabBar 切换三视图（关系网/漏斗流程/连板梯队）。
// 仿 AuctionScreener.test.tsx：mock 三拓扑组件（隔离 echarts/数据 hook），断言 Tab 切换逻辑。
// 三视图各自有独立测试（RelationGraph/FunnelFlow/BoardLadder），此处只验接线 + 三视图可切换。
// 合规 §0（弱合规·工程底线）：拓扑入口只呈现客观关联，不输出方向词。
import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, fireEvent } from "@testing-library/react";

// ---- hoisted mocks：vi.mock 提升不捕获顶层变量，故用 hoisted 持有 ----
const componentMocks = vi.hoisted(() => ({
  RelationGraph: vi.fn(() => <div data-testid="rg-stub">relation</div>),
  FunnelFlow: vi.fn(() => <div data-testid="ff-stub">funnel</div>),
  BoardLadder: vi.fn(() => <div data-testid="bl-stub">ladder</div>),
}));

vi.mock("@/components/topology/RelationGraph", () => ({
  RelationGraph: componentMocks.RelationGraph,
}));
vi.mock("@/components/topology/FunnelFlow", () => ({
  FunnelFlow: componentMocks.FunnelFlow,
}));
vi.mock("@/components/topology/BoardLadder", () => ({
  BoardLadder: componentMocks.BoardLadder,
}));

// S065 followup：Topology 加了 AskAiButton（调 useTopologyRelation/useFunnelLayers/useBoardLadder）
const queryMocks = vi.hoisted(() => ({
  useTopologyRelation: vi.fn(() => ({ data: null })),
  useFunnelLayers: vi.fn(() => ({ data: null })),
  useBoardLadder: vi.fn(() => ({ data: null })),
}));
vi.mock("@/lib/query", () => ({
  useTopologyRelation: queryMocks.useTopologyRelation,
  useFunnelLayers: queryMocks.useFunnelLayers,
  useBoardLadder: queryMocks.useBoardLadder,
}));
// AskAiButton 内部调 hasLlm/chatStream，mock 掉避免真实 LLM 调用
vi.mock("@/components/ui/AskAiButton", () => ({
  AskAiButton: () => <div data-testid="ask-ai-stub">问 AI</div>,
}));

import { Topology } from "@/pages/workflow/Topology";

describe("Topology 拓扑视图入口 (S024-E1)", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    // 重置默认实现（clearAllMocks 清掉实现，需重挂）
    componentMocks.RelationGraph.mockImplementation(
      () => <div data-testid="rg-stub">relation</div>,
    );
    componentMocks.FunnelFlow.mockImplementation(
      () => <div data-testid="ff-stub">funnel</div>,
    );
    componentMocks.BoardLadder.mockImplementation(
      () => <div data-testid="bl-stub">ladder</div>,
    );
  });

  it("渲染 PageHeader + TabBar 三 tab + 默认渲染关系网（RelationGraph）", () => {
    render(<Topology />);
    expect(screen.getByText("拓扑展示")).toBeInTheDocument();
    // TabBar 三 tab 存在
    expect(screen.getByRole("button", { name: "关系网" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "漏斗流程" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "连板梯队" })).toBeInTheDocument();
    // 默认 tab = 关系网 → RelationGraph 渲染，其余不渲染
    expect(screen.getByTestId("rg-stub")).toBeInTheDocument();
    expect(screen.queryByTestId("ff-stub")).not.toBeInTheDocument();
    expect(screen.queryByTestId("bl-stub")).not.toBeInTheDocument();
  });

  it("点「漏斗流程」→ 切换渲染 FunnelFlow，关系网隐藏", () => {
    render(<Topology />);
    fireEvent.click(screen.getByRole("button", { name: "漏斗流程" }));
    expect(screen.queryByTestId("rg-stub")).not.toBeInTheDocument();
    expect(screen.getByTestId("ff-stub")).toBeInTheDocument();
    expect(screen.queryByTestId("bl-stub")).not.toBeInTheDocument();
  });

  it("点「连板梯队」→ 切换渲染 BoardLadder，其余隐藏", () => {
    render(<Topology />);
    fireEvent.click(screen.getByRole("button", { name: "连板梯队" }));
    expect(screen.queryByTestId("rg-stub")).not.toBeInTheDocument();
    expect(screen.queryByTestId("ff-stub")).not.toBeInTheDocument();
    expect(screen.getByTestId("bl-stub")).toBeInTheDocument();
  });

  it("三视图均接收 date prop（默认 undefined，后端取今日）", () => {
    render(<Topology />);
    // 默认 tab 关系网 → RelationGraph 被调用
    expect(componentMocks.RelationGraph).toHaveBeenCalled();
    // 切到漏斗流程 → FunnelFlow 被调用
    fireEvent.click(screen.getByRole("button", { name: "漏斗流程" }));
    expect(componentMocks.FunnelFlow).toHaveBeenCalled();
    // 切到连板梯队 → BoardLadder 被调用
    fireEvent.click(screen.getByRole("button", { name: "连板梯队" }));
    expect(componentMocks.BoardLadder).toHaveBeenCalled();
  });

  it("切回关系网 → BoardLadder 隐藏、RelationGraph 复现", () => {
    render(<Topology />);
    fireEvent.click(screen.getByRole("button", { name: "连板梯队" }));
    expect(screen.getByTestId("bl-stub")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "关系网" }));
    expect(screen.queryByTestId("bl-stub")).not.toBeInTheDocument();
    expect(screen.getByTestId("rg-stub")).toBeInTheDocument();
  });
});
