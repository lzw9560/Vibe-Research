import { describe, it, expect, vi } from "vitest";
import { render, screen, fireEvent } from "@testing-library/react";
import { Sheet } from "./Sheet";

// S031 T16：Sheet 抽屉——开/关/Esc/点遮罩/点面板不关/锁滚动。
describe("Sheet", () => {
  it("open 时把 children 渲染到 document.body（portal）", () => {
    render(
      <Sheet open onClose={() => {}}>
        抽屉内容
      </Sheet>,
    );
    expect(screen.getByText("抽屉内容")).toBeInTheDocument();
  });

  it("open=false 时不渲染", () => {
    render(
      <Sheet open={false} onClose={() => {}}>
        抽屉内容
      </Sheet>,
    );
    expect(screen.queryByText("抽屉内容")).not.toBeInTheDocument();
  });

  it("Esc 调 onClose", () => {
    const onClose = vi.fn();
    render(<Sheet open onClose={onClose}>内容</Sheet>);
    fireEvent.keyDown(document.body, { key: "Escape" });
    expect(onClose).toHaveBeenCalled();
  });

  it("点遮罩调 onClose", () => {
    const onClose = vi.fn();
    render(<Sheet open onClose={onClose}>内容</Sheet>);
    fireEvent.click(screen.getByTestId("sheet-overlay"));
    expect(onClose).toHaveBeenCalled();
  });

  it("点面板内容不触发 onClose（遮罩与面板为兄弟节点）", () => {
    const onClose = vi.fn();
    render(
      <Sheet open onClose={onClose}>
        <button>内部按钮</button>
      </Sheet>,
    );
    fireEvent.click(screen.getByText("内部按钮"));
    expect(onClose).not.toHaveBeenCalled();
  });

  it("open 时锁 body 滚动，卸载后恢复", () => {
    const { unmount } = render(<Sheet open onClose={() => {}}>内容</Sheet>);
    expect(document.body.style.overflow).toBe("hidden");
    unmount();
    expect(document.body.style.overflow).toBe("");
  });

  it("side=left 时面板贴左", () => {
    render(<Sheet open side="left" onClose={() => {}}>内容</Sheet>);
    expect(screen.getByTestId("sheet-panel").className).toContain("left-0");
  });
});
