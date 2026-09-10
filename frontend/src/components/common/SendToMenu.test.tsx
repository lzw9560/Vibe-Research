import { describe, it, expect, vi } from "vitest";
import { render, screen, fireEvent } from "@testing-library/react";
import { SendToMenu, type SendPayload, type SendTarget } from "./SendToMenu";

describe("SendToMenu", () => {
  const baseProps = {
    code: "600519",
    name: "贵州茅台",
    sourcePage: "screener",
  };

  it("renders trigger button labeled 送入", () => {
    render(<SendToMenu {...baseProps} onSend={vi.fn()} />);
    expect(screen.getByRole("button", { name: /送入/ })).toBeInTheDocument();
  });

  it("does not show menu items before clicking", () => {
    render(<SendToMenu {...baseProps} onSend={vi.fn()} />);
    expect(screen.queryByText("加入自选")).not.toBeInTheDocument();
  });

  it("opens menu on click and shows all four targets", () => {
    render(<SendToMenu {...baseProps} onSend={vi.fn()} />);
    fireEvent.click(screen.getByRole("button", { name: /送入/ }));
    expect(screen.getByText("加入自选")).toBeInTheDocument();
    expect(screen.getByText("加入持仓")).toBeInTheDocument();
    expect(screen.getByText("加入交易日志")).toBeInTheDocument();
    expect(screen.getByText("加入研究记录")).toBeInTheDocument();
  });

  it("calls onSend with full SendPayload including target=watchlist", () => {
    const onSend = vi.fn();
    render(<SendToMenu {...baseProps} onSend={onSend} />);
    fireEvent.click(screen.getByRole("button", { name: /送入/ }));
    fireEvent.click(screen.getByText("加入自选"));

    expect(onSend).toHaveBeenCalledTimes(1);
    const payload: SendPayload = onSend.mock.calls[0][0];
    expect(payload.code).toBe("600519");
    expect(payload.name).toBe("贵州茅台");
    expect(payload.source_page).toBe("screener");
    expect(payload.target).toBe("watchlist");
    expect(typeof payload.timestamp).toBe("number");
  });

  it("calls onSend with target=portfolio when that item clicked", () => {
    const onSend = vi.fn();
    render(<SendToMenu {...baseProps} onSend={onSend} />);
    fireEvent.click(screen.getByRole("button", { name: /送入/ }));
    fireEvent.click(screen.getByText("加入持仓"));
    expect(onSend.mock.calls[0][0].target).toBe("portfolio");
  });

  it("closes menu after selecting a target", () => {
    render(<SendToMenu {...baseProps} onSend={vi.fn()} />);
    fireEvent.click(screen.getByRole("button", { name: /送入/ }));
    expect(screen.getByText("加入自选")).toBeInTheDocument();
    fireEvent.click(screen.getByText("加入持仓"));
    expect(screen.queryByText("加入自选")).not.toBeInTheDocument();
  });

  it("closes on Escape key", () => {
    render(<SendToMenu {...baseProps} onSend={vi.fn()} />);
    fireEvent.click(screen.getByRole("button", { name: /送入/ }));
    expect(screen.getByText("加入自选")).toBeInTheDocument();
    fireEvent.keyDown(document, { key: "Escape" });
    expect(screen.queryByText("加入自选")).not.toBeInTheDocument();
  });

  it("closes on click outside", () => {
    render(
      <div>
        <SendToMenu {...baseProps} onSend={vi.fn()} />
        <button>外部按钮</button>
      </div>,
    );
    fireEvent.click(screen.getByRole("button", { name: /送入/ }));
    expect(screen.getByText("加入自选")).toBeInTheDocument();
    fireEvent.mouseDown(screen.getByText("外部按钮"));
    expect(screen.queryByText("加入自选")).not.toBeInTheDocument();
  });

  it("toggles menu closed when trigger clicked again", () => {
    render(<SendToMenu {...baseProps} onSend={vi.fn()} />);
    const trigger = screen.getByRole("button", { name: /送入/ });
    fireEvent.click(trigger);
    expect(screen.getByText("加入自选")).toBeInTheDocument();
    fireEvent.click(trigger);
    expect(screen.queryByText("加入自选")).not.toBeInTheDocument();
  });

  it("renders disabled button when disabled prop is true", () => {
    render(<SendToMenu {...baseProps} onSend={vi.fn()} disabled />);
    expect(screen.getByRole("button", { name: /送入/ })).toBeDisabled();
  });

  it("all four SendTarget values are valid", () => {
    const targets: SendTarget[] = ["watchlist", "portfolio", "journal", "research"];
    expect(targets).toHaveLength(4);
  });
});
