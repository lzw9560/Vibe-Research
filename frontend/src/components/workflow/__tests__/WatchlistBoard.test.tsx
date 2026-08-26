// S093 T16：WatchlistBoard 渲染测试——三组分组 + 卡片 + 空态 + loading。
import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";

const cvMock = vi.hoisted(() => vi.fn());
const quoteMock = vi.hoisted(() => vi.fn());
const statesMock = vi.hoisted(() => vi.fn());

vi.mock("@/lib/query/useCrossValidation", () => ({
  useCrossValidationGroups: cvMock,
}));
vi.mock("@/lib/query", () => ({
  useQuote: quoteMock,
  useWorkflowStates: statesMock,
}));

import { WatchlistBoard } from "@/components/workflow/WatchlistBoard";

const PROPS = { F: "2026-08-21", forward: "2026-08-22", date: "2026-08-22" };

function renderBoard() {
  return render(
    <MemoryRouter>
      <WatchlistBoard {...PROPS} />
    </MemoryRouter>,
  );
}

describe("WatchlistBoard (S093 T16)", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    cvMock.mockReturnValue({ dual: [], funnelOnly: [], breakoutOnly: [], isLoading: false });
    quoteMock.mockReturnValue({ data: undefined });
    statesMock.mockReturnValue({ data: undefined });
  });

  it("loading → 骨架屏", () => {
    cvMock.mockReturnValue({ dual: [], funnelOnly: [], breakoutOnly: [], isLoading: true });
    renderBoard();
    expect(screen.getByText("前瞻结论标的看板")).toBeInTheDocument();
  });

  it("无标的 → 空态文案", () => {
    renderBoard();
    expect(screen.getByText(/前瞻 Tab 尚无选股结论/)).toBeInTheDocument();
  });

  it("三组分组渲染 + 卡片显示 code", () => {
    cvMock.mockReturnValue({
      dual: [{ code: "600519", name: "贵州茅台", geneScore: 65.2, strategyName: "连板接力", strategyScore: 72.5, breakoutScore: 0.95, source: "dual" }],
      funnelOnly: [{ code: "000001", name: "平安银行", geneScore: 50.1, strategyName: "首板挖掘", strategyScore: 40.0, source: "funnelOnly" }],
      breakoutOnly: [{ code: "300750", name: "宁德时代", breakoutScore: 0.88, source: "breakoutOnly" }],
      isLoading: false,
    });
    quoteMock.mockReturnValue({
      data: {
        "600519": { name: "贵州茅台", price: 1800.5, last_close: 1780, change_pct: 1.15, pe_ttm: 30, pb: 10, turnover_pct: 0.5, limit_up_price: 1958, limit_down_price: 1602 },
        "000001": { name: "平安银行", price: 12.34, last_close: 12.2, change_pct: 1.15, pe_ttm: 5, pb: 0.6, turnover_pct: 1.2, limit_up_price: 13.42, limit_down_price: 10.98 },
        "300750": { name: "宁德时代", price: 250.0, last_close: 240, change_pct: 4.17, pe_ttm: 50, pb: 5, turnover_pct: 2.0, limit_up_price: 264, limit_down_price: 216 },
      },
    });
    renderBoard();
    // 三组 label
    expect(screen.getByText("双重确认")).toBeInTheDocument();
    expect(screen.getAllByText("仅漏斗").length).toBeGreaterThanOrEqual(1);
    expect(screen.getAllByText("仅 breakout").length).toBeGreaterThanOrEqual(1);
    // 卡片 股票名
    expect(screen.getByText("贵州茅台")).toBeInTheDocument();
    expect(screen.getByText("平安银行")).toBeInTheDocument();
    expect(screen.getByText("宁德时代")).toBeInTheDocument();
  });

  it("持仓状态徽章渲染（holding → 绿色徽章）", () => {
    cvMock.mockReturnValue({
      dual: [{ code: "600519", name: "贵州茅台", source: "dual" }],
      funnelOnly: [],
      breakoutOnly: [],
      isLoading: false,
    });
    quoteMock.mockReturnValue({ data: undefined });
    statesMock.mockReturnValue({
      data: { date: "2026-08-22", states: [{ code: "600519", status: "holding" }], counts: { holding: 1 } },
    });
    renderBoard();
    expect(screen.getByText("持仓")).toBeInTheDocument();
  });

  it("封板状态渲染（price >= limit_up_price → 封板）", () => {
    cvMock.mockReturnValue({
      dual: [{ code: "600519", name: "贵州茅台", source: "dual" }],
      funnelOnly: [],
      breakoutOnly: [],
      isLoading: false,
    });
    quoteMock.mockReturnValue({
      data: {
        "600519": { name: "贵州茅台", price: 1958, last_close: 1780, change_pct: 10.0, pe_ttm: 30, pb: 10, turnover_pct: 0.5, limit_up_price: 1958, limit_down_price: 1602 },
      },
    });
    renderBoard();
    expect(screen.getByText(/封板/)).toBeInTheDocument();
  });

  it("无 quote 数据 → 标「实时价格待接入」", () => {
    cvMock.mockReturnValue({
      dual: [{ code: "600519", name: "贵州茅台", source: "dual" }],
      funnelOnly: [],
      breakoutOnly: [],
      isLoading: false,
    });
    quoteMock.mockReturnValue({ data: undefined });
    renderBoard();
    expect(screen.getByText("实时价格待接入")).toBeInTheDocument();
  });

  it("参考值非执行指令标注", () => {
    cvMock.mockReturnValue({
      dual: [{ code: "600519", name: "贵州茅台", source: "dual" }],
      funnelOnly: [],
      breakoutOnly: [],
      isLoading: false,
    });
    quoteMock.mockReturnValue({ data: undefined });
    renderBoard();
    expect(screen.getByText(/参考值，非执行指令/)).toBeInTheDocument();
  });
});
