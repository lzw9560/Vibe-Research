import { describe, it, expect, vi } from "vitest";
import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import type { ReactNode } from "react";
import { FunnelLayerCard } from "./FunnelLayerCard";
import type { FunnelLayer } from "@/lib/candidates";

// S033 T13：FunnelLayerCard 状态徽标——mock getWorkflowStates（全量取数路径）。
const apiMocks = vi.hoisted(() => ({
  getWorkflowStates: vi.fn<() => Promise<unknown>>(),
}));

vi.mock("@/lib/api", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@/lib/api")>();
  return { ...actual, getWorkflowStates: apiMocks.getWorkflowStates };
});

// S031 T13：公共 FunnelLayerCard——计数/conditions/passed/filtered/footer + info/neutral 色调。
const base: FunnelLayer = {
  layer_id: "R1", name: "换手过滤", as_of: "2026-08-07T09:00:00",
  input_count: 10, output_count: 3,
  filtered_out: [{ code: "000002", name: "万科A", reason: "换手<8%" }],
  output_codes: ["000001"], conditions: ["换手>=8.0%"],
  passed: [{ code: "000001", name: "平安银行" }],
};

function newClient() {
  return new QueryClient({ defaultOptions: { queries: { retry: false } } });
}
function renderWithClient(ui: ReactNode) {
  return render(<QueryClientProvider client={newClient()}>{ui}</QueryClientProvider>);
}

describe("FunnelLayerCard", () => {
  it("渲染层标题 + 输入→输出计数 + conditions + passed + filtered", () => {
    renderWithClient(<FunnelLayerCard layer={base} />);
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
    renderWithClient(<FunnelLayerCard layer={base} onPick={onPick} />);
    fireEvent.click(screen.getByText(/平安银行/));
    expect(onPick).toHaveBeenCalledWith("000001");
  });

  it("variant=info 时 conditions 用 primary 色", () => {
    const { container } = renderWithClient(<FunnelLayerCard layer={base} variant="info" />);
    const chip = container.querySelector(".bg-primary\\/10");
    expect(chip).not.toBeNull();
  });

  it("data_status=未取得 时显示原因、不渲染 passed", () => {
    const layer: FunnelLayer = { ...base, data_status: "未取得", data_reason: "预计算未执行", passed: [{ code: "000001", name: "X" }] };
    renderWithClient(<FunnelLayerCard layer={layer} />);
    expect(screen.getByText(/预计算未执行/)).toBeInTheDocument();
    expect(screen.queryByText(/平安银行/)).not.toBeInTheDocument();
  });

  it("footer 槽渲染（候选池 rerun 注入）", () => {
    renderWithClient(<FunnelLayerCard layer={base} footer={<button>重跑此层</button>} />);
    expect(screen.getByText("重跑此层")).toBeInTheDocument();
  });

  // ============ S033 T7/T12：状态徽标 ============

  it("S033：传 date 时 passed 行渲染 workflow_state 状态色块（holding 绿）", async () => {
    apiMocks.getWorkflowStates.mockResolvedValue({
      date: "2026-08-07",
      states: [
        { code: "000001", name: "平安银行", trade_date: "2026-08-07", status: "holding", reason: "", created_at: "", updated_at: "" },
      ],
      counts: { holding: 1 },
    });
    const { container } = renderWithClient(<FunnelLayerCard layer={base} date="2026-08-07" />);
    await waitFor(() => expect(container.querySelector(".bg-green-500")).not.toBeNull());
    expect(apiMocks.getWorkflowStates).toHaveBeenCalledWith("2026-08-07");
  });

  it("S033：状态缺失的 passed 行用灰淡默认色（不臆造状态）", async () => {
    apiMocks.getWorkflowStates.mockResolvedValue({ date: "2026-08-07", states: [], counts: {} });
    const { container } = renderWithClient(<FunnelLayerCard layer={base} date="2026-08-07" />);
    await waitFor(() => expect(container.querySelector(".bg-gray-200")).not.toBeNull());
  });

  it("S033：filtered_out 行带红淡徽标（无需 date）", () => {
    const { container } = renderWithClient(<FunnelLayerCard layer={base} />);
    expect(container.querySelector(".bg-red-300")).not.toBeNull();
  });
});
