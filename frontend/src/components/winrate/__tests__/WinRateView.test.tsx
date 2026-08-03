// S025-B5 测试：WinRateView 主体——FilterBar 窗口滑块（7/30/90）+ 四区编排 + 挂 RecordsForm。
// spy 5 个 winrate hooks + mock echarts（TrendsChart 在 jsdom 内 init）。
// 验证：切窗 7→30→90 → hooks 收到新 windowSize；四区 + RecordsForm 渲染。
import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, fireEvent } from "@testing-library/react";
import type { WinRateStats } from "@/lib/api";

const echartsMocks = vi.hoisted(() => {
  const setOption = vi.fn();
  const dispose = vi.fn();
  const resize = vi.fn();
  const init = vi.fn(() => ({ setOption, dispose, resize }));
  return { init, setOption, dispose, resize };
});

vi.mock("echarts", () => ({ init: echartsMocks.init, default: { init: echartsMocks.init } }));

const hooks = vi.hoisted(() => ({
  useWinRateStats: vi.fn(),
  useWinRateTrends: vi.fn(),
  useWinRateAdjustments: vi.fn(),
  useWinRateSector: vi.fn(),
  useWinRateStrategy: vi.fn(),
  // C2 起 RecordsForm 在视图内挂载，调用 useWinRateRecords；此 stub 防止真 hook 触发网络。
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

import { WinRateView } from "../WinRateView";

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
const trends = [{ date: "2026-07-30", total_trades: 6, win_count: 4, win_rate: 0.66 }];
const adjustments = [{ type: "reduce_exposure", reason: "胜率下降", action: "降仓" }];

const ok = (data: unknown) => ({ data, isLoading: false, isError: false, error: null });
const empty = { data: undefined, isLoading: false, isError: false, error: null };

function mockAll() {
  hooks.useWinRateStats.mockReturnValue(ok(stats));
  hooks.useWinRateTrends.mockReturnValue(ok(trends));
  hooks.useWinRateAdjustments.mockReturnValue(ok(adjustments));
  hooks.useWinRateSector.mockReturnValue(empty);
  hooks.useWinRateStrategy.mockReturnValue(empty);
}

describe("WinRateView (B5)", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mockAll();
  });

  it("初始 defaultWindow=7 → 各 hook 收到 7", () => {
    render(<WinRateView defaultWindow={7} />);
    expect(hooks.useWinRateStats).toHaveBeenLastCalledWith(7);
    expect(hooks.useWinRateTrends).toHaveBeenLastCalledWith(7);
  });

  it("切窗 7→30→90 → useWinRateStats 收到新 windowSize", () => {
    render(<WinRateView defaultWindow={7} />);
    fireEvent.click(screen.getByText("30天"));
    expect(hooks.useWinRateStats).toHaveBeenLastCalledWith(30);
    fireEvent.click(screen.getByText("90天"));
    expect(hooks.useWinRateStats).toHaveBeenLastCalledWith(90);
    fireEvent.click(screen.getByText("7天"));
    expect(hooks.useWinRateStats).toHaveBeenLastCalledWith(7);
  });

  it("四区标题渲染（概览/趋势/下钻/建议）", () => {
    render(<WinRateView defaultWindow={30} />);
    expect(screen.getByText("概览")).toBeInTheDocument();
    expect(screen.getByText("趋势")).toBeInTheDocument();
    expect(screen.getByText("下钻")).toBeInTheDocument();
    expect(screen.getByText("建议")).toBeInTheDocument();
  });

  it("概览区渲染指标卡内容", () => {
    render(<WinRateView defaultWindow={30} />);
    expect(screen.getByText("总交易")).toBeInTheDocument();
  });

  it("挂载 RecordsForm 占位", () => {
    render(<WinRateView defaultWindow={30} />);
    expect(screen.getByText(/记入胜率/)).toBeInTheDocument();
  });

  it("选维度 + 输入值 → 下钻 hook 收到对应值", () => {
    render(<WinRateView defaultWindow={30} />);
    // 默认维度 sector；输入板块名
    const input = screen.getByPlaceholderText("输入板块名");
    fireEvent.change(input, { target: { value: "银行" } });
    expect(hooks.useWinRateSector).toHaveBeenLastCalledWith("银行", 30);
    // 切到 strategy 维度
    fireEvent.click(screen.getByText("按战法"));
    expect(hooks.useWinRateStrategy).toHaveBeenLastCalledWith("", 30);
    fireEvent.change(input, { target: { value: "打板" } });
    expect(hooks.useWinRateStrategy).toHaveBeenLastCalledWith("打板", 30);
  });
});
