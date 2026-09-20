// S221 gap2: WeeklyReviewPanel 测试——周度复盘渲染。
// actual P&L 趋势 + 4 周对比 + cap-down 提案（前端推算，mean<0）+ HonestEmptyState。
import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen } from "@testing-library/react";

const hooks = vi.hoisted(() => ({
  useSignalsManualTrades: vi.fn(),
  useSignalsStatus: vi.fn(),
  useWeeklyReview: vi.fn(),
}));

vi.mock("@/lib/query/signals", () => ({
  useSignalsManualTrades: hooks.useSignalsManualTrades,
  useSignalsStatus: hooks.useSignalsStatus,
  useWeeklyReview: hooks.useWeeklyReview,
}));

import { WeeklyReviewPanel } from "../WeeklyReviewPanel";
import type { ManualTradesResponse, SignalsStatusResponse } from "@/lib/api/types";

function mockTrade(over: Partial<{
  trade_id: string;
  code: string;
  actual_pnl: { pnl_pct: number | null; pnl_cny: number | null; status: string };
  reference_pnl: { pnl_pct: number | null; source: string };
  recorded_at: string;
  pnl_diff: { diff_pct: number | null; delivery_leak: boolean; leak_reason: string };
  delivery_leak: boolean;
}> = {}) {
  return {
    trade_id: "t1",
    code: "000001",
    actual_pnl: { pnl_pct: 1.2, pnl_cny: 126.0, status: "closed" },
    reference_pnl: { pnl_pct: 1.04, expected_return_pct: 1.04, source: "chrono_test_mean" },
    pnl_diff: { diff_pct: 0.16, delivery_leak: false, leak_reason: "" },
    delivery_leak: false,
    recorded_at: "2026-09-19T10:00:00",
    ...over,
  };
}

function mockStatus(): SignalsStatusResponse {
  return {
    regime: { current: "bull", freshness: { last_cache_date: "2026-09-19", stale: false, days_since: 0 } },
    arms: { consecutive_relay: { is_active: true, weight_override: null } },
  };
}

function setupTrades(trades: ReturnType<typeof mockTrade>[], cap: number = 1.0) {
  const resp: ManualTradesResponse = { trades, count: trades.length };
  hooks.useSignalsManualTrades.mockReturnValue({
    data: resp,
    isLoading: false,
    isError: false,
    error: null,
  });
  hooks.useSignalsStatus.mockReturnValue({
    data: { ...mockStatus(), arms: { consecutive_relay: { is_active: true, weight_override: cap } } },
    isLoading: false,
    isError: false,
    error: null,
  });
  hooks.useWeeklyReview.mockReturnValue({ data: { status: "no_reports" } });
}

function setupEmpty() {
  hooks.useSignalsManualTrades.mockReturnValue({
    data: { trades: [], count: 0 },
    isLoading: false,
    isError: false,
    error: null,
  });
  hooks.useSignalsStatus.mockReturnValue({
    data: mockStatus(),
    isLoading: false,
    isError: false,
    error: null,
  });
}

function setupLoading() {
  hooks.useSignalsManualTrades.mockReturnValue({ data: undefined, isLoading: true, isError: false, error: null });
  hooks.useSignalsStatus.mockReturnValue({ data: undefined, isLoading: true, isError: false, error: null });
}

describe("WeeklyReviewPanel (S221 gap2)", () => {
  beforeEach(() => vi.clearAllMocks());

  it("无数据 → HonestEmptyState 暂无已录实际交易", () => {
    setupEmpty();
    render(<WeeklyReviewPanel />);
    expect(screen.getByText(/暂无已录实际交易/)).toBeInTheDocument();
    expect(screen.getByText(/记录成交后显示/)).toBeInTheDocument();
  });

  it("loading → skeleton（不假装有数据）", () => {
    setupLoading();
    const { container } = render(<WeeklyReviewPanel />);
    // Loading 用 Loader2 animate-spin（非 animate-pulse），核 spinner 存在
    expect(container.querySelector(".animate-spin")).toBeTruthy();
  });

  it("有 closed trades mean<0 → 显示 cap-down 提案 + 前端推算标注", () => {
    setupTrades([
      mockTrade({ trade_id: "t1", actual_pnl: { pnl_pct: -1.5, pnl_cny: -150, status: "closed" }, recorded_at: "2026-09-19T10:00:00" }),
      mockTrade({ trade_id: "t2", actual_pnl: { pnl_pct: -0.5, pnl_cny: -50, status: "closed" }, recorded_at: "2026-09-18T10:00:00" }),
    ], 0.75);
    render(<WeeklyReviewPanel />);
    // cap-down 提案（mean=-1.0% < 0）
    expect(screen.getByText(/cap-down 提案/)).toBeInTheDocument();
    expect(screen.getByText(/前端推算/)).toBeInTheDocument();
  });

  it("有 closed trades mean>0 → 无 cap-down 提案，显示 P&L 趋势", () => {
    setupTrades([
      mockTrade({ trade_id: "t1", actual_pnl: { pnl_pct: 1.5, pnl_cny: 150, status: "closed" }, recorded_at: "2026-09-19T10:00:00" }),
    ], 1.0);
    render(<WeeklyReviewPanel />);
    // 无 cap-down（mean=1.5% > 0）
    expect(screen.queryByText(/cap-down 提案/)).not.toBeInTheDocument();
    // 有 P&L 趋势
    expect(screen.getByText(/实际 P&L 趋势/)).toBeInTheDocument();
  });

  it("有 closed trades → 显示 4 周对比区 + 交易明细", () => {
    setupTrades([
      mockTrade({ trade_id: "t1", code: "000001", actual_pnl: { pnl_pct: 1.5, pnl_cny: 150, status: "closed" }, recorded_at: "2026-09-19T10:00:00" }),
    ], 1.0);
    render(<WeeklyReviewPanel />);
    expect(screen.getByText(/4 周对比/)).toBeInTheDocument();
    expect(screen.getByText("000001")).toBeInTheDocument();
  });

  it("有 delivery_leak trade → 显示 leak 标记", () => {
    setupTrades([
      mockTrade({
        trade_id: "t1",
        code: "000001",
        actual_pnl: { pnl_pct: -2.0, pnl_cny: -200, status: "closed" },
        reference_pnl: { pnl_pct: 1.04, source: "chrono_test_mean" },
        pnl_diff: { diff_pct: -3.04, delivery_leak: true, leak_reason: "actual 远低于 reference -50%" },
        delivery_leak: true,
        recorded_at: "2026-09-19T10:00:00",
      }),
    ], 1.0);
    render(<WeeklyReviewPanel />);
    // "leak" 出现在 trade row badge + delivery leak 告警 → getAllByText 至少 1 处
    expect(screen.getAllByText(/leak/).length).toBeGreaterThan(0);
  });
});
