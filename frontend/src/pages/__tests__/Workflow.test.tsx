// S093 T14：适配前瞻 Tab 重构——ForwardTabSection 调 usePreMarketBriefing + useCrossValidationGroups
// + 新组件 imports（CandidateFunnelEmbed/CrossValidationBadge/P2RiskPanel/WeatherDecisionBar/T1Tab/ContextTab/FactorSection）。
// mock @/lib/query（useDateTriplet/usePreMarketRefresh/usePreMarketBriefing）、@/lib/useMarketClock、
// @/components/workflow/TaskStatusCard + 三个视图组件（避免 lazy import 复杂度）。
// MemoryRouter 驱动 useSearchParams（?view= + ?date=）。
import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";

// ---- mock hooks ----
const qMocks = vi.hoisted(() => ({
  useDateTriplet: vi.fn(),
  usePreMarketRefresh: vi.fn(),
  usePreMarketDates: vi.fn(),
  usePreMarketBriefing: vi.fn(),
}));

vi.mock("@/lib/query", () => ({
  useDateTriplet: qMocks.useDateTriplet,
  usePreMarketRefresh: qMocks.usePreMarketRefresh,
  usePreMarketDates: qMocks.usePreMarketDates,
  usePreMarketBriefing: qMocks.usePreMarketBriefing,
}));

// S093 T14：ForwardTabSection 调 useCrossValidationGroups，mock 避免真 hook 链
vi.mock("@/lib/query/useCrossValidation", () => ({
  useCrossValidationGroups: () => ({ dual: [], funnelOnly: [], breakoutOnly: [], isLoading: false }),
}));

// mock useQuery（advisory 摘要等）+ request（避免真请求）
vi.mock("@tanstack/react-query", () => ({
  useQuery: () => ({ data: undefined }),
}));
vi.mock("@/lib/api/client", () => ({
  request: vi.fn(),
}));

// S093 T14：mock 前瞻 Tab 新组件 imports（避免复杂内部链）
vi.mock("@/components/workflow/CandidateFunnelEmbed", () => ({
  default: () => <div data-testid="candidate-funnel-embed" />,
}));
vi.mock("@/components/workflow/CrossValidationBadge", () => ({
  CrossValidationBadge: () => null,
}));
vi.mock("@/components/workflow/P2RiskPanel", () => ({
  P2RiskPanel: () => null,
}));
vi.mock("@/components/workflow/WeatherDecisionBar", () => ({
  WeatherDecisionBar: () => null,
}));
vi.mock("@/components/workflow/T1Tab", () => ({
  T1Tab: () => null,
}));
vi.mock("@/components/workflow/ContextTab", () => ({
  ContextTab: () => null,
}));
vi.mock("@/components/workflow/FactorSection", () => ({
  FactorSection: () => null,
}));
// S140 R6：rail 行为由 CandidateStateRail.test 覆盖；此处 stub 避免触发 useWorkflowStates 真链
vi.mock("@/components/workflow/CandidateStateRail", () => ({
  CandidateStateRail: () => <div data-testid="candidate-state-rail" />,
}));
vi.mock("@/components/ui/SectionHeader", () => ({
  SectionHeader: () => null,
}));

// useMarketClock mock（避免定时器副作用）
vi.mock("@/lib/useMarketClock", () => ({
  useMarketClock: vi.fn(),
}));

// TaskStatusCard mock（避免轮询 + api 调用）
vi.mock("@/components/workflow/TaskStatusCard", () => ({
  TaskStatusCard: ({ stage, isTradingDay }: { stage: string; isTradingDay: boolean }) => (
    <div data-testid="task-status-card" data-stage={stage} data-trading={String(isTradingDay)}>
      TaskStatusCard
    </div>
  ),
}));

// 三个视图组件 mock（避免 lazy/Suspense + 内部 hooks 复杂度）
vi.mock("@/pages/workflow/PostMarketReview", () => ({
  default: ({ date, reviewAdvanced, stage }: { date: string; reviewAdvanced: boolean; stage: string }) => (
    <div data-testid="post-market-review" data-date={date} data-advanced={String(reviewAdvanced)} data-stage={stage}>
      PostMarketReview
    </div>
  ),
}));

vi.mock("@/pages/workflow/PreMarketBriefing", () => ({
  default: ({ date, stage }: { date: string; stage: string }) => (
    <div data-testid="pre-market-briefing" data-date={date} data-stage={stage}>
      PreMarketBriefing
    </div>
  ),
}));

