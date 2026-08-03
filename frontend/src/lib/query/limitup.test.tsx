// S025-A 测试：winrate/auction react-query hooks（仿 useAuctionTop 范式）。
// 验证 queryKey/queryFn 接线、mutation invalidate、竞价窗口判定。
import { describe, it, expect, vi, beforeEach } from "vitest";
import { renderHook, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import type { ReactNode } from "react";
import type {
  WinRateRecordInput,
  WinRateRecordsResponse,
  WinRateStats,
  AuctionSignal,
} from "@/lib/api";

// vi.hoisted 保证 mock fn 引用在 factory 与测试间一致（vi.mock 提升不捕获顶层变量）。
const apiMocks = vi.hoisted(() => ({
  winRateStats: vi.fn<(w?: number) => Promise<WinRateStats>>(),
  winRateTrends: vi.fn<(w?: number) => Promise<unknown[]>>(),
  winRateAdjustments: vi.fn<(w?: number) => Promise<unknown>>(),
  winRateSector: vi.fn<(s: string, w?: number) => Promise<unknown>>(),
  winRateStrategy: vi.fn<(s: string, w?: number) => Promise<unknown>>(),
  winRateRecords: vi.fn<(r: WinRateRecordInput[]) => Promise<WinRateRecordsResponse>>(),
  auctionMonitor: vi.fn<() => Promise<AuctionSignal[]>>(),
  auctionWatchlist: vi.fn<() => Promise<string[]>>(),
}));

vi.mock("@/lib/api", () => ({ api: apiMocks }));

import {
  useWinRateStats,
  useWinRateTrends,
  useWinRateAdjustments,
  useWinRateSector,
  useWinRateStrategy,
  useWinRateRecords,
  useAuctionMonitor,
  isInAuctionWindow,
} from "@/lib/query/limitup";

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

const emptyStats = (w: number): WinRateStats => ({
  window_size: w,
  total_trades: 0,
  win_count: 0,
  win_rate: 0,
  avg_return: 0,
  max_drawdown: 0,
  sharpe_ratio: 0,
  trend: "stable",
  sector_breakdown: {},
  strategy_breakdown: {},
  score_breakdown: {},
});

describe("useWinRateStats (A3)", () => {
  beforeEach(() => vi.clearAllMocks());

  it("queryKey 含 windowSize，queryFn 调 api.winRateStats(windowSize)", async () => {
    apiMocks.winRateStats.mockResolvedValue(emptyStats(30));
    const qc = newClient();
    const { result } = renderHook(() => useWinRateStats(30), { wrapper: withClient(qc) });

    await waitFor(() => expect(result.current.isSuccess).toBe(true));
    expect(apiMocks.winRateStats).toHaveBeenCalledWith(30);
    expect(result.current.data?.window_size).toBe(30);
    expect(qc.getQueryData(["limitup", "winrate", "stats", 30])).toBeTruthy();
  });

  it("切 windowSize → 新 queryKey → 重查", async () => {
    apiMocks.winRateStats.mockResolvedValue(emptyStats(7));
    const qc = newClient();
    const { result, rerender } = renderHook(({ w }: { w: number }) => useWinRateStats(w), {
      wrapper: withClient(qc),
      initialProps: { w: 7 },
    });
    await waitFor(() => expect(result.current.isSuccess).toBe(true));
    expect(apiMocks.winRateStats).toHaveBeenCalledWith(7);

    apiMocks.winRateStats.mockResolvedValue(emptyStats(30));
    rerender({ w: 30 });
    await waitFor(() => expect(apiMocks.winRateStats).toHaveBeenCalledWith(30));
    // 新 windowSize 落到独立 queryKey（旧 key 在 gcTime:0 下被回收，不在此断言）
    expect(qc.getQueryData(["limitup", "winrate", "stats", 30])).toBeTruthy();
  });
});

describe("useWinRateTrends (A3)", () => {
  beforeEach(() => vi.clearAllMocks());

  it("queryFn 调 api.winRateTrends(windowSize)", async () => {
    const trends = [{ date: "2026-08-01", total_trades: 3, win_count: 2, win_rate: 0.66 }];
    apiMocks.winRateTrends.mockResolvedValue(trends);
    const qc = newClient();
    const { result } = renderHook(() => useWinRateTrends(30), { wrapper: withClient(qc) });

    await waitFor(() => expect(result.current.isSuccess).toBe(true));
    expect(apiMocks.winRateTrends).toHaveBeenCalledWith(30);
    expect(result.current.data).toEqual(trends);
  });
});

describe("useWinRateAdjustments (A3)", () => {
  beforeEach(() => vi.clearAllMocks());

  it("queryFn 调 api.winRateAdjustments(windowSize)", async () => {
    const adj = [{ type: "reduce_exposure", reason: "胜率下降", action: "降仓" }];
    apiMocks.winRateAdjustments.mockResolvedValue(adj);
    const qc = newClient();
    const { result } = renderHook(() => useWinRateAdjustments(30), { wrapper: withClient(qc) });

    await waitFor(() => expect(result.current.isSuccess).toBe(true));
    expect(apiMocks.winRateAdjustments).toHaveBeenCalledWith(30);
    expect(result.current.data).toEqual(adj);
  });
});

describe("useWinRateSector (A3)", () => {
  beforeEach(() => vi.clearAllMocks());

  it("sector 非空 → queryFn 调 api.winRateSector(sector, windowSize)", async () => {
    const stats = { sector: "银行", total_trades: 5, win_count: 3, win_rate: 0.6, avg_return: 1.2 };
    apiMocks.winRateSector.mockResolvedValue(stats);
    const qc = newClient();
    const { result } = renderHook(() => useWinRateSector("银行", 30), { wrapper: withClient(qc) });

    await waitFor(() => expect(result.current.isSuccess).toBe(true));
    expect(apiMocks.winRateSector).toHaveBeenCalledWith("银行", 30);
    expect(result.current.data).toEqual(stats);
  });

  it("sector 为空 → enabled=false → 不调 queryFn", async () => {
    const qc = newClient();
    const { result } = renderHook(() => useWinRateSector("", 30), { wrapper: withClient(qc) });
    // 等一个微任务，确认不发起请求
    await new Promise((r) => setTimeout(r, 0));
    expect(apiMocks.winRateSector).not.toHaveBeenCalled();
    expect(result.current.fetchStatus).toBe("idle");
  });
});

describe("useWinRateStrategy (A3)", () => {
  beforeEach(() => vi.clearAllMocks());

  it("strategy 非空 → queryFn 调 api.winRateStrategy(strategy, windowSize)", async () => {
    const stats = { strategy: "打板", total_trades: 4, win_count: 2, win_rate: 0.5, avg_return: 0.8 };
    apiMocks.winRateStrategy.mockResolvedValue(stats);
    const qc = newClient();
    const { result } = renderHook(() => useWinRateStrategy("打板", 30), { wrapper: withClient(qc) });

    await waitFor(() => expect(result.current.isSuccess).toBe(true));
    expect(apiMocks.winRateStrategy).toHaveBeenCalledWith("打板", 30);
    expect(result.current.data).toEqual(stats);
  });

  it("strategy 为空 → enabled=false → 不调 queryFn", async () => {
    const qc = newClient();
    const { result } = renderHook(() => useWinRateStrategy("", 30), { wrapper: withClient(qc) });
    await new Promise((r) => setTimeout(r, 0));
    expect(apiMocks.winRateStrategy).not.toHaveBeenCalled();
    expect(result.current.fetchStatus).toBe("idle");
  });
});

describe("useWinRateRecords (A4)", () => {
  beforeEach(() => vi.clearAllMocks());

  it("mutateAsync 调 api.winRateRecords 并 invalidate winrate 查询前缀", async () => {
    const okRes: WinRateRecordsResponse = {
      added: ["000001"],
      added_count: 1,
      errors: [],
      error_count: 0,
    };
    apiMocks.winRateRecords.mockResolvedValue(okRes);
    const qc = newClient();
    const invalidateSpy = vi.spyOn(qc, "invalidateQueries");

    const { result } = renderHook(() => useWinRateRecords(), { wrapper: withClient(qc) });
    const record: WinRateRecordInput = {
      stock_code: "000001",
      entry_date: "2026-08-01",
      exit_date: "2026-08-02",
    };

    await result.current.mutateAsync([record]);
    await waitFor(() => expect(invalidateSpy).toHaveBeenCalled());

    expect(apiMocks.winRateRecords).toHaveBeenCalledWith([record]);
    expect(invalidateSpy).toHaveBeenCalledWith({ queryKey: ["limitup", "winrate"] });
  });
});

describe("isInAuctionWindow (A5)", () => {
  // refetchInterval = () => isInAuctionWindow() ? 15000 : false；
  // 此处直接测试驱动 refetchInterval 的判定谓词，覆盖 15000 与 false 两条路径。
  it("周一 9:20 在窗口内", () => {
    expect(isInAuctionWindow(new Date(2026, 7, 3, 9, 20, 0))).toBe(true); // 2026-08-03 Mon
  });
  it("周一 9:15 边界在窗口内", () => {
    expect(isInAuctionWindow(new Date(2026, 7, 3, 9, 15, 0))).toBe(true);
  });
  it("周一 9:30 边界在窗口内", () => {
    expect(isInAuctionWindow(new Date(2026, 7, 3, 9, 30, 0))).toBe(true);
  });
  it("周一 9:31 出窗口", () => {
    expect(isInAuctionWindow(new Date(2026, 7, 3, 9, 31, 0))).toBe(false);
  });
  it("周一 9:14 出窗口", () => {
    expect(isInAuctionWindow(new Date(2026, 7, 3, 9, 14, 0))).toBe(false);
  });
  it("周一 14:00 出窗口", () => {
    expect(isInAuctionWindow(new Date(2026, 7, 3, 14, 0, 0))).toBe(false);
  });
  it("周六 9:20 出窗口（周末）", () => {
    expect(isInAuctionWindow(new Date(2026, 7, 8, 9, 20, 0))).toBe(false); // Sat
  });
  it("周日 9:20 出窗口（周末）", () => {
    expect(isInAuctionWindow(new Date(2026, 7, 9, 9, 20, 0))).toBe(false); // Sun
  });
  it("默认参数用当前时间（不抛错）", () => {
    expect(typeof isInAuctionWindow()).toBe("boolean");
  });
});

describe("useAuctionMonitor (A5)", () => {
  beforeEach(() => vi.clearAllMocks());

  it("并行调 auctionMonitor + auctionWatchlist，返回 [signals, watchlist] tuple", async () => {
    const signals: AuctionSignal[] = [
      {
        code: "000001",
        name: "平安",
        signal_type: "高开",
        confidence: 0.8,
        open_premium: 2,
        volume_ratio: 1.5,
        reasoning: [],
      },
    ];
    apiMocks.auctionMonitor.mockResolvedValue(signals);
    apiMocks.auctionWatchlist.mockResolvedValue(["000001", "600000"]);
    const qc = newClient();
    const { result } = renderHook(() => useAuctionMonitor(), { wrapper: withClient(qc) });

    await waitFor(() => expect(result.current.isSuccess).toBe(true));
    expect(apiMocks.auctionMonitor).toHaveBeenCalledTimes(1);
    expect(apiMocks.auctionWatchlist).toHaveBeenCalledTimes(1);
    expect(result.current.data?.[0]).toEqual(signals);
    expect(result.current.data?.[1]).toEqual(["000001", "600000"]);
    expect(qc.getQueryData(["limitup", "auction", "monitor"])).toBeTruthy();
  });
});
