// S025-B2 测试：TrendsChart 趋势折线——echarts.init 模式（useEffect+init+resize+dispose）。
// mock echarts.init 返回带 setOption/dispose/resize 的实例；mock useWinRateTrends。
import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, act } from "@testing-library/react";

// echarts mock：init 返回共享 setOption/dispose/resize 的实例，便于断言调用。
const echartsMocks = vi.hoisted(() => {
  const setOption = vi.fn();
  const dispose = vi.fn();
  const resize = vi.fn();
  const init = vi.fn(() => ({ setOption, dispose, resize }));
  return { init, setOption, dispose, resize };
});

vi.mock("echarts/core", () => ({ init: echartsMocks.init, use: vi.fn(), default: { init: echartsMocks.init, use: vi.fn() } }));

const hooks = vi.hoisted(() => ({
  useWinRateTrends: vi.fn(),
}));

vi.mock("@/lib/query", () => ({ useWinRateTrends: hooks.useWinRateTrends }));

import { TrendsChart } from "../TrendsChart";

const trends = [
  { date: "2026-07-28", total_trades: 5, win_count: 3, win_rate: 0.6 },
  { date: "2026-07-29", total_trades: 4, win_count: 2, win_rate: 0.5 },
  { date: "2026-07-30", total_trades: 6, win_count: 4, win_rate: 0.66 },
];

function mockOk(data: typeof trends) {
  hooks.useWinRateTrends.mockReturnValue({ data, isLoading: false, isError: false, error: null });
}
function mockEmpty() {
  hooks.useWinRateTrends.mockReturnValue({ data: [], isLoading: false, isError: false, error: null });
}
function mockLoading() {
  hooks.useWinRateTrends.mockReturnValue({ data: undefined, isLoading: true, isError: false, error: null });
}
function mockError() {
  hooks.useWinRateTrends.mockReturnValue({ data: undefined, isLoading: false, isError: true, error: new Error("boom") });
}

describe("TrendsChart (B2)", () => {
  beforeEach(() => vi.clearAllMocks());

  it("hook 收到 windowSize 入参", () => {
    mockOk(trends);
    render(<TrendsChart windowSize={30} />);
    expect(hooks.useWinRateTrends).toHaveBeenCalledWith(30);
  });

  it("success → 调 echarts.init + setOption（折线 + 胜率数据点）", () => {
    mockOk(trends);
    render(<TrendsChart windowSize={30} />);
    expect(echartsMocks.init).toHaveBeenCalledTimes(1);
    expect(echartsMocks.setOption).toHaveBeenCalledTimes(1);
    const option = echartsMocks.setOption.mock.calls[0][0];
    expect(option.series[0].type).toBe("line");
    // win_rate×100 取整：0.6→60, 0.5→50, 0.66→66
    expect(option.series[0].data).toEqual([60, 50, 66]);
    expect(option.xAxis.data).toEqual(["2026-07-28", "2026-07-29", "2026-07-30"]);
  });

  it("空数据 → 不 init echarts，显示占位", () => {
    mockEmpty();
    render(<TrendsChart windowSize={30} />);
    expect(echartsMocks.init).not.toHaveBeenCalled();
    expect(screen.getByText("暂无趋势数据")).toBeInTheDocument();
  });

  it("loading → 不 init echarts", () => {
    mockLoading();
    render(<TrendsChart windowSize={30} />);
    expect(echartsMocks.init).not.toHaveBeenCalled();
  });

  it("error → 不 init echarts，显示占位", () => {
    mockError();
    render(<TrendsChart windowSize={30} />);
    expect(echartsMocks.init).not.toHaveBeenCalled();
    expect(screen.getByText("暂无趋势数据")).toBeInTheDocument();
  });

  it("窗口 resize → 调 instance.resize", () => {
    mockOk(trends);
    render(<TrendsChart windowSize={30} />);
    act(() => {
      window.dispatchEvent(new Event("resize"));
    });
    expect(echartsMocks.resize).toHaveBeenCalled();
  });

  it("卸载 → 调 instance.dispose", () => {
    mockOk(trends);
    const { unmount } = render(<TrendsChart windowSize={30} />);
    unmount();
    expect(echartsMocks.dispose).toHaveBeenCalledTimes(1);
  });
});
