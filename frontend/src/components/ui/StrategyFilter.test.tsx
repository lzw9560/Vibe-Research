import { describe, it, expect, vi } from "vitest";
import { render, screen, fireEvent } from "@testing-library/react";
import { StrategyFilter } from "./StrategyFilter";

// S031 T19：StrategyFilter——多选 chips + 全部 + 反筛纯前端 onChange。
describe("StrategyFilter", () => {
  it("渲染 全部 + 各战法 chips", () => {
    render(<StrategyFilter strategies={["首板挖掘", "连板接力"]} selected={new Set()} onChange={() => {}} />);
    expect(screen.getByText("全部")).toBeInTheDocument();
    expect(screen.getByText("首板挖掘")).toBeInTheDocument();
    expect(screen.getByText("连板接力")).toBeInTheDocument();
  });

  it("点未选战法 → onChange 加入该战法", () => {
    const onChange = vi.fn();
    render(<StrategyFilter strategies={["首板挖掘"]} selected={new Set()} onChange={onChange} />);
    fireEvent.click(screen.getByText("首板挖掘"));
    expect(onChange).toHaveBeenCalledWith(new Set(["首板挖掘"]));
  });

  it("点已选战法 → onChange 移除该战法", () => {
    const onChange = vi.fn();
    render(<StrategyFilter strategies={["首板挖掘"]} selected={new Set(["首板挖掘"])} onChange={onChange} />);
    fireEvent.click(screen.getByText("首板挖掘"));
    expect(onChange).toHaveBeenCalledWith(new Set());
  });

  it("点全部 → onChange 清空（恢复）", () => {
    const onChange = vi.fn();
    render(<StrategyFilter strategies={["首板挖掘"]} selected={new Set(["首板挖掘"])} onChange={onChange} />);
    fireEvent.click(screen.getByText("全部"));
    expect(onChange).toHaveBeenCalledWith(new Set());
  });

  it("aria-pressed 反映选中态", () => {
    render(<StrategyFilter strategies={["首板挖掘"]} selected={new Set(["首板挖掘"])} onChange={() => {}} />);
    expect(screen.getByText("首板挖掘")).toHaveAttribute("aria-pressed", "true");
    expect(screen.getByText("全部")).toHaveAttribute("aria-pressed", "false");
  });
});
