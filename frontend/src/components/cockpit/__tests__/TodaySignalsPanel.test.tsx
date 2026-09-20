// S218 #9: TodaySignalsPanel 测试——渲染三 bucket + 记录成交 modal + POST 触发。
import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, fireEvent, waitFor } from "@testing-library/react";

const hooks = vi.hoisted(() => ({
  useSignalsDaily: vi.fn(),
  useRecordManualTrade: vi.fn(),
  useSignalsManualTrades: vi.fn(),
  useDeliveryFireStatus: vi.fn(),
}));

vi.mock("@/lib/query/signals", () => ({
  useSignalsDaily: hooks.useSignalsDaily,
  useRecordManualTrade: hooks.useRecordManualTrade,
  useSignalsManualTrades: hooks.useSignalsManualTrades,
  useDeliveryFireStatus: hooks.useDeliveryFireStatus,
}));

// Sheet 用 createPortal——mock 掉 react-dom createPortal 让内容直接渲染到 container。
vi.mock("react-dom", () => {
  const actual = vi.importActual("react-dom");
  return {
    ...actual,
    createPortal: (node: React.ReactNode) => node,
  };
});

import { TodaySignalsPanel } from "../TodaySignalsPanel";
import type { SignalsDailyResponse, ManualTradeResponse } from "@/lib/api/types";

// 构造一个含 tradable + exploratory + avoid 三 bucket 的 daily 响应
function mockDailyResponse(): SignalsDailyResponse {
  return {
    date: "2026-09-19",
    arm: "consecutive_relay",
    regime: {
      current: "bull",
      edge_status: "bull validated（train 1.57%→test 1.04%，p=0.0054）",
      freshness: { last_cache_date: "2026-09-19", stale: false, days_since: 0, n_dates: 100 },
    },
    cap: { effective: 0.75, base: 1.0, decay: 0.75, regime_factor: 1.0, zuoT_factor: 1.0, note: "bull" },
    hardstop: { active: false, reason: null },
    filters: { total_scanned: 5, tradable: 1, exploratory: 1, avoid: 1 },
    signals: [
      {
        code: "000001", name: "平安银行", lbc: 2, entry_price: 10.50,
        price_source: "2026-09-19", unbuyable: false, bucket: "tradable", hardstop_reason: null,
      },
      {
        code: "000002", name: "万科A", lbc: 2, entry_price: 8.20,
        price_source: "2026-09-19", unbuyable: false, bucket: "exploratory", hardstop_reason: null,
      },
      {
        code: "000003", name: "一字板股", lbc: 3, entry_price: 5.00,
        price_source: "2026-09-19", unbuyable: true, bucket: "avoid", hardstop_reason: null,
      },
    ],
    verified_numbers: {
      chrono_train: 1.57, chrono_test: 1.04, chrono_decay_pct: 34,
      chrono_p: 0.0054, chrono_wr: 52.7, deep_dive_lbc2: 0.90, deep_dive_lbc3: 2.05,
    },
    disclaimers: ["统计验证（非已实现收益）—— edge 衰减中", "paper-only 无券商"],
  };
}

function mockHardstopResponse() {
  const base = mockDailyResponse();
  return {
    ...base,
    regime: { ...base.regime, current: "bear" },
    cap: { ...base.cap, effective: 0.5 },
    hardstop: { active: true, reason: "regime_cache_stale_hardstop：cache last-date=unknown" },
    signals: base.signals.map((s) => ({
      ...s,
      bucket: "exploratory" as const,
      hardstop_reason: "regime_cache_stale_hardstop",
    })),
  };
}

// mutation mock：返 { mutate, isPending, data, error }，mutate 调 onSuccess 回 result
function mockMutation() {
  const result = {
    trade_id: "manual_abc123",
    code: "000001",
    actual_pnl: { pnl_pct: 1.2, pnl_cny: 126.0, status: "closed" },
    reference_pnl: { pnl_pct: 1.04, expected_return_pct: 1.04, source: "chrono_test_mean_1.04pct" },
    pnl_diff: { diff_pct: 0.16, delivery_leak: false, leak_reason: "" },
    delivery_leak: false,
    recorded_at: "2026-09-19T10:00:00",
  };
  return {
    mutate: vi.fn((_body, opts) => {
      (opts as any)?.onSuccess?.(result);
    }),
    mutateAsync: vi.fn(),
    isPending: false,
    isIdle: true,
    isError: false,
    data: result,
    error: null,
  };
}

function setupDaily(mockData: ReturnType<typeof mockDailyResponse> | undefined = mockDailyResponse()) {
  hooks.useSignalsDaily.mockReturnValue({
    data: mockData,
    isLoading: false,
    isError: false,
    error: null,
  });
}

function setupLoading() {
  hooks.useSignalsDaily.mockReturnValue({ data: undefined, isLoading: true, isError: false, error: null });
}

