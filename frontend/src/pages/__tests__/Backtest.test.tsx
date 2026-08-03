// S025-D2 测试：Backtest 页内 TabBar（回测结果 result / 胜率趋势 winrate）。
// mock echarts（ScatterChart）、@/lib/api（backtestScatter/backtestResult）、
// @/lib/query winrate hooks（WinRateView 仅在 tab2 挂载）。
// 验证：默认 tab=回测结果 → 散点图渲染（echarts.init，非纯文本列表）；
// 切「胜率趋势」→ WinRateView 概览出现、回测查询条件隐藏。
import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, fireEvent, waitFor } from "@testing-library/react";

// echarts mock：ScatterChart 在 tab1 挂载时 init。
const echartsMocks = vi.hoisted(() => {
  const setOption = vi.fn();
  const dispose = vi.fn();
  const resize = vi.fn();
  const init = vi.fn(() => ({ setOption, dispose, resize }));
  return { init, setOption, dispose, resize };
});
vi.mock("echarts", () => ({ init: echartsMocks.init, default: { init: echartsMocks.init } }));

// api mock：仅 backtestScatter/backtestResult 被页调用。
const mockApi = vi.hoisted(() => ({
  backtestScatter: vi.fn(),
  backtestResult: vi.fn(),
}));
vi.mock("@/lib/api", () => ({ api: mockApi }));

// winrate hooks mock：WinRateView 在 tab2 挂载时调；返空/loading 让四区标题渲染。
const hooks = vi.hoisted(() => ({
  useWinRateStats: vi.fn(),
  useWinRateTrends: vi.fn(),
  useWinRateAdjustments: vi.fn(),
  useWinRateSector: vi.fn(),
  useWinRateStrategy: vi.fn(),
  useWinRateRecords: vi.fn(() => ({ mutateAsync: vi.fn(), isPending: false })),
}));
vi.mock("@/lib/query", () => ({
  useWinRateStats: hooks.useWinRateStats,
  useWinRateTrends: hooks.useWinRateTrends,
  useWinRateAdjustments: hooks.useWinRateAdjustments,
  useWinRateSector: hooks.useWinRateSector,
  useWinRateStrategy: hooks.useWinRateStrategy,
  useWinRateRecords: hooks.useWinRateRecords,
}));

import Backtest from "../Backtest";

const scatterPoints = [
  { gene_score: 60, next_day_return: 0.03, code: "000001", date: "2026-07-28", industry: "银行" },
  { gene_score: 45, next_day_return: -0.02, code: "600519", date: "2026-07-29", industry: "白酒" },
];
const result = {
  period: "2026-07-01~2026-07-31",
  total_signals: 50,
  hit_count: 30,
  hit_rate: 0.6,
  avg_return: 0.015,
  max_drawdown: -0.08,
  sharpe_ratio: 1.2,
  percentile_analysis: {},
};

function mockAllOk() {
  mockApi.backtestScatter.mockResolvedValue(scatterPoints);
  mockApi.backtestResult.mockResolvedValue(result);
  hooks.useWinRateStats.mockReturnValue({ data: undefined, isLoading: false, isError: false, error: null });
  hooks.useWinRateTrends.mockReturnValue({ data: [], isLoading: false, isError: false, error: null });
  hooks.useWinRateAdjustments.mockReturnValue({ data: undefined, isLoading: false, isError: false, error: null });
  hooks.useWinRateSector.mockReturnValue({ data: undefined, isLoading: false, isError: false, error: null });
  hooks.useWinRateStrategy.mockReturnValue({ data: undefined, isLoading: false, isError: false, error: null });
}

describe("Backtest 页内 TabBar (D2)", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mockAllOk();
  });

  it("默认 tab=回测结果：渲染查询条件 + 散点图（echarts.init，非纯文本列表）", async () => {
    render(<Backtest />);
    await waitFor(() => expect(echartsMocks.init).toHaveBeenCalled());
    expect(screen.getByText("查询条件")).toBeInTheDocument();
    // 散点用 ScatterChart：旧的"散点数据"纯文本标题不再出现
    expect(screen.queryByText(/散点数据/)).not.toBeInTheDocument();
  });

  it("点「胜率趋势」→ 切到 tab2，WinRateView 渲染（概览），回测内容隐藏", async () => {
    render(<Backtest />);
    await waitFor(() => expect(echartsMocks.init).toHaveBeenCalled());

    fireEvent.click(screen.getByRole("button", { name: "胜率趋势" }));

    await waitFor(() => expect(screen.getByText("概览")).toBeInTheDocument());
    expect(screen.queryByText("查询条件")).not.toBeInTheDocument();
  });

  it("从胜率趋势切回回测结果 → 查询条件复现", async () => {
    render(<Backtest />);
    await waitFor(() => expect(echartsMocks.init).toHaveBeenCalled());
    fireEvent.click(screen.getByRole("button", { name: "胜率趋势" }));
    await waitFor(() => expect(screen.getByText("概览")).toBeInTheDocument());
    fireEvent.click(screen.getByRole("button", { name: "回测结果" }));
    await waitFor(() => expect(screen.getByText("查询条件")).toBeInTheDocument());
    expect(screen.queryByText("概览")).not.toBeInTheDocument();
  });
});
