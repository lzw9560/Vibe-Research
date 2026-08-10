import { describe, it, expect } from "vitest";
import { render, screen } from "@testing-library/react";
import { WinRateComparePanel } from "./WinRateComparePanel";
import type { StrategyBacktestItem } from "@/lib/query/strategy";
import type { PassedItem } from "@/lib/candidates";

// S031 T24：WinRateComparePanel——真实回测 vs 合成估算两列对比。
// 合成公式 min(conf*0.8+0.2,0.95)：首板(0.85)→0.88、连板(0.6)→0.68。
const backtest: StrategyBacktestItem[] = [
  { strategy: "首板挖掘", strategy_code: "first_plate", win_rate: 0.623, avg_return: 2.1, sample_size: 12, available_days: 8 },
  { strategy: "连板接力", strategy_code: "consecutive_relay", win_rate: 0.78, avg_return: 2.1, sample_size: 18, available_days: 8 },
];
const l2Passed: PassedItem[] = [
  { code: "000001", name: "X", best_strategy: "首板挖掘", confidence_value: 0.85 },
  { code: "000002", name: "Y", best_strategy: "连板接力", confidence_value: 0.6 },
];

describe("WinRateComparePanel", () => {
  it("渲染回测胜率 + 合成估算两列", () => {
    render(<WinRateComparePanel backtest={backtest} l2Passed={l2Passed} />);
    expect(screen.getByText(/首板挖掘/)).toBeInTheDocument();
    expect(screen.getByText("62.3%")).toBeInTheDocument(); // 回测
    expect(screen.getByText("88.0%")).toBeInTheDocument(); // 合成(0.85→0.88)
    expect(screen.getAllByText("估算").length).toBe(2); // 两行合成均标估算
  });

  it("无 backtest 数据返回 null", () => {
    const { container } = render(<WinRateComparePanel l2Passed={l2Passed} />);
    expect(container.firstChild).toBeNull();
  });

  it("loading 显示 Skeleton", () => {
    const { container } = render(<WinRateComparePanel loading />);
    expect(container.firstChild).not.toBeNull();
  });
});