describe("TodaySignalsPanel (S218 #9)", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    hooks.useRecordManualTrade.mockReturnValue(mockMutation());
    // S221 gap3: 默认无回录交易（无 diff 显示）
    hooks.useSignalsManualTrades.mockReturnValue({
      data: { trades: [], count: 0 },
      isLoading: false,
      isError: false,
      error: null,
    });
    // S221 gap1: DeliveryStatusCard 默认 pending 态
    hooks.useDeliveryFireStatus.mockReturnValue({
      data: [],
      dailyReport: null,
      weeklyReview: null,
      isLoading: false,
      isError: false,
      error: null,
    });
  });

  it("renders loading spinner", () => {
    setupLoading();
    render(<TodaySignalsPanel />);
    expect(document.body.innerHTML).toContain("加载今日信号");
  });

  it("renders date + regime + effective cap in header", () => {
    setupDaily();
    render(<TodaySignalsPanel />);
    expect(screen.getByText(/2026-09-19/)).toBeInTheDocument();
    expect(screen.getByText(/bull ×0\.75/)).toBeInTheDocument();
  });

  it("renders honesty strings: 统计验证/非已实现收益 + paper-only + 照做有风险", () => {
    setupDaily();
    render(<TodaySignalsPanel />);
    // 这些串出现在 honor banner + disclaimers 列表两处，用 getAllByText
    expect(screen.getAllByText(/统计验证（非已实现收益）/).length).toBeGreaterThan(0);
    expect(screen.getAllByText(/paper-only 无券商/).length).toBeGreaterThan(0);
    expect(screen.getAllByText(/照做有风险/).length).toBeGreaterThan(0);
  });

  it("renders tradable + exploratory + avoid buckets with code/name/参考价", () => {
    setupDaily();
    render(<TodaySignalsPanel />);
    // tradable
    expect(screen.getByText("000001")).toBeInTheDocument();
    expect(screen.getByText("平安银行")).toBeInTheDocument();
    expect(screen.getByText(/¥10\.50/)).toBeInTheDocument();
    // exploratory
    expect(screen.getByText("000002")).toBeInTheDocument();
    expect(screen.getByText("万科A")).toBeInTheDocument();
    expect(screen.getByText("探索性")).toBeInTheDocument();
    // avoid（一字板）
    expect(screen.getByText("000003")).toBeInTheDocument();
    expect(screen.getByText("一字板")).toBeInTheDocument();
  });

  it("renders filters honesty count: 扫描 5 → 1 可做 / 1 探索性 / 1 别碰", () => {
    setupDaily();
    render(<TodaySignalsPanel />);
    expect(screen.getByText(/扫描 5 只 → 1 可做/)).toBeInTheDocument();
    expect(screen.getByText(/1 探索性/)).toBeInTheDocument();
    expect(screen.getByText(/1 别碰/)).toBeInTheDocument();
  });

  it("renders verified chrono numbers: train 1.57% + test 1.04% + 衰减 34% + WR 52.7%", () => {
    setupDaily();
    render(<TodaySignalsPanel />);
    // 1.57%/1.04% 也出现在 edge_status 段，用 getAllByText 断言至少 1 处
    expect(screen.getAllByText(/1\.57%/).length).toBeGreaterThan(0);
    expect(screen.getAllByText(/1\.04%/).length).toBeGreaterThan(0);
    expect(screen.getAllByText(/-34%/).length).toBeGreaterThan(0);
    expect(screen.getAllByText(/52\.7%/).length).toBeGreaterThan(0);
  });

  it("hardstop active → shows hard-stop banner + 0 tradable honesty", () => {
    setupDaily(mockHardstopResponse());
    render(<TodaySignalsPanel />);
    expect(screen.getByText(/hard-stop 触发/)).toBeInTheDocument();
    // bear cap
    expect(screen.getByText(/bear ×0\.5/)).toBeInTheDocument();
  });

  it("记录成交 button → opens Sheet modal pre-filled with code + reference_signal_id", () => {
    setupDaily();
    render(<TodaySignalsPanel />);
    // 点 tradable 第一条的"记录成交"
    const buttons = screen.getAllByRole("button", { name: /记录成交/ });
    expect(buttons.length).toBeGreaterThan(0);
    fireEvent.click(buttons[0]);
    // Sheet 打开，标题 + 预填只读信号摘要（关联信号 id）
    expect(screen.getByText("记录实际成交")).toBeInTheDocument();
    expect(
      screen.getByText(/consecutive_relay_2026-09-19_000001/),
    ).toBeInTheDocument();
  });

  it("submit calls mutate with code/entry_price/entry_time/followed_reference=true", async () => {
    setupDaily();
    const mutation = mockMutation();
    hooks.useRecordManualTrade.mockReturnValue(mutation);
    render(<TodaySignalsPanel />);
    fireEvent.click(screen.getAllByRole("button", { name: /记录成交/ })[0]);
    // entry_price 已预填参考价 10.50；entry_time 预填 09:30
    // 直接点提交
    fireEvent.click(screen.getByRole("button", { name: /提交成交记录/ }));
    await waitFor(() => {
      expect(mutation.mutate).toHaveBeenCalledTimes(1);
    });
    const body = mutation.mutate.mock.calls[0][0];
    expect(body.code).toBe("000001");
    expect(body.entry_price).toBe(10.5);
    expect(body.followed_reference).toBe(true);
    expect(body.reference_signal_id).toBe("consecutive_relay_2026-09-19_000001");
    expect(body.entry_time).toContain("2026-09-19");
  });

  it("submit shows trade_id + actual_pnl + delivery_leak result after success", async () => {
    setupDaily();
    render(<TodaySignalsPanel />);
    fireEvent.click(screen.getAllByRole("button", { name: /记录成交/ })[0]);
    fireEvent.click(screen.getByRole("button", { name: /提交成交记录/ }));
    await waitFor(() => {
      expect(screen.getByText(/manual_abc123/)).toBeInTheDocument();
    });
    expect(screen.getByText(/实际 P&L：1\.2/)).toBeInTheDocument();
  });

  it("rejects submit when entry_price missing → shows error", async () => {
    setupDaily();
    const mutation = mockMutation();
    hooks.useRecordManualTrade.mockReturnValue(mutation);
    render(<TodaySignalsPanel />);
    fireEvent.click(screen.getAllByRole("button", { name: /记录成交/ })[0]);
    // 清空预填的 entry_price
    const priceInput = screen.getByLabelText(/实际买入价/) as HTMLInputElement;
    fireEvent.change(priceInput, { target: { value: "" } });
    fireEvent.click(screen.getByRole("button", { name: /提交成交记录/ }));
    await waitFor(() => {
      expect(screen.getByTestId("manual-trade-error")).toBeInTheDocument();
    });
    expect(mutation.mutate).not.toHaveBeenCalled();
  });
});

