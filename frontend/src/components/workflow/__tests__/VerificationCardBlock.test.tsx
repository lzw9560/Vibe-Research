// S060：验证对账卡前端测试
import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import { VerificationCardBlock } from "@/components/workflow/VerificationCardBlock";

const mockApi = vi.hoisted(() => ({
  verificationCard: vi.fn(),
}));
vi.mock("@/lib/api", () => ({ api: mockApi }));

describe("VerificationCardBlock (S060)", () => {
  beforeEach(() => vi.clearAllMocks());

  it("无条件时不渲染", async () => {
    mockApi.verificationCard.mockResolvedValue({ conditions: [], count: 0, status_summary: {} });
    const { container } = render(<VerificationCardBlock />);
    await new Promise((r) => setTimeout(r, 50));
    expect(container.querySelector('[data-testid="verification-card"]')).toBeNull();
  });

  it("pending 条件渲染「明日验证条件预览」", async () => {
    mockApi.verificationCard.mockResolvedValue({
      conditions: [
        { id: 1, date: "2026-08-12", metric: "zt_count", subject: "全市场",
          baseline: 58, threshold_up: 69.6, threshold_down: 46.4,
          actual: null, status: "pending", note: "涨停家数 58 ±20%",
          created_at: "", verified_at: null },
      ],
      count: 1, status_summary: { pending: 1 }, note: "",
    });
    render(<VerificationCardBlock />);
    await waitFor(() => {
      expect(screen.getByText("明日验证条件预览")).toBeInTheDocument();
      expect(screen.getByText("1 条待验证")).toBeInTheDocument();
    });
  });

  it("已对账条件渲染「昨日验证对账」+ 状态图标", async () => {
    mockApi.verificationCard.mockResolvedValue({
      conditions: [
        { id: 1, date: "2026-08-12", metric: "zt_count", subject: "全市场",
          baseline: 58, threshold_up: 69.6, threshold_down: 46.4,
          actual: 130, status: "met_up", note: "涨停家数 58 ±20%；实际 130 ≥ 69.6",
          created_at: "", verified_at: "2026-08-13T10:00:00" },
      ],
      count: 1, status_summary: { met_up: 1 }, note: "",
    });
    render(<VerificationCardBlock />);
    await waitFor(() => {
      expect(screen.getByText("昨日验证对账")).toBeInTheDocument();
      expect(screen.getByText("上行验证")).toBeInTheDocument();
    });
  });

  it("data_missing 条件渲染「数据缺失」", async () => {
    mockApi.verificationCard.mockResolvedValue({
      conditions: [
        { id: 2, date: "2026-08-12", metric: "break_rate", subject: "全市场",
          baseline: 0.15, threshold_up: 0.2, threshold_down: 0.1,
          actual: null, status: "data_missing", note: "炸板率；T+1 数据缺失",
          created_at: "", verified_at: null },
      ],
      count: 1, status_summary: { data_missing: 1 }, note: "",
    });
    render(<VerificationCardBlock />);
    await waitFor(() => {
      expect(screen.getByText("数据缺失")).toBeInTheDocument();
    });
  });
});
