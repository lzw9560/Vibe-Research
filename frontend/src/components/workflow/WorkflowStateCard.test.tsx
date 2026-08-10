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
    // S049 D7：candidate 态"取消选中"按钮文案（→filtered）
    expect(screen.getByText(/取消选中/)).toBeInTheDocument();
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

  // ============ S034：结算摘要展示 ============

  it("S034：settled 行显示结算收益（盈 + 红涨色）", () => {
    qm.useWorkflowState.mockReturnValue({
      data: {
        ...stateCandidate, status: "settled", allowed_targets: ["candidate"],
        entry_price: 10, exit_price: 11, strategy: "首板挖掘",
        settlement: { return_pct: 10, won: true, hold_days: 3 },
      },
      isLoading: false,
    });
    qm.useWorkflowStateHistory.mockReturnValue({ data: [] });
    const { container } = render(<WorkflowStateCard code="600001" date="2026-08-07" />);
    expect(screen.getByText(/结算收益 \+10%/)).toBeInTheDocument();
    expect(screen.getByText(/盈/)).toBeInTheDocument();
    expect(screen.getByText(/持有 3 天/)).toBeInTheDocument();
    expect(container.querySelector(".text-danger")).not.toBeNull(); // 红涨（A 股口径）
  });

  it("S034：亏损结算显示绿跌色", () => {
    qm.useWorkflowState.mockReturnValue({
      data: {
        ...stateCandidate, status: "settled", allowed_targets: ["candidate"],
        entry_price: 10, exit_price: 9.5,
        settlement: { return_pct: -5, won: false, hold_days: 1 },
      },
      isLoading: false,
    });
    qm.useWorkflowStateHistory.mockReturnValue({ data: [] });
    const { container } = render(<WorkflowStateCard code="600001" date="2026-08-07" />);
    expect(screen.getByText(/结算收益 -5%/)).toBeInTheDocument();
    expect(container.querySelector(".text-success")).not.toBeNull(); // 绿跌
  });

  it("S034：未 settled 行不显示结算摘要", () => {
    qm.useWorkflowState.mockReturnValue({ data: stateCandidate, isLoading: false });
    qm.useWorkflowStateHistory.mockReturnValue({ data: [] });
    render(<WorkflowStateCard code="600001" date="2026-08-07" />);
    expect(screen.queryByText(/结算收益/)).not.toBeInTheDocument();
  });

  // ============ S038：市价自动结算 toggle + exit_price_source 标注 ============

  it("S038：settled 流转勾选市价自动结算 → 请求体含 auto_fill_exit_price:true 且无 exit_price", () => {
    const mutate = vi.fn();
    qm.useTransitionWorkflowState.mockReturnValue({ mutate, isPending: false });
    qm.useWorkflowState.mockReturnValue({
      data: { ...stateCandidate, status: "holding", allowed_targets: ["settled", "candidate"] },
      isLoading: false,
    });
    qm.useWorkflowStateHistory.mockReturnValue({ data: [] });
    render(<WorkflowStateCard code="600001" date="2026-08-07" />);

    fireEvent.click(screen.getByText(/结算/));
    // 勾选「按市价自动结算」
    fireEvent.click(screen.getByRole("checkbox"));
    // 勾选后卖出价输入框应消失
    expect(screen.queryByPlaceholderText("如 13.80")).not.toBeInTheDocument();
    fireEvent.click(screen.getByText("确认流转"));
    expect(mutate).toHaveBeenCalledWith(expect.objectContaining({
      code: "600001", date: "2026-08-07", target: "settled",
      auto_fill_exit_price: true, exit_price: undefined,
    }));
  });

  it("S038：settled 流转不勾选 + 手填卖出价 → 请求体含 exit_price 且 auto_fill_exit_price 为 false", () => {
    const mutate = vi.fn();
    qm.useTransitionWorkflowState.mockReturnValue({ mutate, isPending: false });
    qm.useWorkflowState.mockReturnValue({
      data: { ...stateCandidate, status: "holding", allowed_targets: ["settled", "candidate"] },
      isLoading: false,
    });
    qm.useWorkflowStateHistory.mockReturnValue({ data: [] });
    render(<WorkflowStateCard code="600001" date="2026-08-07" />);

    fireEvent.click(screen.getByText(/结算/));
    // 不勾选——直接手填卖出价
    const exitInput = screen.getByPlaceholderText("如 13.80");
    fireEvent.change(exitInput, { target: { value: "13.8" } });
    fireEvent.click(screen.getByText("确认流转"));
    expect(mutate).toHaveBeenCalledWith(expect.objectContaining({
      code: "600001", date: "2026-08-07", target: "settled",
      exit_price: 13.8, auto_fill_exit_price: false,
    }));
  });

  it("S038：exit_price_source=market → 卖出价后标「市价自动」", () => {
    qm.useWorkflowState.mockReturnValue({
      data: {
        ...stateCandidate, status: "settled", allowed_targets: ["candidate"],
        entry_price: 10, exit_price: 1800.5,
        settlement: { return_pct: 50, won: true, hold_days: 0, exit_price_source: "market" },
      },
      isLoading: false,
    });
    qm.useWorkflowStateHistory.mockReturnValue({ data: [] });
    render(<WorkflowStateCard code="600001" date="2026-08-07" />);
    expect(screen.getByText(/卖出价 1800.5/)).toBeInTheDocument();
    expect(screen.getByText(/市价自动/)).toBeInTheDocument();
    expect(screen.queryByText(/手动填写/)).not.toBeInTheDocument();
  });

  it("S038：exit_price_source=manual → 卖出价后标「手动填写」", () => {
    qm.useWorkflowState.mockReturnValue({
      data: {
        ...stateCandidate, status: "settled", allowed_targets: ["candidate"],
        entry_price: 10, exit_price: 11,
        settlement: { return_pct: 10, won: true, hold_days: 0, exit_price_source: "manual" },
      },
      isLoading: false,
    });
    qm.useWorkflowStateHistory.mockReturnValue({ data: [] });
    render(<WorkflowStateCard code="600001" date="2026-08-07" />);
    expect(screen.getByText(/手动填写/)).toBeInTheDocument();
    expect(screen.queryByText(/市价自动/)).not.toBeInTheDocument();
  });

  it("S038：exit_price_source 缺失（null）→ 卖出价后不标来源", () => {
    qm.useWorkflowState.mockReturnValue({
      data: {
        ...stateCandidate, status: "settled", allowed_targets: ["candidate"],
        entry_price: 10, exit_price: 11,
        settlement: { return_pct: 10, won: true, hold_days: 0 },
      },
      isLoading: false,
    });
    qm.useWorkflowStateHistory.mockReturnValue({ data: [] });
    render(<WorkflowStateCard code="600001" date="2026-08-07" />);
    expect(screen.getByText(/卖出价 11/)).toBeInTheDocument();
    expect(screen.queryByText(/市价自动/)).not.toBeInTheDocument();
    expect(screen.queryByText(/手动填写/)).not.toBeInTheDocument();
  });

  // ============ S049 D7：取消观察/取消选中按钮 ============

  it("S049 D7：candidate 态渲染「✕ 取消选中」按钮（→filtered）", () => {
    const mutate = vi.fn();
    qm.useTransitionWorkflowState.mockReturnValue({ mutate, isPending: false });
    qm.useWorkflowState.mockReturnValue({ data: stateCandidate, isLoading: false });
    qm.useWorkflowStateHistory.mockReturnValue({ data: [] });
    render(<WorkflowStateCard code="600001" date="2026-08-07" />);
    const btn = screen.getByText(/取消选中/);
    expect(btn).toBeInTheDocument();
    fireEvent.click(btn);
    expect(mutate).toHaveBeenCalledWith({ code: "600001", date: "2026-08-07", target: "filtered" });
  });

  it("S049 D7：watching 态渲染「取消观察」按钮（→candidate）", () => {
    const mutate = vi.fn();
    qm.useTransitionWorkflowState.mockReturnValue({ mutate, isPending: false });
    qm.useWorkflowState.mockReturnValue({
      data: { ...stateCandidate, status: "watching", allowed_targets: ["monitoring", "filtered", "candidate"] },
      isLoading: false,
    });
    qm.useWorkflowStateHistory.mockReturnValue({ data: [] });
    render(<WorkflowStateCard code="600001" date="2026-08-07" />);
    const btn = screen.getByText(/取消观察/);
    expect(btn).toBeInTheDocument();
    fireEvent.click(btn);
    expect(mutate).toHaveBeenCalledWith({ code: "600001", date: "2026-08-07", target: "candidate" });
  });
});
