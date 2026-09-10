import { describe, it, expect } from "vitest";
import { render, screen } from "@testing-library/react";
import { HonestEmptyState } from "./HonestEmptyState";

describe("HonestEmptyState", () => {
  it("renders message when no data available", () => {
    render(<HonestEmptyState message="暂无 OFI 快照" />);
    expect(screen.getByText("暂无 OFI 快照")).toBeInTheDocument();
  });

  it("renders hint when provided", () => {
    render(<HonestEmptyState message="暂无数据" hint="盘中采集后显示" />);
    expect(screen.getByText("盘中采集后显示")).toBeInTheDocument();
  });

  it("omits hint paragraph when not provided", () => {
    const { container } = render(<HonestEmptyState message="暂无数据" />);
    expect(container.querySelectorAll("p")).toHaveLength(1);
  });

  it("renders ReactNode hint with inline elements (e.g. <code>)", () => {
    render(
      <HonestEmptyState
        message="暂无闭环记录"
        hint={<><span>运行 </span><code>journal_recorder.run_daily()</code><span> 后显示</span></>}
      />,
    );
    expect(screen.getByText("journal_recorder.run_daily()")).toBeInTheDocument();
    expect(screen.getByText(/后显示/)).toBeInTheDocument();
  });

  it("applies custom className alongside base classes", () => {
    const { container } = render(<HonestEmptyState message="空" className="my-4" />);
    expect(container.firstChild).toHaveClass("my-4");
    expect(container.firstChild).toHaveClass("border-dashed");
  });

  it("uses muted foreground color (honest, not alarming)", () => {
    render(<HonestEmptyState message="暂无数据" />);
    expect(screen.getByText("暂无数据")).toHaveClass("text-muted-foreground");
  });
});
