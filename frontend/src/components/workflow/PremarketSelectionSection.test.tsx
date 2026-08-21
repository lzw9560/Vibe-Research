// S090 A PremarketSelectionSection 测试——loading/error/empty/有候选/date fallback。
import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen } from "@testing-library/react";
import { PremarketSelectionSection } from "./PremarketSelectionSection";

vi.mock("@/lib/query/premarket", () => ({
  usePremarketSelection: vi.fn(),
}));
import { usePremarketSelection } from "@/lib/query/premarket";

const mockUse = usePremarketSelection as ReturnType<typeof vi.fn>;

const sampleData = {
  target_date: "2026-08-21",
  honest_label: "弱信号",
  risk_params: {
    position_pct: 30,
    max_positions: 3,
    stop_loss_pct: -5,
    take_profit_pct: 10,
    max_hold_days: 3,
  },
  calendar_multiplier: 1,
  calendar_reason: "",
  market_note: "正常",
  candidates: [
    {
      code: "000001",
      name: "平安银行",
      breakout_score: 0.95,
      breakout_binary: 1,
      t1_close: 12.5,
      t1_date: "2026-08-20",
      entry_ref: 12.5,
      stop_loss: 11.88,
      take_profit: 13.75,
      position_pct: 30,
    },
  ],
  count: 1,
};

describe("PremarketSelectionSection", () => {
  beforeEach(() => mockUse.mockReset());

  it("loading 态不渲染候选表", () => {
    mockUse.mockReturnValue({ isLoading: true });
    render(<PremarketSelectionSection date="2026-08-21" />);
    expect(screen.queryByText("盘前选股")).not.toBeInTheDocument();
  });

  it("error 态显示失败文案", () => {
    mockUse.mockReturnValue({ isLoading: false, error: new Error("boom"), refetch: vi.fn() });
    render(<PremarketSelectionSection date="2026-08-21" />);
    expect(screen.getByText(/加载失败/)).toBeInTheDocument();
  });

  it("empty 态显示无候选", () => {
    mockUse.mockReturnValue({
      isLoading: false,
      data: { ...sampleData, candidates: [] },
      error: null,
    });
    render(<PremarketSelectionSection date="2026-08-21" />);
    expect(screen.getByText(/无候选/)).toBeInTheDocument();
  });

  it("有候选展示 code/name/breakout/风控/honest", () => {
    mockUse.mockReturnValue({ isLoading: false, data: sampleData, error: null });
    render(<PremarketSelectionSection date="2026-08-21" />);
    expect(screen.getByText("盘前选股")).toBeInTheDocument();
    expect(screen.getByText("弱信号")).toBeInTheDocument();
    expect(screen.getByText("000001")).toBeInTheDocument();
    expect(screen.getByText("平安银行")).toBeInTheDocument();
    expect(screen.getByText("仓位 30%")).toBeInTheDocument();
    expect(screen.getByText("止损 -5%")).toBeInTheDocument();
    expect(screen.getByText("止盈 10%")).toBeInTheDocument();
  });

  it("date undefined → 显示加载态（等待 dateTriplet），不臆造日期", () => {
    mockUse.mockReturnValue({ isLoading: true });
    render(<PremarketSelectionSection />);
    // date undefined 时不调 hook（不臆造 toISOString），显示加载态
    expect(mockUse).not.toHaveBeenCalled();
  });

  it("日历倍率 ≠1 时展示倍率 + reason", () => {
    mockUse.mockReturnValue({
      isLoading: false,
      data: { ...sampleData, calendar_multiplier: 0.7, calendar_reason: "周五×0.7" },
      error: null,
    });
    render(<PremarketSelectionSection date="2026-08-21" />);
    expect(screen.getByText(/日历 ×0.7/)).toBeInTheDocument();
    expect(screen.getByText(/周五×0.7/)).toBeInTheDocument();
  });
});
