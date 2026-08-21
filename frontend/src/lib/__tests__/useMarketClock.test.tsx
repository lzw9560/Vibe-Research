// S092 T4+T5+T6 测试：dateTriplet fetch + useDateTriplet hook + useMarketClock 双定时器。
//
// 覆盖：
// - T5 useDateTriplet hook 加载（mock fetch 返回 dateTriplet，hook 返回正确 data）
// - T6 useMarketClock 延时计算（mock Date.now + 验证 setTimeout 调用 + 延时正确）
// - T6 non_trading 跳过 / is_manual 跳过 / delay<=0 跳过 / delay>12h 跳过
//
// vitest mock 惯例参照 hooks/useDebounce.test.ts（vi.useFakeTimers + renderHook）。

import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { renderHook, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import React from "react";

import { useDateTriplet } from "@/lib/query/workflow";
import { useMarketClock } from "@/lib/useMarketClock";

// ───────────────── helpers ─────────────────

function makeTriplet(overrides: Partial<{
  F: string; review: string; today: string; forward: string;
  stage: string; is_trading_day: boolean; review_advanced: boolean;
  server_now: string; next_review_advance_at: number; next_f_advance_at: number;
  non_trading: boolean;
}> = {}) {
  return {
    F: "2026-08-21",
    review: "2026-08-21",
    today: "2026-08-22",
    forward: "2026-08-22",
    stage: "post_market" as const,
    is_trading_day: true,
    review_advanced: true,
    server_now: "2026-08-21T18:00:00+08:00",
    next_review_advance_at: 1787554800,
    next_f_advance_at: 1787303700,
    non_trading: false,
    ...overrides,
  };
}

function wrapper(opts: { retry?: false } = {}) {
  const qc = new QueryClient({
    defaultOptions: { queries: { retry: opts.retry ?? false } },
  });
  function Wrapper({ children }: { children: React.ReactNode }) {
    return React.createElement(QueryClientProvider, { client: qc }, children);
  }
  return { qc, Wrapper };
}

// ───────────────── T5: useDateTriplet hook ─────────────────

describe("useDateTriplet (T5)", () => {
  // 注意：useDateTriplet 测试不用 fake timers——waitFor 内部轮询依赖 real timer，
  // fake timers 下 waitFor 永远不 resolve → 超时。
  beforeEach(() => {
    vi.spyOn(global, "fetch");
  });
  afterEach(() => {
    vi.restoreAllMocks();
  });

  it("loads dateTriplet from GET /api/workflow/date-triplet", async () => {
    const triplet = makeTriplet();
    (global.fetch as ReturnType<typeof vi.fn>).mockResolvedValue({
      ok: true,
      status: 200,
      json: async () => triplet,
    });
    const { result } = renderHook(() => useDateTriplet(), {
      wrapper: wrapper().Wrapper,
    });
    await waitFor(() => expect(result.current.isSuccess).toBe(true));
    expect(result.current.data).toEqual(triplet);
    expect(global.fetch).toHaveBeenCalledWith(
      "/api/workflow/date-triplet",
      expect.objectContaining({ method: "GET" }),
    );
  });

  it("passes date query when provided", async () => {
    (global.fetch as ReturnType<typeof vi.fn>).mockResolvedValue({
      ok: true, status: 200, json: async () => makeTriplet(),
    });
    const { result } = renderHook(() => useDateTriplet("2026-08-20"), {
      wrapper: wrapper().Wrapper,
    });
    await waitFor(() => expect(result.current.isSuccess).toBe(true));
    expect(global.fetch).toHaveBeenCalledWith(
      "/api/workflow/date-triplet?date=2026-08-20",
      expect.objectContaining({ method: "GET" }),
    );
  });
});

// ───────────────── T6: useMarketClock ─────────────────

describe("useMarketClock (T6)", () => {
  beforeEach(() => {
    vi.useFakeTimers();
  });
  afterEach(() => {
    vi.useRealTimers();
    vi.restoreAllMocks();
  });

  // mock Date.now 返回固定值（ms），让 next_*_at*1000 - now 可预测
  function fixNow(nowMs: number) {
    vi.spyOn(Date, "now").mockReturnValue(nowMs);
  }

  it("sets review timer with delay = next_review_advance_at*1000 - Date.now()", () => {
    const now = 1_000_000; // ms
    fixNow(now);
    const spy = vi.spyOn(global, "setTimeout");
    const { Wrapper } = wrapper();
    const onReview = vi.fn();
    renderHook(
      () => useMarketClock({
        next_review_advance_at: 1099, // 1_099_000ms - 1_000_000ms = 99_000ms
        next_f_advance_at: 1200,       // 1_200_000ms - 1_000_000ms = 200_000ms
        non_trading: false,
        is_manual: false,
        onReviewAdvance: onReview,
      }),
      { wrapper: Wrapper },
    );
    // 应有两个 setTimeout 调用（review 99_000ms + f 99_000ms）
    expect(spy).toHaveBeenCalled();
    const delays = spy.mock.calls.map((c) => c[1]);
    expect(delays).toContain(99_000);
    // 不应立即触发
    expect(onReview).not.toHaveBeenCalled();
    spy.mockRestore();
    // 清理：unmount 隐式由 renderHook 处理
  });

  it("fires onReviewAdvance + invalidates date-triplet at review timer fire", async () => {
    const now = 1_000_000;
    fixNow(now);
    const { qc, Wrapper } = wrapper();
    const onReview = vi.fn();
    const invalidateSpy = vi.spyOn(qc, "invalidateQueries");
    renderHook(
      () => useMarketClock({
        next_review_advance_at: 1099, // delay 99_000 ms
        next_f_advance_at: 2000,     // delay 1_000_000 ms（不触发）
        non_trading: false,
        is_manual: false,
        onReviewAdvance: onReview,
      }),
      { wrapper: Wrapper },
    );
    vi.advanceTimersByTime(99_000);
    expect(onReview).toHaveBeenCalledTimes(1);
    expect(invalidateSpy).toHaveBeenCalledWith({ queryKey: ["workflow", "date-triplet"] });
  });

  it("fires onFAdvance at 17:15 timer fire", () => {
    const now = 1_000_000;
    fixNow(now);
    const { Wrapper } = wrapper();
    const onF = vi.fn();
    renderHook(
      () => useMarketClock({
        next_review_advance_at: 2000,  // 不触发
        next_f_advance_at: 1099,         // delay 99_000 ms
        non_trading: false,
        is_manual: false,
        onFAdvance: onF,
      }),
      { wrapper: Wrapper },
    );
    vi.advanceTimersByTime(99_000);
    expect(onF).toHaveBeenCalledTimes(1);
  });

  it("skips both timers when non_trading=true", () => {
    const now = 1_000_000;
    fixNow(now);
    const spy = vi.spyOn(global, "setTimeout");
    const { Wrapper } = wrapper();
    renderHook(
      () => useMarketClock({
        next_review_advance_at: 1099,
        next_f_advance_at: 1200,
        non_trading: true,
        is_manual: false,
      }),
      { wrapper: Wrapper },
    );
    expect(spy).not.toHaveBeenCalled();
    spy.mockRestore();
  });

  it("skips both timers when is_manual=true", () => {
    const now = 1_000_000;
    fixNow(now);
    const spy = vi.spyOn(global, "setTimeout");
    const { Wrapper } = wrapper();
    renderHook(
      () => useMarketClock({
        next_review_advance_at: 1099,
        next_f_advance_at: 1200,
        non_trading: false,
        is_manual: true,
      }),
      { wrapper: Wrapper },
    );
    expect(spy).not.toHaveBeenCalled();
    spy.mockRestore();
  });

  it("skips timer when delay <= 0 (target already passed)", () => {
    const now = 200_000_000; // ms = 200_000 sec
    fixNow(now);
    const spy = vi.spyOn(global, "setTimeout");
    const { Wrapper } = wrapper();
    renderHook(
      () => useMarketClock({
        next_review_advance_at: 100, // 100_000 ms < now → delay <= 0 跳过
        next_f_advance_at: 150,        // 150_000 ms < now → delay 跳过
        non_trading: false,
        is_manual: false,
      }),
      { wrapper: Wrapper },
    );
    expect(spy).not.toHaveBeenCalled();
    spy.mockRestore();
  });

  it("skips timer when delay > 12h (anomalous next_*_at)", () => {
    const now = 1_000_000; // ms
    fixNow(now);
    const spy = vi.spyOn(global, "setTimeout");
    const { Wrapper } = wrapper();
    const twelve_hours_sec = 12 * 3600; // 43200 sec
    renderHook(
      () => useMarketClock({
        // delay = (now/1000 + twelve_hours_sec + 1)*1000 - now = 12h + 1000ms → 超限跳过
        next_review_advance_at: now / 1000 + twelve_hours_sec + 1,
        next_f_advance_at: now / 1000 + twelve_hours_sec + 1,
        non_trading: false,
        is_manual: false,
      }),
      { wrapper: Wrapper },
    );
    expect(spy).not.toHaveBeenCalled();
    spy.mockRestore();
  });

  it("clears timers on unmount (no callback fire after unmount)", () => {
    const now = 1_000_000;
    fixNow(now);
    const { Wrapper } = wrapper();
    const onReview = vi.fn();
    const { unmount } = renderHook(
      () => useMarketClock({
        next_review_advance_at: 1099,
        next_f_advance_at: 2000,
        non_trading: false,
        is_manual: false,
        onReviewAdvance: onReview,
      }),
      { wrapper: Wrapper },
    );
    unmount();
    vi.advanceTimersByTime(200_000);
    expect(onReview).not.toHaveBeenCalled();
  });
});