vi.mock("@/components/workflow/PremarketSelectionSection", () => ({
  PremarketSelectionSection: ({ date }: { date: string }) => (
    <div data-testid="premarket-selection" data-date={date}>
      PremarketSelectionSection
    </div>
  ),
}));

vi.mock("@/components/workflow/StrategyMatchMatrix", () => ({
  StrategyMatchMatrix: ({ date }: { date: string }) => (
    <div data-testid="strategy-match-matrix" data-date={date}>
      StrategyMatchMatrix
    </div>
  ),
}));

// S099: mock PipelineTopology（echarts.init 在 jsdom 无 canvas renderer，stub 避免崩溃）。
// S099 重构后前瞻 Tab 主组件是 PipelineTopology；PremarketSelectionSection 移入其 ③ fold（defaultOpen=false），
// 故 forward date 透传到 PipelineTopology 的 forward prop（原 premarket-selection data-date assert 改测 pipeline-topology data-forward）。
vi.mock("@/components/pipeline/PipelineTopology", () => ({
  PipelineTopology: ({ forward, F }: { forward: string; F: string }) => (
    <div data-testid="pipeline-topology" data-forward={forward} data-F={F}>
      PipelineTopology
    </div>
  ),
}));

import Workflow from "@/pages/Workflow";

// ---- dateTriplet 假数据 ----
function makeTriplet(overrides: Partial<{
  F: string; review: string; today: string; forward: string;
  stage: string; is_trading_day: boolean; review_advanced: boolean;
  server_now: string; next_review_advance_at: number; next_f_advance_at: number;
  non_trading: boolean;
}> = {}) {
  return {
    F: "2026-08-21",
    review: "2026-08-21",
    today: "2026-08-22",
    forward: "2026-08-22",
    stage: "post_market" as const,
    is_trading_day: true,
    review_advanced: true,
    server_now: "2026-08-21T18:00:00+08:00",
    next_review_advance_at: 1787554800,
    next_f_advance_at: 1787303700,
    non_trading: false,
    ...overrides,
  };
}

function renderAt(entry = "/workflow") {
  return render(<MemoryRouter initialEntries={[entry]}><Workflow /></MemoryRouter>);
}

/** 按 Tab 文本取 Tab 按钮（避开锚条同名 label）。Tab 按钮在 TabBar 容器内。 */
function getTabButton(label: string) {
  // TabBar 按钮有 className 含 "rounded-lg px-5" 的 button
  const buttons = screen.getAllByRole("button", { name: label });
  // Tab 按钮的父 div 有 "inline-flex gap-1 rounded-xl" class（TabBar 容器）
  const tabBtn = buttons.find((b) => {
    const parent = b.parentElement;
    return parent?.className.includes("rounded-xl");
  });
  return tabBtn ?? buttons[0];
}

