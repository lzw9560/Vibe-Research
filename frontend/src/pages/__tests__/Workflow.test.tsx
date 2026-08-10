// S048 R1/R2/R3 测试：Workflow 首页——三卡片恒序（不随时段重排）+ URL ?date= 历史视角。
// mock @/lib/query 三 hooks（status/briefing/states），MemoryRouter 驱动 useSearchParams。
import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, fireEvent } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";

const qMocks = vi.hoisted(() => ({
  useWorkflowStatus: vi.fn(),
  usePreMarketBriefing: vi.fn(),
  useWorkflowStates: vi.fn(),
}));

vi.mock("@/lib/query", () => ({
  useWorkflowStatus: qMocks.useWorkflowStatus,
  usePreMarketBriefing: qMocks.usePreMarketBriefing,
  useWorkflowStates: qMocks.useWorkflowStates,
}));

import Workflow from "@/pages/Workflow";

function renderAt(entry = "/workflow") {
  return render(<MemoryRouter initialEntries={[entry]}><Workflow /></MemoryRouter>);
}

describe("Workflow 首页 (S048)", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    qMocks.useWorkflowStatus.mockReturnValue({
      data: { candidate_count: 12, signal_count: 3, alert_count: 0, win_rate: 55 },
      isLoading: false,
      isFetching: false,
      refetch: vi.fn(),
    });
    qMocks.usePreMarketBriefing.mockReturnValue({ data: undefined });
    qMocks.useWorkflowStates.mockReturnValue({ data: undefined });
  });

  it("R1: 三阶段卡恒按 盘前→盘中→盘后 渲染（h3 序断言，不随时段重排）", () => {
    renderAt();
    const h3s = screen.getAllByRole("heading", { level: 3 }).map((h) => h.textContent);
    expect(h3s.slice(0, 3)).toEqual(["盘前简报", "盘中监控", "盘后复盘"]);
  });

  it("R2: URL ?date= → 日期选择器回显 + briefing/states hooks 收到该 date", () => {
    renderAt("/workflow?date=2026-07-01");
    const input = screen.getByLabelText("选择历史日期") as HTMLInputElement;
    expect(input.value).toBe("2026-07-01");
    expect(qMocks.usePreMarketBriefing).toHaveBeenCalledWith("2026-07-01");
    expect(qMocks.useWorkflowStates).toHaveBeenCalledWith("2026-07-01");
  });

  it("R2: 无 ?date= → hooks 收 undefined（今日实时现状不变）", () => {
    renderAt();
    expect(qMocks.usePreMarketBriefing).toHaveBeenCalledWith(undefined);
    expect(qMocks.useWorkflowStates).toHaveBeenCalledWith(undefined);
  });

  it("R3: 历史视角卡片——盘前=快照候选数、盘中=monitoring、盘后=settled", () => {
    // 注：候选数用 5/6/7 避开 StageCard 步骤序号 1-4（getByText 精确匹配会撞）
    qMocks.usePreMarketBriefing.mockReturnValue({
      data: {
        status: "done",
        from_snapshot: true,
        factors: [
          { factor_id: "f1", candidates: [{ code: "1" }, { code: "2" }, { code: "3" }, { code: "4" }, { code: "5" }] },
        ],
      },
    });
    qMocks.useWorkflowStates.mockReturnValue({
      data: { date: "2026-07-01", states: [], counts: { monitoring: 6, settled: 7 } },
    });
    renderAt("/workflow?date=2026-07-01");
    expect(screen.getByText("5")).toBeInTheDocument();  // 5 快照候选
    expect(screen.getByText("6")).toBeInTheDocument();  // monitoring
    expect(screen.getByText("7")).toBeInTheDocument();  // settled
  });

  it("R3: 历史视角无数据 → 显示 --", () => {
    renderAt("/workflow?date=2026-07-01");
    expect(screen.getAllByText("--").length).toBeGreaterThanOrEqual(3);
  });

  it("R3: 历史视角停 60s 轮询；今日视角维持 60s", () => {
    renderAt("/workflow?date=2026-07-01");
    expect(qMocks.useWorkflowStatus).toHaveBeenCalledWith({ refetchInterval: false });
    vi.clearAllMocks();
    qMocks.useWorkflowStatus.mockReturnValue({ data: {}, isLoading: false, isFetching: false, refetch: vi.fn() });
    qMocks.usePreMarketBriefing.mockReturnValue({ data: undefined });
    qMocks.useWorkflowStates.mockReturnValue({ data: undefined });
    renderAt();
    expect(qMocks.useWorkflowStatus).toHaveBeenCalledWith({ refetchInterval: 60_000 });
  });

  it("R2: 改日期选择器 → URL 更新（hooks 收到新 date）", () => {
    renderAt();
    const input = screen.getByLabelText("选择历史日期");
    fireEvent.change(input, { target: { value: "2026-07-02" } });
    expect(qMocks.usePreMarketBriefing).toHaveBeenLastCalledWith("2026-07-02");
  });

  it("R2: 「回到今日」清 ?date= → hooks 收 undefined", () => {
    renderAt("/workflow?date=2026-07-01");
    fireEvent.click(screen.getByRole("button", { name: "回到今日" }));
    expect(qMocks.usePreMarketBriefing).toHaveBeenLastCalledWith(undefined);
  });
});
