import { describe, it, expect, vi } from "vitest";
import { render, screen, fireEvent } from "@testing-library/react";
import { TransitionForm } from "./TransitionForm";

// S033 T13：TransitionForm——holding 买入价 / settled 卖出价 / 战法下拉 / 理由，全可选。
describe("TransitionForm", () => {
  it("holding 表单：填买入价+战法+理由，提交带全字段", () => {
    const onSubmit = vi.fn();
    render(
      <TransitionForm code="600001" date="2026-08-07" target="holding" onSubmit={onSubmit} onCancel={vi.fn()} />,
    );
    fireEvent.change(screen.getByPlaceholderText("如 12.50"), { target: { value: "10.2" } });
    fireEvent.change(screen.getByRole("combobox"), { target: { value: "连板接力" } });
    fireEvent.change(screen.getByPlaceholderText("备注（可选）"), { target: { value: "打板进" } });
    fireEvent.click(screen.getByText("确认流转"));
    expect(onSubmit).toHaveBeenCalledWith({
      code: "600001", date: "2026-08-07", target: "holding",
      reason: "打板进", entry_price: 10.2, exit_price: undefined, strategy: "连板接力",
    });
  });

  it("settled 表单：只显示卖出价，不显示买入价", () => {
    render(
      <TransitionForm code="600001" date="2026-08-07" target="settled" onSubmit={vi.fn()} onCancel={vi.fn()} />,
    );
    expect(screen.getByPlaceholderText("如 13.80")).toBeInTheDocument();
    expect(screen.queryByPlaceholderText("如 12.50")).not.toBeInTheDocument();
  });

  it("全空提交：价格/战法/理由均 undefined（COALESCE 不覆盖已有值）", () => {
    const onSubmit = vi.fn();
    render(
      <TransitionForm code="600001" date="2026-08-07" target="holding" onSubmit={onSubmit} onCancel={vi.fn()} />,
    );
    fireEvent.click(screen.getByText("确认流转"));
    expect(onSubmit).toHaveBeenCalledWith({
      code: "600001", date: "2026-08-07", target: "holding",
      reason: undefined, entry_price: undefined, exit_price: undefined, strategy: undefined,
    });
  });

  it("非法数字忽略（entry_price undefined，不传 NaN）", () => {
    const onSubmit = vi.fn();
    render(
      <TransitionForm code="600001" date="2026-08-07" target="holding" onSubmit={onSubmit} onCancel={vi.fn()} />,
    );
    fireEvent.change(screen.getByPlaceholderText("如 12.50"), { target: { value: "abc" } });
    fireEvent.click(screen.getByText("确认流转"));
    expect(onSubmit).toHaveBeenCalledWith(expect.objectContaining({ entry_price: undefined }));
  });

  it("取消调 onCancel 不提交", () => {
    const onSubmit = vi.fn();
    const onCancel = vi.fn();
    render(
      <TransitionForm code="600001" date="2026-08-07" target="holding" onSubmit={onSubmit} onCancel={onCancel} />,
    );
    fireEvent.click(screen.getByText("取消"));
    expect(onCancel).toHaveBeenCalled();
    expect(onSubmit).not.toHaveBeenCalled();
  });
});
