// S063 T32 AC19：IntradayMonitor 四层布局渲染 stub 测试。
import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";

// mock 5 个 query hooks（返空数据，验证四层骨架渲染）
const qMocks = vi.hoisted(() => ({
  useIntradayLatest: vi.fn(),
  useIntradayTimeline: vi.fn(),
  useIntradayHoldings: vi.fn(),
  useIntradayScenarios: vi.fn(),
  useIntradayT1Projection: vi.fn(),
  useWorkflowStates: vi.fn(),
}));

vi.mock("@/lib/query", () => ({
  useIntradayLatest: qMocks.useIntradayLatest,
  useIntradayTimeline: qMocks.useIntradayTimeline,
  useIntradayHoldings: qMocks.useIntradayHoldings,
  useIntradayScenarios: qMocks.useIntradayScenarios,
  useIntradayT1Projection: qMocks.useIntradayT1Projection,
  useWorkflowStates: qMocks.useWorkflowStates,
}));

// S066 MarketKillSwitchBanner 的 hook mock（返 undefined → 不渲染横幅）
vi.mock("@/lib/query/strategy", () => ({
  useMarketKillSwitch: () => ({ data: undefined }),
}));

// mock echarts（不渲染真实图表）
vi.mock("@/hooks/useECharts", () => ({
  useECharts: () => {},
}));

import IntradayMonitor from "@/pages/workflow/IntradayMonitor";

function renderPage() {
  return render(
    <MemoryRouter initialEntries={["/workflow/intraday"]}>
      <IntradayMonitor />
    </MemoryRouter>,
  );
}

describe("IntradayMonitor (S063)", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    qMocks.useIntradayLatest.mockReturnValue({ data: null, isLoading: false });
    qMocks.useIntradayTimeline.mockReturnValue({ data: null, isLoading: false });
    qMocks.useIntradayHoldings.mockReturnValue({ data: null, isLoading: false });
    qMocks.useIntradayScenarios.mockReturnValue({ data: null, isLoading: false });
    qMocks.useIntradayT1Projection.mockReturnValue({ data: null, isLoading: false });
    qMocks.useWorkflowStates.mockReturnValue({ data: null, isLoading: false });
  });

  it("AC12：四层纵向布局标题渲染", () => {
    renderPage();
    expect(screen.getByText("Layer 1 · 情绪走势")).toBeInTheDocument();
    expect(screen.getByText("Layer 2 · 持仓×情绪联动")).toBeInTheDocument();
    expect(screen.getByText("Layer 3 · 条件场景推演")).toBeInTheDocument();
    expect(screen.getByText("Layer 4 · T+1 预判")).toBeInTheDocument();
  });

  it("AC12：PipelineProgressBar 渲染 5 节点", () => {
    renderPage();
    // 5 个序号圆点 1-5
    expect(screen.getByText("1")).toBeInTheDocument();
    expect(screen.getByText("5")).toBeInTheDocument();
    expect(screen.getByText("盘中辅助")).toBeInTheDocument();
  });

  it("AC12：状态机看板标题渲染", () => {
    renderPage();
    expect(screen.getByText("状态机看板")).toBeInTheDocument();
  });
});
