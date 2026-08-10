// S048 R12 测试：EdgeLegend 图例开关——无 onToggle 纯展示；有 onToggle 可点击；hidden 态样式。
import { describe, it, expect, vi } from "vitest";
import { render, screen, fireEvent } from "@testing-library/react";
import { EdgeLegend } from "../EdgeLegend";
import type { GraphEdge } from "@/lib/api/types";

const edges: GraphEdge[] = [
  { source: "a", target: "b", type: "sector", weight: 1 },
  { source: "a", target: "c", type: "fund_flow", weight: 2 },
];

describe("EdgeLegend (S048 R12)", () => {
  it("无 onToggle → 纯展示 span，不渲染 button（兼容他处用法）", () => {
    const { container } = render(<EdgeLegend edges={edges} />);
    expect(screen.getByText("同板块")).toBeInTheDocument();
    expect(screen.getByText("共流入")).toBeInTheDocument();
    expect(container.querySelectorAll("button")).toHaveLength(0);
  });

  it("有 onToggle → 渲染 button，点击回调该边类型", () => {
    const onToggle = vi.fn();
    render(<EdgeLegend edges={edges} onToggle={onToggle} />);
    fireEvent.click(screen.getByRole("button", { name: /共流入/ }));
    expect(onToggle).toHaveBeenCalledWith("fund_flow");
  });

  it("hidden 类型 → aria-pressed=false + opacity-40；可见类型 aria-pressed=true", () => {
    render(<EdgeLegend edges={edges} hidden={["fund_flow"]} onToggle={vi.fn()} />);
    expect(screen.getByRole("button", { name: /共流入/ }).getAttribute("aria-pressed")).toBe("false");
    expect(screen.getByRole("button", { name: /同板块/ }).getAttribute("aria-pressed")).toBe("true");
    expect(screen.getByRole("button", { name: /共流入/ }).className).toContain("opacity-40");
  });

  it("未出现的边类型不展示（存在性按传入 edges 判定）", () => {
    render(<EdgeLegend edges={[edges[0]]} onToggle={vi.fn()} />);
    expect(screen.queryByText("共流入")).not.toBeInTheDocument();
  });

  it("空 edges → 不渲染", () => {
    const { container } = render(<EdgeLegend edges={[]} />);
    expect(container.firstChild).toBeNull();
  });
});
