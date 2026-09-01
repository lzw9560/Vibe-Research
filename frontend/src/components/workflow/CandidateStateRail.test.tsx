import { describe, it, expect, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import { CandidateStateRail } from "./CandidateStateRail";

vi.mock("@/lib/query", () => ({
  useWorkflowStates: vi.fn((date?: string) => ({
    data: date
      ? { counts: { pending: 3, candidate: 2, watching: 1, monitoring: 0, holding: 0, settled: 0, filtered: 0 } }
      : undefined,
  })),
}));

import { useWorkflowStates } from "@/lib/query";

describe("CandidateStateRail (S140 R6)", () => {
  it("date 空时返 null——防 IntradayMonitor 全零空挂覆辙", () => {
    const { container } = render(<CandidateStateRail date={undefined} />);
    expect(container.firstChild).toBeNull();
    // 不该调 query（rail 缺数据时根本不挂）
    expect(useWorkflowStates).not.toHaveBeenCalled();
  });

  it("date 非空时挂 StateMachineDashboard + 用该 date 取数（A6 防假过门）", () => {
    render(<CandidateStateRail date="2026-09-01" />);
    expect(useWorkflowStates).toHaveBeenCalledWith("2026-09-01");
    expect(screen.getByText("状态机看板")).toBeInTheDocument();
    expect(screen.getByText("3")).toBeInTheDocument(); // pending=3 计数可见
  });
});
