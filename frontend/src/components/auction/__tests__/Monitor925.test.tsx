// S025-E1 测试：Monitor925 9:25 盘中监控。
// fake timers：窗口内 15s 触发 refetch；窗口外显示快照+倒计时。
// 仿 limitup.test.tsx 的 api mock + QueryClientProvider 包装范式。
import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { render, screen, act } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import type { ReactNode } from "react";
import type { AuctionSignal } from "@/lib/api";

// vi.hoisted 保证 mock fn 引用在 factory 与测试间一致（vi.mock 提升不捕获顶层变量）。
const apiMocks = vi.hoisted(() => ({
  auctionMonitor: vi.fn<() => Promise<AuctionSignal[]>>(),
  auctionWatchlist: vi.fn<() => Promise<string[]>>(),
}));

vi.mock("@/lib/api", () => ({ api: apiMocks }));

import { Monitor925, getNextAuctionWindow } from "../Monitor925";

function newClient() {
  return new QueryClient({
    defaultOptions: {
      queries: { retry: false, gcTime: 0, refetchOnWindowFocus: false, staleTime: 0 },
    },
  });
}

function withClient(qc: QueryClient) {
  return ({ children }: { children: ReactNode }) => (
    <QueryClientProvider client={qc}>{children}</QueryClientProvider>
  );
}

const signals: AuctionSignal[] = [
  {
    code: "000001",
    name: "平安银行",
    signal_type: "高开",
    confidence: 0.8,
    open_premium: 2,
    volume_ratio: 1.5,
    reasoning: [],
  },
];
const watchlist = ["000001", "600000"];

describe("Monitor925 (E1)", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    apiMocks.auctionMonitor.mockResolvedValue(signals);
    apiMocks.auctionWatchlist.mockResolvedValue(watchlist);
  });
  afterEach(() => {
    vi.useRealTimers();
  });

  it("窗口内 → 渲染 monitor 信号 + watchlist + 实时标记", async () => {
    vi.useFakeTimers({ now: new Date(2026, 7, 3, 9, 20, 0) }); // 周一 9:20
    const qc = newClient();
    render(<Monitor925 />, { wrapper: withClient(qc) });

    // flush 初始 fetch
    await act(async () => {
      await vi.advanceTimersByTimeAsync(0);
    });
    expect(apiMocks.auctionMonitor).toHaveBeenCalledTimes(1);
    expect(apiMocks.auctionWatchlist).toHaveBeenCalledTimes(1);
    // 实时标记
    expect(screen.getByText("实时监控中")).toBeInTheDocument();
    // monitor 信号渲染
    expect(screen.getByText("平安银行")).toBeInTheDocument();
    // watchlist 渲染（600000 仅在 watchlist）
    expect(screen.getByText("600000")).toBeInTheDocument();
  });

  it("窗口内 15s → 触发 refetch（api 再调一次）", async () => {
    vi.useFakeTimers({ now: new Date(2026, 7, 3, 9, 20, 0) }); // 周一 9:20
    const qc = newClient();
    render(<Monitor925 />, { wrapper: withClient(qc) });

    await act(async () => {
      await vi.advanceTimersByTimeAsync(0);
    });
    expect(apiMocks.auctionMonitor).toHaveBeenCalledTimes(1);

    // 推进 15s → react-query refetchInterval 触发 refetch
    await act(async () => {
      await vi.advanceTimersByTimeAsync(15_000);
    });
    expect(apiMocks.auctionMonitor).toHaveBeenCalledTimes(2);
    expect(apiMocks.auctionWatchlist).toHaveBeenCalledTimes(2);
  });

  it("窗口外 → 显示快照 + 倒计时，无自动 refetch", async () => {
    vi.useFakeTimers({ now: new Date(2026, 7, 3, 10, 0, 0) }); // 周一 10:00
    const qc = newClient();
    render(<Monitor925 />, { wrapper: withClient(qc) });

    await act(async () => {
      await vi.advanceTimersByTimeAsync(0);
    });
    expect(apiMocks.auctionMonitor).toHaveBeenCalledTimes(1);
    // 快照仍显示数据
    expect(screen.getByText("快照模式")).toBeInTheDocument();
    expect(screen.getByText("平安银行")).toBeInTheDocument();
    // 倒计时
    expect(screen.getByText(/距下次竞价窗口/)).toBeInTheDocument();
    // 推进 30s 不触发 refetch（refetchInterval=false 在窗口外）
    await act(async () => {
      await vi.advanceTimersByTimeAsync(30_000);
    });
    expect(apiMocks.auctionMonitor).toHaveBeenCalledTimes(1);
  });
});

describe("getNextAuctionWindow", () => {
  it("周一 10:00 → 次日(周二) 9:15", () => {
    const now = new Date(2026, 7, 3, 10, 0, 0); // 周一
    const next = getNextAuctionWindow(now);
    expect(next.getDay()).toBe(2); // 周二
    expect(next.getHours()).toBe(9);
    expect(next.getMinutes()).toBe(15);
  });

  it("周一 8:00 → 当日 9:15", () => {
    const now = new Date(2026, 7, 3, 8, 0, 0); // 周一 9:15 前
    const next = getNextAuctionWindow(now);
    expect(next.getDay()).toBe(1); // 周一
    expect(next.getHours()).toBe(9);
    expect(next.getMinutes()).toBe(15);
  });

  it("周五 10:00 → 下周一 9:15", () => {
    const now = new Date(2026, 7, 7, 10, 0, 0); // 周五
    const next = getNextAuctionWindow(now);
    expect(next.getDay()).toBe(1); // 周一
    expect(next.getDate()).toBe(10); // 8月10日
  });

  it("周六 12:00 → 下周一 9:15", () => {
    const now = new Date(2026, 7, 8, 12, 0, 0); // 周六
    const next = getNextAuctionWindow(now);
    expect(next.getDay()).toBe(1); // 周一
    expect(next.getDate()).toBe(10); // 8月10日
  });
});
