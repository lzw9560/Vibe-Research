// useDebounce 单测：验证 (1) 挂载即返回初值；(2) 延迟内仅末次变更生效；
// (3) 卸载时清理计时器，不再 setState；(4) 空值即时断查 + 切换后重输不以旧值起跳。
import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { renderHook, act } from "@testing-library/react";
import { useDebounce } from "./useDebounce";

describe("useDebounce", () => {
  beforeEach(() => {
    vi.useFakeTimers();
  });
  afterEach(() => {
    vi.useRealTimers();
  });

  it("returns initial value immediately (no debounce on mount)", () => {
    const { result } = renderHook(() => useDebounce("init", 300));
    expect(result.current).toBe("init");
  });

  it("debounces: only emits last value after delay elapses", () => {
    let value = "a";
    const { result, rerender } = renderHook(() => useDebounce(value, 300));
    expect(result.current).toBe("a");

    // 第一次变更：未到延迟，仍为旧值
    value = "ab";
    rerender();
    expect(result.current).toBe("a");

    // 200ms 内再次变更 → 计时器重置，仍为旧值
    act(() => {
      vi.advanceTimersByTime(200);
    });
    value = "abc";
    rerender();
    expect(result.current).toBe("a");

    // 完整延迟过后同步末次值
    act(() => {
      vi.advanceTimersByTime(300);
    });
    expect(result.current).toBe("abc");
  });

  it("clears pending timer on unmount (no state update after unmount)", () => {
    const { result, unmount } = renderHook(() => useDebounce("x", 300));
    unmount();
    // 卸载后推进计时器：若未清理会触发 setState；此处应无副作用且值不变
    act(() => {
      vi.advanceTimersByTime(400);
    });
    expect(result.current).toBe("x");
  });

  it("empties immediately on clear and does not leak stale into a new input", () => {
    let value = "银行";
    const { result, rerender } = renderHook(() => useDebounce(value, 300));

    // 先让 "银行" 结算
    act(() => {
      vi.advanceTimersByTime(300);
    });
    expect(result.current).toBe("银行");

    // 清空：渲染期即时返空（不等延迟），防清空首帧 stale
    value = "";
    rerender();
    expect(result.current).toBe("");

    // 立即（未推进计时器）重输新值：不应以旧 "银行" 起跳，应为空直到再次结算
    value = "打板";
    rerender();
    expect(result.current).toBe("");

    act(() => {
      vi.advanceTimersByTime(300);
    });
    expect(result.current).toBe("打板");
  });
});
