// S025-B3 测试：BreakdownTable 拆分下钻——DataTable 按 sector / 按 strategy。
// 消费 useWinRateSector/Strategy，sector/strategy 任一非空即下钻对应维度。
import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen } from "@testing-library/react";

const hooks = vi.hoisted(() => ({
  useWinRateSector: vi.fn(),
  useWinRateStrategy: vi.fn(),
}));

vi.mock("@/lib/query", () => ({
  useWinRateSector: hooks.useWinRateSector,
  useWinRateStrategy: hooks.useWinRateStrategy,
}));

import { BreakdownTable } from "../BreakdownTable";

const sectorStats = { sector: "银行", total_trades: 5, win_count: 3, win_rate: 0.6, avg_return: 1.2 };
const strategyStats = { strategy: "打板", total_trades: 4, win_count: 2, win_rate: 0.5, avg_return: 0.8 };

const emptyRet = { data: undefined, isLoading: false, isError: false, error: null };

describe("BreakdownTable (B3)", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    hooks.useWinRateSector.mockReturnValue(emptyRet);
    hooks.useWinRateStrategy.mockReturnValue(emptyRet);
  });

  it("选 sector → 调 useWinRateSector(sector, windowSize) 且表渲染", () => {
    hooks.useWinRateSector.mockReturnValue({ data: sectorStats, isLoading: false, isError: false, error: null });
    render(<BreakdownTable sector="银行" windowSize={30} />);
    expect(hooks.useWinRateSector).toHaveBeenCalledWith("银行", 30);
    // 表头 + 数据行
    expect(screen.getByText("板块")).toBeInTheDocument();
    expect(screen.getByText("银行")).toBeInTheDocument();
    expect(screen.getByText("5")).toBeInTheDocument(); // total_trades
    expect(screen.getByText("3")).toBeInTheDocument(); // win_count
    expect(screen.getByText("60.0%")).toBeInTheDocument(); // win_rate
    expect(screen.getByText("1.20%")).toBeInTheDocument(); // avg_return
  });

  it("选 strategy → 调 useWinRateStrategy(strategy, windowSize) 且表渲染", () => {
    hooks.useWinRateStrategy.mockReturnValue({ data: strategyStats, isLoading: false, isError: false, error: null });
    render(<BreakdownTable strategy="打板" windowSize={30} />);
    expect(hooks.useWinRateStrategy).toHaveBeenCalledWith("打板", 30);
    expect(screen.getByText("战法")).toBeInTheDocument();
    expect(screen.getByText("打板")).toBeInTheDocument();
    expect(screen.getByText("4")).toBeInTheDocument();
    expect(screen.getByText("2")).toBeInTheDocument();
    expect(screen.getByText("50.0%")).toBeInTheDocument();
    expect(screen.getByText("0.80%")).toBeInTheDocument();
  });

  it("sector + strategy 都未选 → 显示占位", () => {
    render(<BreakdownTable windowSize={30} />);
    expect(screen.getByText("选择板块或战法")).toBeInTheDocument();
  });

  it("loading → 显示骨架（无数据行）", () => {
    hooks.useWinRateSector.mockReturnValue({ data: undefined, isLoading: true, isError: false, error: null });
    render(<BreakdownTable sector="银行" windowSize={30} />);
    expect(screen.queryByText("银行")).not.toBeInTheDocument();
  });

  it("error → 显示空状态", () => {
    hooks.useWinRateSector.mockReturnValue({ data: undefined, isLoading: false, isError: true, error: new Error("nope") });
    render(<BreakdownTable sector="银行" windowSize={30} />);
    expect(screen.queryByText("银行")).not.toBeInTheDocument();
  });
});