// S221 gap3: delivery leak 标记——SignalRow 按 code 匹配 manual trade，显示 diff + leak badge。
describe("TodaySignalsPanel delivery leak marker (S221 gap3)", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    hooks.useRecordManualTrade.mockReturnValue(mockMutation());
    hooks.useDeliveryFireStatus.mockReturnValue({
      data: [],
      dailyReport: null,
      weeklyReview: null,
      isLoading: false,
      isError: false,
      error: null,
    });
  });

  it("matched trade + delivery_leak=true → 红色 leak badge + diff 文本", () => {
    setupDaily();
    const leakTrade: ManualTradeResponse = {
      trade_id: "t1",
      code: "000001",
      actual_pnl: { pnl_pct: -2.0, pnl_cny: -200, status: "closed" },
      reference_pnl: { pnl_pct: 1.04, expected_return_pct: 1.04, source: "chrono_test_mean" },
      pnl_diff: { diff_pct: -3.04, delivery_leak: true, leak_reason: "actual 远低于 reference -50%" },
      delivery_leak: true,
      recorded_at: "2026-09-19T10:00:00",
    };
    hooks.useSignalsManualTrades.mockReturnValue({
      data: { trades: [leakTrade], count: 1 },
      isLoading: false,
      isError: false,
      error: null,
    });
    render(<TodaySignalsPanel />);
    // tradable 第一条 code=000001 匹配 leakTrade → 显示 leak badge
    expect(screen.getByText(/leak/)).toBeInTheDocument();
  });

  it("matched trade + delivery_leak=false → 显示 diff 文本，无 leak badge", () => {
    setupDaily();
    const okTrade: ManualTradeResponse = {
      trade_id: "t1",
      code: "000001",
      actual_pnl: { pnl_pct: 1.2, pnl_cny: 126.0, status: "closed" },
      reference_pnl: { pnl_pct: 1.04, expected_return_pct: 1.04, source: "chrono_test_mean" },
      pnl_diff: { diff_pct: 0.16, delivery_leak: false, leak_reason: "" },
      delivery_leak: false,
      recorded_at: "2026-09-19T10:00:00",
    };
    hooks.useSignalsManualTrades.mockReturnValue({
      data: { trades: [okTrade], count: 1 },
      isLoading: false,
      isError: false,
      error: null,
    });
    render(<TodaySignalsPanel />);
    // 非 leak → 内 span 显示 +1.20%（actual_pnl），无红色 leak badge
    expect(screen.getByText("+1.20%")).toBeInTheDocument();
    expect(screen.queryByText(/leak/)).not.toBeInTheDocument();
  });

  it("无 matched trade → 不显示 diff（诚实不臆造）", () => {
    setupDaily();
    // 默认 beforeEach 已设 trades=[] → 无匹配
    render(<TodaySignalsPanel />);
    // 信号 000001 在 tradable，但无 manual trade → 不显示 diff/leak
    expect(screen.queryByText(/leak/)).not.toBeInTheDocument();
  });
});
