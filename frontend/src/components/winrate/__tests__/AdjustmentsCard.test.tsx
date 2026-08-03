// S025-B4 测试：AdjustmentsCard 调整建议区——GlassCard 呈现 useWinRateAdjustments。
import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen } from "@testing-library/react";

const hooks = vi.hoisted(() => ({
  useWinRateAdjustments: vi.fn(),
}));

vi.mock("@/lib/query", () => ({ useWinRateAdjustments: hooks.useWinRateAdjustments }));

import { AdjustmentsCard } from "../AdjustmentsCard";

const adjustments = [
  { type: "reduce_exposure", reason: "胜率下降至30.0%，建议降低仓位", action: "将HIGH等级仓位从30%降至20%" },
  { type: "avoid_sector", reason: "银行板块胜率仅20.0%", action: "建议暂时回避银行板块" },
];

function mockOk(data: typeof adjustments) {
  hooks.useWinRateAdjustments.mockReturnValue({ data, isLoading: false, isError: false, error: null });
}
function mockEmpty() {
  hooks.useWinRateAdjustments.mockReturnValue({ data: [], isLoading: false, isError: false, error: null });
}
function mockLoading() {
  hooks.useWinRateAdjustments.mockReturnValue({ data: undefined, isLoading: true, isError: false, error: null });
}
function mockError() {
  hooks.useWinRateAdjustments.mockReturnValue({ data: undefined, isLoading: false, isError: true, error: new Error("x") });
}

describe("AdjustmentsCard (B4)", () => {
  beforeEach(() => vi.clearAllMocks());

  it("hook 收到 windowSize 入参", () => {
    mockOk(adjustments);
    render(<AdjustmentsCard windowSize={30} />);
    expect(hooks.useWinRateAdjustments).toHaveBeenCalledWith(30);
  });

  it("success → 渲染标题 + 每条建议的 type/reason/action", () => {
    mockOk(adjustments);
    render(<AdjustmentsCard windowSize={30} />);
    expect(screen.getByText("调整建议")).toBeInTheDocument();
    expect(screen.getByText("reduce_exposure")).toBeInTheDocument();
    expect(screen.getByText("胜率下降至30.0%，建议降低仓位")).toBeInTheDocument();
    expect(screen.getByText("将HIGH等级仓位从30%降至20%")).toBeInTheDocument();
    expect(screen.getByText("avoid_sector")).toBeInTheDocument();
    expect(screen.getByText("建议暂时回避银行板块")).toBeInTheDocument();
  });

  it("空数据 → 显示占位", () => {
    mockEmpty();
    render(<AdjustmentsCard windowSize={30} />);
    expect(screen.getByText("暂无调整建议")).toBeInTheDocument();
  });

  it("loading → 骨架态（无标题正文）", () => {
    mockLoading();
    render(<AdjustmentsCard windowSize={30} />);
    expect(screen.queryByText("调整建议")).not.toBeInTheDocument();
  });

  it("error → 显示占位", () => {
    mockError();
    render(<AdjustmentsCard windowSize={30} />);
    expect(screen.getByText("暂无调整建议")).toBeInTheDocument();
  });
});
