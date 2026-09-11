// S183 测试：JournalWinRateCurve——echarts stack CI band + 50% markLine + 空态 + 双轴标签。
// 仿 TrendsChart.test.tsx 范式：mock echarts.init + useJournalWinRateTrends。
import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen } from "@testing-library/react";

const echartsMocks = vi.hoisted(() => {
  const setOption = vi.fn();
  const dispose = vi.fn();
  const resize = vi.fn();
  const init = vi.fn(() => ({ setOption, dispose, resize }));
  return { init, setOption, dispose, resize };
});

vi.mock("echarts/core", () => ({ init: echartsMocks.init, use: vi.fn(), default: { init: echartsMocks.init, use: vi.fn() } }));

const hooks = vi.hoisted(() => ({
  useJournalWinRateTrends: vi.fn(),
}));

vi.mock("@/lib/query/journal", () => ({ useJournalWinRateTrends: hooks.useJournalWinRateTrends }));

import { JournalWinRateCurve } from "../JournalWinRateCurve";

const trends = [
  { week_start: "2026-09-07", win_rate: 0.667, ci_low: 0.208, ci_high: 0.939, n_decided: 3, n_total: 3, n_days: 1, label: "insufficient_sample" as const },
  { week_start: "2026-09-14", win_rate: 0.5, ci_low: 0.3, ci_high: 0.7, n_decided: 6, n_total: 6, n_days: 2, label: "insufficient_sample" as const },
];

function mockOk(data: typeof trends) {
  hooks.useJournalWinRateTrends.mockReturnValue({ data: { available: true, trends: data }, isLoading: false, isError: false, error: null });
}
function mockEmpty() {
  hooks.useJournalWinRateTrends.mockReturnValue({ data: { available: true, trends: [] }, isLoading: false, isError: false, error: null });
}
function mockLoading() {
  hooks.useJournalWinRateTrends.mockReturnValue({ data: undefined, isLoading: true, isError: false, error: null });
}
function mockError() {
  hooks.useJournalWinRateTrends.mockReturnValue({ data: undefined, isLoading: false, isError: true, error: new Error("boom") });
}

describe("JournalWinRateCurve (S183)", () => {
  beforeEach(() => vi.clearAllMocks());

  it("success → init + setOption（3 series: CI下/CI带/胜率 + markLine 50）", () => {
    mockOk(trends);
    render(<JournalWinRateCurve />);
    expect(echartsMocks.init).toHaveBeenCalledTimes(1);
    expect(echartsMocks.setOption).toHaveBeenCalledTimes(1);
    const option = echartsMocks.setOption.mock.calls[0][0];
    expect(option.series).toHaveLength(3);
    expect(option.series[0].stack).toBe("ci");  // CI 下透明垫底
    expect(option.series[1].stack).toBe("ci");  // CI 带差值
    expect(option.series[2].data).toEqual([66.7, 50]);  // win_rate×100
    expect(option.xAxis.data).toEqual(["2026-09-07", "2026-09-14"]);
    // 50% 随机基准 markLine
    expect(option.series[2].markLine.data[0].yAxis).toBe(50);
  });

  it("空数据 → 不 init echarts + 显'模拟盘积累中'占位", () => {
    mockEmpty();
    render(<JournalWinRateCurve />);
    expect(echartsMocks.init).not.toHaveBeenCalled();
    expect(screen.getByText("模拟盘积累中")).toBeInTheDocument();
  });

  it("loading → 不 init echarts", () => {
    mockLoading();
    render(<JournalWinRateCurve />);
    expect(echartsMocks.init).not.toHaveBeenCalled();
  });

  it("error → 不 init + 显'胜率曲线加载失败'", () => {
    mockError();
    render(<JournalWinRateCurve />);
    expect(echartsMocks.init).not.toHaveBeenCalled();
    expect(screen.getByText("胜率曲线加载失败")).toBeInTheDocument();
  });
});
