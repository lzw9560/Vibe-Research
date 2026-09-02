// S093 T16 + S146：WatchlistBoard 渲染测试——三组分组 + 卡片 + 空态 + loading。
// CV 重定向涨停叉内（final∩scored）：dual/funnelOnly/strategyOnly（原 breakoutOnly 弃，breakout 移研究）。
import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, fireEvent } from "@testing-library/react";
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

const PROPS = { F: "2026-08-21", date: "2026-08-22" };

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
    cvMock.mockReturnValue({ dual: [], funnelOnly: [], strategyOnly: [], isLoading: false });
    quoteMock.mockReturnValue({ data: undefined });
    statesMock.mockReturnValue({ data: undefined });
  });

  it("loading → 骨架屏", () => {
    cvMock.mockReturnValue({ dual: [], funnelOnly: [], strategyOnly: [], isLoading: true });
    renderBoard();
    expect(screen.getByText("前瞻结论标的看板")).toBeInTheDocument();
  });

  it("无标的 → 空态文案", () => {
    renderBoard();
    expect(screen.getByText(/前瞻 Tab 尚无选股结论/)).toBeInTheDocument();
  });

  it("三组分组渲染 + 卡片显示 code（双重确认默认展开，其余点击展开）", () => {
    cvMock.mockReturnValue({
      dual: [{ code: "600519", name: "贵州茅台", geneScore: 65.2, strategyName: "连板接力", strategyScore: 72.5, source: "dual" }],
      funnelOnly: [{ code: "000001", name: "平安银行", geneScore: 50.1, strategyName: "首板挖掘", strategyScore: 40.0, source: "funnelOnly" }],
      strategyOnly: [{ code: "300750", name: "宁德时代", strategyName: "平台突破", strategyScore: 55.0, source: "strategyOnly" }],
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
    // 三组 label（header 始终显）
    expect(screen.getByText("双指标重叠")).toBeInTheDocument();
    expect(screen.getAllByText("仅漏斗终选").length).toBeGreaterThanOrEqual(1);
    expect(screen.getAllByText("仅战法命中").length).toBeGreaterThanOrEqual(1);
    // 双重确认默认展开 → 贵州茅台 立即可见
    expect(screen.getByText("贵州茅台")).toBeInTheDocument();
    // 仅漏斗终选 / 仅战法命中 默认收缩 → 懒渲染未出，平安银行/宁德时代 不在 DOM
    expect(screen.queryByText("平安银行")).not.toBeInTheDocument();
    expect(screen.queryByText("宁德时代")).not.toBeInTheDocument();
    // 点击展开 仅漏斗终选
    fireEvent.click(screen.getByRole("button", { name: /仅漏斗终选/ }));
    expect(screen.getByText("平安银行")).toBeInTheDocument();
    // 点击展开 仅战法命中
    fireEvent.click(screen.getByRole("button", { name: /仅战法命中/ }));
    expect(screen.getByText("宁德时代")).toBeInTheDocument();
  });

  it("双重确认组默认展开（▶/▼ 状态）", () => {
    cvMock.mockReturnValue({
      dual: [{ code: "600519", name: "贵州茅台", source: "dual" }],
      funnelOnly: [],
      strategyOnly: [],
      isLoading: false,
    });
    quoteMock.mockReturnValue({ data: undefined });
    renderBoard();
    // dual 默认展开 → 候选立即渲染
    expect(screen.getByText("贵州茅台")).toBeInTheDocument();
  });

  it("仅漏斗终选默认收缩 → 点击展开后显候选", () => {
    cvMock.mockReturnValue({
      dual: [],
      funnelOnly: [{ code: "000001", name: "平安银行", source: "funnelOnly" }],
      strategyOnly: [],
      isLoading: false,
    });
    quoteMock.mockReturnValue({ data: undefined });
    renderBoard();
    // 默认收缩 → 不渲染
    expect(screen.queryByText("平安银行")).not.toBeInTheDocument();
    // 点击展开
    fireEvent.click(screen.getByRole("button", { name: /仅漏斗终选/ }));
    expect(screen.getByText("平安银行")).toBeInTheDocument();
  });

  it("持仓状态徽章渲染（holding → 绿色徽章）", () => {
    cvMock.mockReturnValue({
      dual: [{ code: "600519", name: "贵州茅台", source: "dual" }],
      funnelOnly: [],
      strategyOnly: [],
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
      strategyOnly: [],
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
      strategyOnly: [],
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
      strategyOnly: [],
      isLoading: false,
    });
    quoteMock.mockReturnValue({ data: undefined });
    renderBoard();
    expect(screen.getByText(/参考值，非执行指令/)).toBeInTheDocument();
  });
});
