// TDD for makeIntradayInterval — gating + staggering helper (direction 4).
//
// isTradingHours 的真实实现读北京墙钟时间，测试里不可控；此处用 vi.hoisted +
// vi.mock 把 @/hooks/useLiveQuotes 整模块替换成可变桩，按用例切换 true/false。
import { describe, it, expect, vi, beforeEach } from "vitest";

// 可变桩：beforeEach / 用例里改 isTradingHours 返回值，断言 gating 行为。
const tradingHoursMock = vi.hoisted(() => ({
  isTradingHours: (): boolean => true,
}));

vi.mock("@/hooks/useLiveQuotes", () => ({
  isTradingHours: () => tradingHoursMock.isTradingHours(),
}));

import { makeIntradayInterval } from "@/lib/query/intraday";

describe("makeIntradayInterval", () => {
  beforeEach(() => {
    tradingHoursMock.isTradingHours = (): boolean => true;
  });

  it("returns a function (TanStack refetchInterval contract)", () => {
    expect(typeof makeIntradayInterval(60_000)).toBe("function");
  });

  it("returns the given ms during trading hours (keep polling)", () => {
    tradingHoursMock.isTradingHours = (): boolean => true;
    const interval = makeIntradayInterval(60_000);
    expect(interval()).toBe(60_000);
  });

  it("returns false outside trading hours (stop refetch)", () => {
    tradingHoursMock.isTradingHours = (): boolean => false;
    const interval = makeIntradayInterval(60_000);
    expect(interval()).toBe(false);
  });

  it("respects distinct ms per hook for staggering", () => {
    tradingHoursMock.isTradingHours = (): boolean => true;
    expect(makeIntradayInterval(30_000)()).toBe(30_000);
    expect(makeIntradayInterval(90_000)()).toBe(90_000);
    expect(makeIntradayInterval(120_000)()).toBe(120_000);
  });

  it("reacts to live transition into trading hours (false→ms)", () => {
    tradingHoursMock.isTradingHours = (): boolean => false;
    const interval = makeIntradayInterval(60_000);
    expect(interval()).toBe(false);
    // 开盘后 isTradingHours 变 true，下一拍应恢复轮询
    tradingHoursMock.isTradingHours = (): boolean => true;
    expect(interval()).toBe(60_000);
  });
});
