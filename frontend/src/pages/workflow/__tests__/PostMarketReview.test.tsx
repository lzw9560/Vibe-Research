// S054 R3：PostMarketReview 去桩重写后三问渲染 + 占位「待判定」+ 空态 + 结算入口 + 研判 + 教学点。
import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";

const qMock = vi.hoisted(() => ({
  useDailyWinReview: vi.fn(),
  useShadowComparison: vi.fn(),
  useTransitionWorkflowState: vi.fn(),
  usePreMarketBriefing: vi.fn(),
}));

vi.mock("@/lib/query", () => ({
  useDailyWinReview: qMock.useDailyWinReview,
  useShadowComparison: qMock.useShadowComparison,
  useTransitionWorkflowState: qMock.useTransitionWorkflowState,
  usePreMarketBriefing: qMock.usePreMarketBriefing,
}));

// S066 ForwardTestPanel 的 hook mock（返 undefined → 不渲染面板数据）
vi.mock("@/lib/query/strategy", () => ({
  useForwardTestSummary: () => ({ data: undefined }),
}));

import PostMarketReview from "../PostMarketReview";

function renderPage() {
  return render(
    <MemoryRouter>
      <PostMarketReview date="2026-08-11" reviewAdvanced={true} stage="post_market" />
    </MemoryRouter>,
  );
}

describe("PostMarketReview S054", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    qMock.useShadowComparison.mockReturnValue({ data: null });
    qMock.useTransitionWorkflowState.mockReturnValue({ mutate: vi.fn(), isPending: false });
    qMock.usePreMarketBriefing.mockReturnValue({ data: null });
  });

  it("无快照 → no_snapshot 空态文案", () => {
    qMock.useDailyWinReview.mockReturnValue({
      data: {
        date: "2026-08-11",
        no_snapshot: true,
        pushed: [],
        bought: [],
        missed: [],
        prev_day_missed: { items: [], summary: null },
        missing_kline: 0,
        disclaimer: "历史统计特征，市场有风险，研究参考",
      },
    });
    renderPage();
    expect(screen.getByText(/无盘前快照/)).toBeInTheDocument();
  });

  it("有快照 → 三问区渲染 pushed/bought/missed", () => {
    qMock.useDailyWinReview.mockReturnValue({
      data: {
        date: "2026-08-11",
        no_snapshot: false,
        pushed: [
          { code: "600519", name: "贵州茅台", gene_score: 70, strategies: ["first_plate"] },
        ],
        bought: [
          { code: "600519", name: "贵州茅台", entry_price: 1800.0, strategy: "first_plate", status: "holding", placeholder: "待判定" },
        ],
        missed: [{ code: "300750" }],
        prev_day_missed: { items: [], summary: null },
        missing_kline: 0,
        disclaimer: "历史统计特征，市场有风险，研究参考",
      },
    });
    renderPage();
    expect(screen.getByText("① 系统推了什么")).toBeInTheDocument();
    expect(screen.getByText("② 你买了什么")).toBeInTheDocument();
    expect(screen.getByText("③ 漏了什么")).toBeInTheDocument();
    expect(screen.getAllByText("600519").length).toBeGreaterThanOrEqual(1);
    expect(screen.getByText("300750")).toBeInTheDocument();
  });

  it("bought 占位标签「待判定」", () => {
    qMock.useDailyWinReview.mockReturnValue({
      data: {
        date: "2026-08-11",
        no_snapshot: false,
        pushed: [],
        bought: [
          { code: "600519", name: "贵州茅台", entry_price: null, strategy: null, status: "holding", placeholder: "待判定" },
        ],
        missed: [],
        prev_day_missed: { items: [], summary: null },
        missing_kline: 0,
        disclaimer: "",
      },
    });
    renderPage();
    expect(screen.getByText("待判定")).toBeInTheDocument();
  });

  it("无 pushed → 当日无候选推送", () => {
    qMock.useDailyWinReview.mockReturnValue({
      data: {
        date: "2026-08-11",
        no_snapshot: false,
        pushed: [],
        bought: [],
        missed: [],
        prev_day_missed: { items: [], summary: null },
        missing_kline: 0,
        disclaimer: "",
      },
    });
    renderPage();
    expect(screen.getByText("当日无候选推送")).toBeInTheDocument();
  });

  it("无 bought → 当日无新建仓记录", () => {
    qMock.useDailyWinReview.mockReturnValue({
      data: {
        date: "2026-08-11",
        no_snapshot: false,
        pushed: [],
        bought: [],
        missed: [],
        prev_day_missed: { items: [], summary: null },
        missing_kline: 0,
        disclaimer: "",
      },
    });
    renderPage();
    expect(screen.getByText("当日无新建仓记录")).toBeInTheDocument();
  });

  it("无 missed → 当日无漏单", () => {
    qMock.useDailyWinReview.mockReturnValue({
      data: {
        date: "2026-08-11",
        no_snapshot: false,
        pushed: [],
        bought: [],
        missed: [],
        prev_day_missed: { items: [], summary: null },
        missing_kline: 0,
        disclaimer: "",
      },
    });
    renderPage();
    expect(screen.getByText(/当日无漏单/)).toBeInTheDocument();
  });

  it("结算入口链接可达", () => {
    qMock.useDailyWinReview.mockReturnValue({
      data: {
        date: "2026-08-11",
        no_snapshot: false,
        pushed: [],
        bought: [
          { code: "600519", name: "贵州茅台", entry_price: null, strategy: null, status: "holding", placeholder: "待判定" },
        ],
        missed: [],
        prev_day_missed: { items: [], summary: null },
        missing_kline: 0,
        disclaimer: "",
      },
    });
    renderPage();
    expect(screen.getByText("去结算 →")).toBeInTheDocument();
  });

  it("教学点呈现", () => {
    qMock.useDailyWinReview.mockReturnValue({
      data: {
        date: "2026-08-11",
        no_snapshot: false,
        pushed: [],
        bought: [],
        missed: [],
        prev_day_missed: { items: [], summary: null },
        missing_kline: 0,
        disclaimer: "",
      },
    });
    renderPage();
    expect(screen.getByText(/复盘的意义是迭代/)).toBeInTheDocument();
  });

  it("研判呈现（shadow 数据有 tips 时）", () => {
    qMock.useShadowComparison.mockReturnValue({
      data: {
        window_days: 28,
        follow: { n: 0, win_rate: null, avg_return: null },
        feeling: { n: 0, win_rate: null, avg_return: null },
        missed: { n: 0, win_rate: null, avg_return: null, missing_kline: 0, approx_note: "" },
        independence: { agreement_rate: null, feeling_win_rate: null },
        no_suggestion_days: 0,
        sufficient: false,
        disclaimer: "",
      },
    });
    qMock.useDailyWinReview.mockReturnValue({
      data: {
        date: "2026-08-11",
        no_snapshot: false,
        pushed: [],
        bought: [],
        missed: [],
        prev_day_missed: { items: [], summary: null },
        missing_kline: 0,
        disclaimer: "",
      },
    });
    renderPage();
    expect(screen.getByText("行为研判")).toBeInTheDocument();
    expect(screen.getByText(/暂无行为数据/)).toBeInTheDocument();
  });
});
