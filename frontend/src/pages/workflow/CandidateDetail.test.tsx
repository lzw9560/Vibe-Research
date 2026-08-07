import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import { CandidateDetailPanel } from "./CandidateDetail";
import { candidatesApi } from "@/lib/candidates";
import type { DiagnosisCard } from "@/lib/candidates";

// S031 T17：CandidateDetailPanel——加载/错误/渲染诊断卡（路由页与抽屉共用）。
vi.mock("@/lib/candidates", async () => {
  const actual = await vi.importActual<typeof import("@/lib/candidates")>("@/lib/candidates");
  return { ...actual, candidatesApi: { diagnosis: vi.fn() } };
});

const fakeCard = {
  code: "000001", name: "平安银行", as_of: "2026-08-07",
  indicators: { missing: {}, announcements: [], concepts: [] },
  activity: { tier: "活跃", rules_applied: ["换手>=8%"] },
  stabilization: { evidence: {} },
  risk_flags: [],
} as unknown as DiagnosisCard;

describe("CandidateDetailPanel", () => {
  beforeEach(() => vi.clearAllMocks());

  it("加载中显示 Skeleton", () => {
    vi.mocked(candidatesApi.diagnosis).mockReturnValue(new Promise(() => {}));
    const { container } = render(<CandidateDetailPanel code="000001" />);
    expect(container.querySelectorAll(".h-24, .h-20").length).toBeGreaterThan(0);
  });

  it("取数成功渲染诊断卡名称 + 命中规则", async () => {
    vi.mocked(candidatesApi.diagnosis).mockResolvedValue(fakeCard);
    render(<CandidateDetailPanel code="000001" />);
    await waitFor(() => expect(screen.getByText("平安银行")).toBeInTheDocument());
    expect(screen.getByText("活跃度档位：")).toBeInTheDocument();
    expect(screen.getByText("换手>=8%")).toBeInTheDocument();
  });

  it("取数失败显示错误", async () => {
    vi.mocked(candidatesApi.diagnosis).mockRejectedValue(new Error("boom"));
    render(<CandidateDetailPanel code="000001" />);
    await waitFor(() => expect(screen.getByText(/取数失败：boom/)).toBeInTheDocument());
  });
});
