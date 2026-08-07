import { describe, it, expect, vi } from "vitest";
import { render, screen, fireEvent } from "@testing-library/react";
import { FunnelLayerCard } from "./FunnelLayerCard";
import type { FunnelLayer } from "@/lib/candidates";

// S031 T13：公共 FunnelLayerCard——计数/conditions/passed/filtered/footer + info/neutral 色调。
const base: FunnelLayer = {
  layer_id: "R1", name: "换手过滤", as_of: "2026-08-07T09:00:00",
  input_count: 10, output_count: 3,
  filtered_out: [{ code: "000002", name: "万科A", reason: "换手<8%" }],
  output_codes: ["000001"], conditions: ["换手>=8.0%"],
  passed: [{ code: "000001", name: "平安银行" }],
};

describe("FunnelLayerCard", () => {
  it("渲染层标题 + 输入→输出计数 + conditions + passed + filtered", () => {
    render(<FunnelLayerCard layer={base} />);
    expect(screen.getByText("R1")).toBeInTheDocument();
    expect(screen.getByText("换手过滤")).toBeInTheDocument();
    expect(screen.getByText("3")).toBeInTheDocument(); // output_count
    expect(screen.getByText("换手>=8.0%")).toBeInTheDocument();
    expect(screen.getByText(/平安银行/)).toBeInTheDocument();
    expect(screen.getByText(/万科A/)).toBeInTheDocument();
    expect(screen.getByText(/换手<8%/)).toBeInTheDocument();
  });

  it("点 passed 候选调 onPick", () => {
    const onPick = vi.fn();
    render(<FunnelLayerCard layer={base} onPick={onPick} />);
    fireEvent.click(screen.getByText(/平安银行/));
    expect(onPick).toHaveBeenCalledWith("000001");
  });

  it("variant=info 时 conditions 用 primary 色", () => {
    const { container } = render(<FunnelLayerCard layer={base} variant="info" />);
    const chip = container.querySelector(".bg-primary\\/10");
    expect(chip).not.toBeNull();
  });

  it("data_status=未取得 时显示原因、不渲染 passed", () => {
    const layer: FunnelLayer = { ...base, data_status: "未取得", data_reason: "预计算未执行", passed: [{ code: "000001", name: "X" }] };
    render(<FunnelLayerCard layer={layer} />);
    expect(screen.getByText(/预计算未执行/)).toBeInTheDocument();
    expect(screen.queryByText(/平安银行/)).not.toBeInTheDocument();
  });

  it("footer 槽渲染（候选池 rerun 注入）", () => {
    render(<FunnelLayerCard layer={base} footer={<button>重跑此层</button>} />);
    expect(screen.getByText("重跑此层")).toBeInTheDocument();
  });
});
