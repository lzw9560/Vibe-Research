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
  useShadowComparison: vi.fn(),
  useTransitionWorkflowState: vi.fn(),
  useWeatherStrategyMap: vi.fn(),
  useFunnelStrategies: vi.fn(),
  useCalendarFactor: vi.fn(),
  useMarketKillSwitch: vi.fn(),
}));

vi.mock("@/lib/query", () => ({
  usePreMarketBriefing: qMocks.usePreMarketBriefing,
  usePreMarketRefresh: qMocks.usePreMarketRefresh,
  useShadowComparison: qMocks.useShadowComparison,
  useTransitionWorkflowState: qMocks.useTransitionWorkflowState,
}));
vi.mock("@/lib/query/topology", () => ({ useFunnelLayers: qMocks.useFunnelLayers }));
vi.mock("@/lib/query/strategy", () => ({
  useStrategyBacktest: qMocks.useStrategyBacktest,
  syntheticWinRate: (c: number) => Math.min(c * 0.8 + 0.2, 0.95),
  useWeatherStrategyMap: () => ({ data: { weather_strategy_map: { 晴天: ["consecutive_relay"], 未知: ["first_plate"] }, fallback_strategies: {} } }),
  useFunnelStrategies: () => ({ data: [] }),
  useCalendarFactor: () => ({ data: undefined }),
  useMarketKillSwitch: () => ({ data: undefined }),
  useSectorCycle: () => ({ data: undefined }),
  // S075：HonestyBanner 调 useForwardTestSummary，补 mock 避免预存测试报错
  useForwardTestSummary: () => ({ data: undefined, isLoading: false }),
  // S075：SelectionPipeline 的 SectorRotationNode 调 useMultiRotation，补 mock
  useMultiRotation: () => ({ data: undefined, isLoading: false }),
  // S075：SelectionPipeline 的 NonLimitupLane 调 useNonLimitupFunnel，补 mock
  useNonLimitupFunnel: () => ({ data: undefined, isLoading: false }),
}));
// S090 A：PremarketSelectionSection 调 usePremarketSelection，补 mock 避免真请求
vi.mock("@/lib/query/premarket", () => ({
  usePremarketSelection: () => ({ isLoading: true }),
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

// S049 D2：快照层带 passed（矩阵渲染需 passed 字段）
const snapshotLayer = {
  layer_id: "R1", name: "R1 基础过滤", as_of: "2026-07-01T08:00:00",
  input_count: 10, output_count: 5, filtered_out: [], output_codes: ["600519"],
  passed: [{ code: "600519", name: "贵州茅台", gene_score: 80 }],
};

describe("PreMarketBriefing (S048)", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    qMocks.usePreMarketRefresh.mockReturnValue({ mutate: mutateMock, isPending: false });
    qMocks.useFunnelLayers.mockReturnValue({ data: undefined, isLoading: false });
    qMocks.useStrategyBacktest.mockReturnValue({ data: [], isLoading: false });
    qMocks.useShadowComparison.mockReturnValue({ data: undefined, isLoading: false });
    qMocks.useTransitionWorkflowState.mockReturnValue({ mutate: vi.fn(), isPending: false });
    qMocks.usePreMarketBriefing.mockReturnValue({
      data: { status: "done", factors: [], data_date: "2026-08-07", funnel_layers: [] },
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

  it("R9: from_snapshot → 直渲 briefing.funnel_layers，live 漏斗查询禁用（S049 D4：不发 GET）", () => {
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
    // S049 D2/D4：直渲 briefing.funnel_layers（SelectionPipeline 渲染 layer_id "R1"）
    expect(screen.getByText("R1")).toBeInTheDocument();
    // S049 D4：live 查询不再启用（funnel_layers 由 briefing 携带，不发 GET）
    expect(qMocks.useFunnelLayers).not.toHaveBeenCalled();
  });

  it("R2: 今日 done（无 date）→ 刷新按钮在（S049 D4：funnel_layers 由 briefing 携带）", () => {
    renderAt();
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
