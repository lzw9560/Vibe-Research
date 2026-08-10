// S048 R2/R7/R9 测试：PreMarketBriefing 页——date 感知 / no_snapshot 补采 / 历史不可变 / 快照漏斗层。
// mock 四个协作 hook + CandidateDetailPanel + FunnelLayers（隔离候选抽屉与漏斗行重组件）。
import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, fireEvent } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";

const qMocks = vi.hoisted(() => ({
  usePreMarketBriefing: vi.fn(),
  usePreMarketRefresh: vi.fn(),
  useFunnelLayers: vi.fn(),
  useStrategyBacktest: vi.fn(),
}));

vi.mock("@/lib/query", () => ({
  usePreMarketBriefing: qMocks.usePreMarketBriefing,
  usePreMarketRefresh: qMocks.usePreMarketRefresh,
}));
vi.mock("@/lib/query/topology", () => ({ useFunnelLayers: qMocks.useFunnelLayers }));
vi.mock("@/lib/query/strategy", () => ({
  useStrategyBacktest: qMocks.useStrategyBacktest,
  syntheticWinRate: (c: number) => Math.min(c * 0.8 + 0.2, 0.95),
}));
vi.mock("@/pages/workflow/CandidateDetail", () => ({ CandidateDetailPanel: () => null }));
vi.mock("@/components/candidate/FunnelLayers", () => ({
  FunnelLayers: ({ layers }: { layers: unknown[] }) => (
    <div data-testid="funnel-stub" data-count={layers.length} />
  ),
}));

import PreMarketBriefing from "@/pages/workflow/PreMarketBriefing";

const mutateMock = vi.fn();

function renderAt(entry = "/workflow/pre-market") {
  return render(<MemoryRouter initialEntries={[entry]}><PreMarketBriefing /></MemoryRouter>);
}

const snapshotLayer = {
  layer_id: "R1", name: "R1 基础过滤", as_of: "2026-07-01T08:00:00",
  input_count: 10, output_count: 5, filtered_out: [], output_codes: ["600519"],
};

describe("PreMarketBriefing (S048)", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    qMocks.usePreMarketRefresh.mockReturnValue({ mutate: mutateMock, isPending: false });
    qMocks.useFunnelLayers.mockReturnValue({ data: undefined, isLoading: false });
    qMocks.useStrategyBacktest.mockReturnValue({ data: [], isLoading: false });
    qMocks.usePreMarketBriefing.mockReturnValue({
      data: { status: "done", factors: [], data_date: "2026-08-07" },
      isLoading: false,
      refetch: vi.fn(),
    });
  });

  it("R2: URL ?date= → usePreMarketBriefing 收到该 date", () => {
    renderAt("/workflow/pre-market?date=2026-07-01");
    expect(qMocks.usePreMarketBriefing).toHaveBeenCalledWith("2026-07-01", expect.anything());
  });

  it("R7: no_snapshot → 补采按钮 + 出入标注；点击 → refresh.mutate(date)", () => {
    qMocks.usePreMarketBriefing.mockReturnValue({
      data: { status: "no_snapshot", data_date: "2026-06-01", msg: "无快照" },
      isLoading: false,
      refetch: vi.fn(),
    });
    renderAt("/workflow/pre-market?date=2026-06-01");
    expect(screen.getByText(/补采数据可能与当日实盘所见有出入/)).toBeInTheDocument();
    const btn = screen.getByRole("button", { name: /补采该日数据/ });
    fireEvent.click(btn);
    expect(mutateMock).toHaveBeenCalledWith("2026-06-01");
  });

  it("R7: 历史 done → 无刷新按钮（不可变）+ 快照提示", () => {
    qMocks.usePreMarketBriefing.mockReturnValue({
      data: { status: "done", from_snapshot: true, data_date: "2026-07-01", factors: [], funnel_layers: [] },
      isLoading: false,
      refetch: vi.fn(),
    });
    renderAt("/workflow/pre-market?date=2026-07-01");
    expect(screen.queryByTitle("刷新")).not.toBeInTheDocument();
    expect(screen.getByText(/历史快照（不可变）/)).toBeInTheDocument();
  });

  it("R9: from_snapshot → 直渲 briefing.funnel_layers，live 漏斗查询禁用", () => {
    qMocks.usePreMarketBriefing.mockReturnValue({
      data: {
        status: "done", from_snapshot: true, data_date: "2026-07-01",
        factors: [{ factor_id: "f1", factor_name: "f1", candidates: [], layers: [], config: {}, as_of: "", data_date: "2026-07-01", data_status: "ok" }],
        funnel_layers: [snapshotLayer],
      },
      isLoading: false,
      refetch: vi.fn(),
    });
    renderAt("/workflow/pre-market?date=2026-07-01");
    const stub = screen.getByTestId("funnel-stub");
    expect(stub.getAttribute("data-count")).toBe("1");
    // live 查询禁用：date 传 undefined + enabled false（历史零外部请求）
    expect(qMocks.useFunnelLayers).toHaveBeenCalledWith(undefined, { enabled: false });
  });

  it("R2: 今日 done（无 date）→ live 漏斗查询启用，刷新按钮在", () => {
    renderAt();
    expect(qMocks.useFunnelLayers).toHaveBeenCalledWith("2026-08-07", { enabled: true });
    expect(screen.getByTitle("刷新")).toBeInTheDocument();
  });

  it("idle 自动采集仅今日触发：无 date → mutate(undefined)；有 date → 不自动触发", () => {
    qMocks.usePreMarketBriefing.mockReturnValue({
      data: { status: "idle", msg: "未采集" }, isLoading: false, refetch: vi.fn(),
    });
    renderAt();
    expect(mutateMock).toHaveBeenCalledWith(undefined);

    mutateMock.mockClear();
    qMocks.usePreMarketBriefing.mockReturnValue({
      data: { status: "idle", msg: "未采集", data_date: "2026-08-07" }, isLoading: false, refetch: vi.fn(),
    });
    renderAt("/workflow/pre-market?date=2026-08-07");
    expect(mutateMock).not.toHaveBeenCalled();
  });
});
