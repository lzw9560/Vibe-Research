import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, fireEvent } from "@testing-library/react";
import { WorkflowStateCard } from "./WorkflowStateCard";

// S033 T13：WorkflowStateCard——徽标 + timeline + 流转按钮（只渲染 allowed_targets）+ 表单弹出。
// mock @/lib/query 的三个 hooks（组件不经真实网络）。
const qm = vi.hoisted(() => ({
  useWorkflowState: vi.fn(),
  useWorkflowStateHistory: vi.fn(),
  useTransitionWorkflowState: vi.fn(),
}));

vi.mock("@/lib/query", async (importOriginal) => {
  const actual = await importOriginal<Record<string, unknown>>();
  return { ...actual, ...qm };
});

const stateCandidate = {
  code: "600001", name: "测试甲", trade_date: "2026-08-07", status: "candidate",
  reason: "基因达标", created_at: "2026-08-07T09:00:00", updated_at: "2026-08-07T09:00:00",
  entry_price: null, exit_price: null, strategy: null,
  allowed_targets: ["watching", "filtered"],
};

beforeEach(() => {
  vi.clearAllMocks();
  qm.useTransitionWorkflowState.mockReturnValue({ mutate: vi.fn(), isPending: false });
});

describe("WorkflowStateCard", () => {
  it("无记录时客观提示，不伪装状态", () => {
    qm.useWorkflowState.mockReturnValue({ data: null, isLoading: false });
    qm.useWorkflowStateHistory.mockReturnValue({ data: null });
    render(<WorkflowStateCard code="600001" date="2026-08-07" />);
    expect(screen.getByText(/无工作流状态记录/)).toBeInTheDocument();
  });

  it("渲染当前态徽标（candidate 蓝色块 + 中文标签）", () => {
    qm.useWorkflowState.mockReturnValue({ data: stateCandidate, isLoading: false });
    qm.useWorkflowStateHistory.mockReturnValue({ data: [] });
    const { container } = render(<WorkflowStateCard code="600001" date="2026-08-07" />);
    expect(screen.getByText("候选")).toBeInTheDocument();
    expect(container.querySelector(".bg-blue-500")).not.toBeNull();
  });

  it("timeline 倒序渲染 from→to + reason", () => {
    qm.useWorkflowState.mockReturnValue({ data: { ...stateCandidate, status: "watching", allowed_targets: ["monitoring", "filtered"] }, isLoading: false });
    qm.useWorkflowStateHistory.mockReturnValue({
      data: [
        { code: "600001", trade_date: "2026-08-07", from_status: "pending", to_status: "candidate", reason: "基因达标", created_at: "2026-08-07T09:00:00" },
        { code: "600001", trade_date: "2026-08-07", from_status: "candidate", to_status: "watching", reason: "手动观察", created_at: "2026-08-07T09:30:00" },
      ],
    });
    render(<WorkflowStateCard code="600001" date="2026-08-07" />);
    const lines = screen.getAllByText(/手动观察|基因达标/);
    expect(lines.length).toBeGreaterThanOrEqual(2);
    // 倒序：最新（手动观察）在前
    expect(lines[0]).toHaveTextContent("手动观察");
  });

  it("流转按钮只渲染 allowed_targets", () => {
    qm.useWorkflowState.mockReturnValue({ data: stateCandidate, isLoading: false });
    qm.useWorkflowStateHistory.mockReturnValue({ data: [] });
    render(<WorkflowStateCard code="600001" date="2026-08-07" />);
    expect(screen.getByText(/观察/)).toBeInTheDocument();
    expect(screen.getByText(/过滤/)).toBeInTheDocument();
    expect(screen.queryByText(/持仓/)).not.toBeInTheDocument(); // holding 不在 allowed
  });

  it("watching 按钮直接 POST（无弹窗）", () => {
    const mutate = vi.fn();
    qm.useTransitionWorkflowState.mockReturnValue({ mutate, isPending: false });
    qm.useWorkflowState.mockReturnValue({ data: stateCandidate, isLoading: false });
    qm.useWorkflowStateHistory.mockReturnValue({ data: [] });
    render(<WorkflowStateCard code="600001" date="2026-08-07" />);
    fireEvent.click(screen.getByText(/观察/));
    expect(mutate).toHaveBeenCalledWith({ code: "600001", date: "2026-08-07", target: "watching" });
  });

  it("holding 按钮先弹表单；填买入价提交带 entry_price", () => {
    const mutate = vi.fn();
    qm.useTransitionWorkflowState.mockReturnValue({ mutate, isPending: false });
    qm.useWorkflowState.mockReturnValue({
      data: { ...stateCandidate, status: "monitoring", allowed_targets: ["holding", "filtered"] },
      isLoading: false,
    });
    qm.useWorkflowStateHistory.mockReturnValue({ data: [] });
    render(<WorkflowStateCard code="600001" date="2026-08-07" />);

    fireEvent.click(screen.getByText(/持仓/));
    // 表单出现：买入价 input（holding 语义）
    const priceInput = screen.getByPlaceholderText("如 12.50");
    fireEvent.change(priceInput, { target: { value: "12.5" } });
    fireEvent.click(screen.getByText("确认流转"));
    expect(mutate).toHaveBeenCalledWith(expect.objectContaining({
      code: "600001", date: "2026-08-07", target: "holding", entry_price: 12.5,
    }));
  });

  it("date 缺省时用 state.trade_date 回填流转", () => {
    const mutate = vi.fn();
    qm.useTransitionWorkflowState.mockReturnValue({ mutate, isPending: false });
    qm.useWorkflowState.mockReturnValue({ data: stateCandidate, isLoading: false });
    qm.useWorkflowStateHistory.mockReturnValue({ data: [] });
    render(<WorkflowStateCard code="600001" />);
    fireEvent.click(screen.getByText(/观察/));
    expect(mutate).toHaveBeenCalledWith({ code: "600001", date: "2026-08-07", target: "watching" });
  });
});
