// S025-B1 测试：StatsMetrics 概览区——6 个 MetricCard 矩阵消费 useWinRateStats。
// 三态：loading→Skeleton；error/empty→EmptyState；success→6 张 MetricCard。
import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen } from "@testing-library/react";
import type { WinRateStats } from "@/lib/api";

// vi.hoisted 保证 mock fn 引用在 vi.mock 工厂与测试间一致。
const hooks = vi.hoisted(() => ({
  useWinRateStats: vi.fn(),
}));

vi.mock("@/lib/query", () => ({
  useWinRateStats: hooks.useWinRateStats,
}));

import { StatsMetrics } from "../StatsMetrics";

const stats: WinRateStats = {
  window_size: 30,
  total_trades: 50,
  win_count: 30,
  win_rate: 0.6,
  avg_return: 1.5,
  max_drawdown: -8.2,
  sharpe_ratio: 1.3,
  trend: "stable",
  sector_breakdown: {},
  strategy_breakdown: {},
  score_breakdown: {},
};

function mockOk(data: WinRateStats) {
  hooks.useWinRateStats.mockReturnValue({
    data,
    isLoading: false,
    isError: false,
    error: null,
  });
}

function mockLoading() {
  hooks.useWinRateStats.mockReturnValue({ data: undefined, isLoading: true, isError: false, error: null });
}

function mockError() {
  hooks.useWinRateStats.mockReturnValue({
    data: undefined,
    isLoading: false,
    isError: true,
    error: new Error("boom"),
  });
}

describe("StatsMetrics (B1)", () => {
  beforeEach(() => vi.clearAllMocks());

  it("hook 收到 windowSize 入参", () => {
    mockOk(stats);
    render(<StatsMetrics windowSize={30} />);
    expect(hooks.useWinRateStats).toHaveBeenCalledWith(30);
  });

  it("success → 渲染 6 个 MetricCard（标签齐全）", () => {
    mockOk(stats);
    render(<StatsMetrics windowSize={30} />);
    for (const label of ["总交易", "胜数", "胜率", "平均收益", "最大回撤", "夏普"]) {
      expect(screen.getByText(label)).toBeInTheDocument();
    }
  });

  it("success → 数值格式化正确（胜率%/收益%/夏普两位）", () => {
    mockOk(stats);
    render(<StatsMetrics windowSize={30} />);
    expect(screen.getByText("60.0%")).toBeInTheDocument(); // 胜率 0.6 → 60.0%
    expect(screen.getByText("1.50%")).toBeInTheDocument(); // 平均收益
    expect(screen.getByText("-8.20%")).toBeInTheDocument(); // 最大回撤
    expect(screen.getByText("1.30")).toBeInTheDocument(); // 夏普
  });

  it("success → 总交易/胜数按原数渲染", () => {
    mockOk(stats);
    render(<StatsMetrics windowSize={30} />);
    expect(screen.getByText("50")).toBeInTheDocument();
    expect(screen.getByText("30")).toBeInTheDocument();
  });

  it("loading → 不渲染指标卡（骨架态）", () => {
    mockLoading();
    render(<StatsMetrics windowSize={30} />);
    expect(screen.queryByText("总交易")).not.toBeInTheDocument();
  });

  it("error → 渲染空状态", () => {
    mockError();
    render(<StatsMetrics windowSize={30} />);
    expect(screen.queryByText("总交易")).not.toBeInTheDocument();
  });
});
