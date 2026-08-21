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
// S092 内嵌补全：PreMarketBriefing 新增 useQuery（advisory 摘要）+ api.advisorySummary 调用，补 mock
vi.mock("@tanstack/react-query", async (importActual) => {
  const actual = await importActual<typeof import("@tanstack/react-query")>();
  return { ...actual, useQuery: () => ({ data: undefined }) };
});
vi.mock("@/lib/api", async (importActual) => {
  const actual = await importActual<typeof import("@/lib/api")>();
  return { ...actual, api: { ...actual.api, advisorySummary: vi.fn() } };
});

import PreMarketBriefing from "@/pages/workflow/PreMarketBriefing";

const mutateMock = vi.fn();

function renderAt(date = "2026-08-07", stage = "pre_market", entry = "/workflow/pre-market") {
  return render(<MemoryRouter initialEntries={[entry]}><PreMarketBriefing date={date} stage={stage} /></MemoryRouter>);
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

  it("R2: date prop → usePreMarketBriefing 收到该 date", () => {
    // S092：date 改为受控 prop（=dateTriplet.today），不再从 URL ?date= 取
    renderAt("2026-07-01");
    expect(qMocks.usePreMarketBriefing).toHaveBeenCalledWith("2026-07-01", expect.anything());
  });

  it("R7: no_snapshot → 补采按钮 + 出入标注；点击 → refresh.mutate(date)", () => {
    qMocks.usePreMarketBriefing.mockReturnValue({
      data: { status: "no_snapshot", data_date: "2026-06-01", msg: "无快照" },
      isLoading: false,
      refetch: vi.fn(),
    });
    renderAt("2026-06-01");
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
    renderAt("2026-07-01");
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
    renderAt("2026-07-01");
    // S049 D2/D4：直渲 briefing.funnel_layers（SelectionPipeline 渲染 layer_id "R1"）
    expect(screen.getByText("R1")).toBeInTheDocument();
    // S049 D4：live 查询不再启用（funnel_layers 由 briefing 携带，不发 GET）
    expect(qMocks.useFunnelLayers).not.toHaveBeenCalled();
  });

  it("R2: 今日 done（无历史 date）→ 刷新按钮在（S049 D4：funnel_layers 由 briefing 携带）", () => {
    // S092：date 改为受控 prop，"今日"= date 与 data_date 相同（isHistorical 仍 true 但 isHistoryDone=false
    //   需要 briefing.data_date === date 才不算"历史"——但原逻辑是 isHistorical=!!date，
    //   所以只要有 date 就是历史。此处改 mock data_date 与 date 一致，测 done 态有刷新按钮。
    //   注：S092 后此组件不再从 URL 取 date，"今日"语义由容器传 dateTriplet.today 决定。
    qMocks.usePreMarketBriefing.mockReturnValue({
      data: { status: "done", factors: [], data_date: "2026-08-07", funnel_layers: [] },
      isLoading: false,
      refetch: vi.fn(),
    });
    renderAt("2026-08-07");
    // S048 R7：done 且非历史 → 可刷新（WorkflowStage onRefresh 渲染）
    expect(screen.getByTitle("刷新")).toBeInTheDocument();
  });

  it("idle 自动采集：idle 态（无 from_snapshot）→ 触发 mutate", () => {
    // S092：isHistorical 改为 briefing.from_snapshot 判断（非 !!date）。
    //   idle 态无 from_snapshot → isHistorical=false → auto-trigger 触发 mutate(date)。
    qMocks.usePreMarketBriefing.mockReturnValue({
      data: { status: "idle", msg: "未采集" }, isLoading: false, refetch: vi.fn(),
    });
    renderAt("2026-08-07");
    expect(mutateMock).toHaveBeenCalled();
  });
});
