// Track D M6 test: focusDay 全局 store——set/clear 跨页传播（跟切重拉基础）。
import { describe, it, expect } from "vitest";
import { render, screen, fireEvent } from "@testing-library/react";
import { FocusDayProvider, useFocusDay, useSetFocusDay } from "../focusDay";

// 消费者组件：显 focusDate + set/clear 按钮
function Consumer() {
  const { focusDate } = useFocusDay();
  const setFocus = useSetFocusDay();
  return (
    <div>
      <span data-testid="state">{focusDate ?? "auto"}</span>
      <button onClick={() => setFocus("2026-09-13")}>set</button>
      <button onClick={() => setFocus(null)}>clear</button>
    </div>
  );
}

describe("focusDay store (M6)", () => {
  it("初始为 auto（null）", () => {
    render(
      <FocusDayProvider>
        <Consumer />
      </FocusDayProvider>
    );
    expect(screen.getByTestId("state").textContent).toBe("auto");
  });

  it("set 设焦点日 → 消费者读到新值", () => {
    render(
      <FocusDayProvider>
        <Consumer />
      </FocusDayProvider>
    );
    fireEvent.click(screen.getByText("set"));
    expect(screen.getByTestId("state").textContent).toBe("2026-09-13");
  });

  it("clear 回 auto（null）", () => {
    render(
      <FocusDayProvider>
        <Consumer />
      </FocusDayProvider>
    );
    fireEvent.click(screen.getByText("set"));
    expect(screen.getByTestId("state").textContent).toBe("2026-09-13");
    fireEvent.click(screen.getByText("clear"));
    expect(screen.getByTestId("state").textContent).toBe("auto");
  });
});