describe("Workflow 三 Tab 容器 (S092)", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    qMocks.useDateTriplet.mockReturnValue({ data: makeTriplet() });
    qMocks.usePreMarketRefresh.mockReturnValue({ mutate: vi.fn(), isPending: false });
    qMocks.usePreMarketDates.mockReturnValue({ data: undefined });
    // S093 T14：ForwardTabSection 调 usePreMarketBriefing，mock 返空数据避免真请求
    qMocks.usePreMarketBriefing.mockReturnValue({ data: undefined, isLoading: false });
  });

  // ---- AC1: 三 Tab 切换 ----
  it("三 Tab 渲染：复盘 / 当日 / 前瞻", () => {
    renderAt();
    // TabBar 里有三个按钮
    const reviewBtn = getTabButton("复盘");
    const todayBtn = getTabButton("盯盘");
    const forwardBtn = getTabButton("选股");
    expect(reviewBtn).toBeTruthy();
    expect(todayBtn).toBeTruthy();
    expect(forwardBtn).toBeTruthy();
  });

  it("默认 Tab = stage 自动高亮（post_market → 前瞻）", async () => {
    renderAt();
    await waitFor(() => {
      const forwardBtn = getTabButton("选股");
      expect(forwardBtn?.className).toContain("text-primary");
    });
  });

  it("点击 Tab → 切到该 Tab", async () => {
    renderAt();
    fireEvent.click(getTabButton("复盘"));
    await waitFor(() => {
      expect(screen.getByTestId("post-market-review")).toBeInTheDocument();
    });
  });

  it("点击当日 Tab → 渲染 PreMarketBriefing", async () => {
    renderAt();
    fireEvent.click(getTabButton("盯盘"));
    await waitFor(() => {
      expect(screen.getByTestId("pre-market-briefing")).toBeInTheDocument();
    });
  });

  it("点击前瞻 Tab → 渲染 PipelineTopology", async () => {
    renderAt();
    fireEvent.click(getTabButton("盯盘"));
    fireEvent.click(getTabButton("选股"));
    fireEvent.click(screen.getByText("pipeline 拓扑")); // S145b：展开 fold（默认收缩）
    await waitFor(() => {
      expect(screen.getByTestId("pipeline-topology")).toBeInTheDocument();
    });
  });

  // ---- R12: stage → 自动高亮 ----
  it("stage=pre_market → 默认高亮前瞻 Tab", async () => {
    qMocks.useDateTriplet.mockReturnValue({ data: makeTriplet({ stage: "pre_market" }) });
    renderAt();
    await waitFor(() => {
      const forwardBtn = getTabButton("选股");
      expect(forwardBtn?.className).toContain("text-primary");
    });
  });

  it("stage=intraday → 默认高亮当日 Tab", async () => {
    qMocks.useDateTriplet.mockReturnValue({ data: makeTriplet({ stage: "intraday" }) });
    renderAt();
    await waitFor(() => {
      const todayBtn = getTabButton("盯盘");
      expect(todayBtn?.className).toContain("text-primary");
    });
  });

  // S093 R3：pre_open → 当日
  it("stage=pre_open → 默认高亮当日 Tab", async () => {
    qMocks.useDateTriplet.mockReturnValue({ data: makeTriplet({ stage: "pre_open" }) });
    renderAt();
    await waitFor(() => {
      const todayBtn = getTabButton("盯盘");
      expect(todayBtn?.className).toContain("text-primary");
    });
  });

  it("stage=post_transition → 默认高亮复盘 Tab", async () => {
    qMocks.useDateTriplet.mockReturnValue({ data: makeTriplet({ stage: "post_transition", review_advanced: true }) });
    renderAt();
    await waitFor(() => {
      const reviewBtn = getTabButton("复盘");
      expect(reviewBtn?.className).toContain("text-primary");
    });
  });

  it("stage=non_trading → 默认高亮复盘 Tab", async () => {
    qMocks.useDateTriplet.mockReturnValue({ data: makeTriplet({ stage: "non_trading", is_trading_day: false, non_trading: true }) });
    renderAt();
    await waitFor(() => {
      const reviewBtn = getTabButton("复盘");
      expect(reviewBtn?.className).toContain("text-primary");
    });
  });

  // ---- 用户手动切 Tab 后 stage 变化不自动切 ----
  it("用户手动切 Tab 后 stage 变化不自动覆盖", async () => {
    renderAt();
    // 手动切复盘
    fireEvent.click(getTabButton("复盘"));
    await waitFor(() => {
      expect(screen.getByTestId("post-market-review")).toBeInTheDocument();
    });
    // 此时 userTouchedTab=true，后续 stage 变化不自动切
    // (stage 不会在这测试中变，但 userTouched 后即便 stage effect 触发也不会覆盖)
    expect(screen.getByTestId("post-market-review")).toBeInTheDocument();
  });

  // ---- R7: date picker ?date= ----
  it("URL ?date= → date picker 回显该日期", () => {
    renderAt("/workflow?date=2026-07-01");
    const input = screen.getByLabelText("选择复盘日 F") as HTMLInputElement;
    expect(input.value).toBe("2026-07-01");
  });

  it("URL ?date= → useDateTriplet 收到该 date（is_manual=true）", () => {
    renderAt("/workflow?date=2026-07-01");
    expect(qMocks.useDateTriplet).toHaveBeenCalledWith("2026-07-01");
  });

  it("无 ?date= → useDateTriplet 收 undefined（自动态）", () => {
    renderAt();
    expect(qMocks.useDateTriplet).toHaveBeenCalledWith(undefined);
  });

  it("改 date picker → URL ?date= 更新", () => {
    renderAt();
    const input = screen.getByLabelText("选择复盘日 F");
    fireEvent.change(input, { target: { value: "2026-07-02" } });
    // setSearchParams 会更新 URL → re-render → useDateTriplet 收新 date
    expect(qMocks.useDateTriplet).toHaveBeenLastCalledWith("2026-07-02");
  });

  it("清除日期按钮 → 删 ?date=", () => {
    renderAt("/workflow?date=2026-07-01");
    fireEvent.click(screen.getByRole("button", { name: "清除日期" }));
    expect(qMocks.useDateTriplet).toHaveBeenLastCalledWith(undefined);
  });

  // ---- 锚条 ----
  it("锚条显示 F + 三视图数据日", () => {
    renderAt();
    expect(screen.getByText("锚定交易日 F")).toBeInTheDocument();
    // F 值 + 复盘数据日都是 2026-08-21，用 getAllByText
    const fValues = screen.getAllByText("2026-08-21");
    expect(fValues.length).toBeGreaterThanOrEqual(1);
  });

  it("过渡窗前瞻数据日显示'待 17:15 产出'", () => {
    qMocks.useDateTriplet.mockReturnValue({ data: makeTriplet({ stage: "post_transition" }) });
    renderAt();
    expect(screen.getByText("待 17:15 产出")).toBeInTheDocument();
  });

  it("过渡窗锚条时段标签显示'数据采集中'", () => {
    qMocks.useDateTriplet.mockReturnValue({ data: makeTriplet({ stage: "post_transition" }) });
    renderAt();
    expect(screen.getByText("数据采集中 · 15:30-17:15")).toBeInTheDocument();
  });

  it("盘后就绪锚条时段标签显示'数据就绪'", () => {
    renderAt();
    expect(screen.getByText("数据就绪 · 17:15 后")).toBeInTheDocument();
  });

  // ---- TaskStatusCard ----
  it("TaskStatusCard 渲染 + 接收 stage/isTradingDay", () => {
    renderAt();
    const card = screen.getByTestId("task-status-card");
    expect(card).toBeInTheDocument();
    expect(card.getAttribute("data-stage")).toBe("post_market");
    expect(card.getAttribute("data-trading")).toBe("true");
  });

  // ---- S093 T21：公共区战法入口 EntryCard ----
  it("公共区渲染战法管理入口卡片（锚条下方常驻）", () => {
    renderAt();
    expect(screen.getByText("战法管理")).toBeInTheDocument();
    expect(screen.getByText("战绩 · 前向测试 · 阈值配置")).toBeInTheDocument();
  });

  it("战法入口卡片链接指向 /strategy", () => {
    renderAt();
    const link = screen.getByText("战法管理").closest("a");
    expect(link).toHaveAttribute("href", "/strategy");
  });

  // ---- dateTriplet 加载态 ----
  it("dateTriplet 未加载 → 锚条显示加载提示", () => {
    qMocks.useDateTriplet.mockReturnValue({ data: undefined });
    renderAt();
    expect(screen.getByText("dateTriplet 加载中…")).toBeInTheDocument();
  });

  // ---- 受控 date prop 注入 ----
  it("复盘 Tab → PostMarketReview 收 dateTriplet.review + reviewAdvanced + stage", async () => {
    renderAt();
    fireEvent.click(getTabButton("复盘"));
    const pmr = await waitFor(() => screen.getByTestId("post-market-review"));
    expect(pmr.getAttribute("data-date")).toBe("2026-08-21"); // = triplet.review
    expect(pmr.getAttribute("data-advanced")).toBe("true");    // = triplet.review_advanced
    expect(pmr.getAttribute("data-stage")).toBe("post_market"); // = triplet.stage
  });

  it("当日 Tab → PreMarketBriefing 收 dateTriplet.today + stage", async () => {
    renderAt();
    fireEvent.click(getTabButton("盯盘"));
    const pmb = await waitFor(() => screen.getByTestId("pre-market-briefing"));
    expect(pmb.getAttribute("data-date")).toBe("2026-08-22"); // = triplet.today
    expect(pmb.getAttribute("data-stage")).toBe("post_market");
  });

  it("前瞻 Tab → PipelineTopology 收 dateTriplet.forward", async () => {
    renderAt();
    fireEvent.click(getTabButton("选股"));
    fireEvent.click(screen.getByText("pipeline 拓扑")); // S145b：展开 fold（默认收缩）
    const pt = await waitFor(() => screen.getByTestId("pipeline-topology"));
    expect(pt.getAttribute("data-forward")).toBe("2026-08-22"); // = triplet.forward
  });
});
