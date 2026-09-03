// S093 T16 + S146：WatchlistBoard 渲染测试——final_candidates flat grid + 卡片 + 空态 + loading。
// 交叉验证（CV 三组 dual/funnelOnly/strategyOnly）已删——两 <2x 弱信号交集无 validated edge（§44）+ scored⊆finals 非真双路。
// 改用 final_candidates 直接列，去 CollapsibleGroup + CrossValidationBadge。
import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";

const briefingMock = vi.hoisted(() => vi.fn());
const quoteMock = vi.hoisted(() => vi.fn());
const statesMock = vi.hoisted(() => vi.fn());

vi.mock("@/lib/query", () => ({
  usePreMarketBriefing: briefingMock,
  useQuote: quoteMock,
  useWorkflowStates: statesMock,
}));

import { WatchlistBoard } from "@/components/workflow/WatchlistBoard";

const PROPS = { date: "2026-08-22" };

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
    briefingMock.mockReturnValue({ data: undefined, isLoading: false });
    quoteMock.mockReturnValue({ data: undefined });
    statesMock.mockReturnValue({ data: undefined });
  });

  it("loading → 骨架屏", () => {
    briefingMock.mockReturnValue({ data: undefined, isLoading: true });
    renderBoard();
    expect(screen.getByText("前瞻结论标的看板")).toBeInTheDocument();
  });

  it("无标的 → 空态文案", () => {
    renderBoard();
    expect(screen.getByText(/前瞻 Tab 尚无选股结论/)).toBeInTheDocument();
  });

  it("finals 渲染 + 卡片显示 name/code", () => {
    briefingMock.mockReturnValue({
      data: {
        final_candidates: [
          { code: "600519", name: "贵州茅台", gene_score: { total_score: 65.2 } },
          { code: "000001", name: "平安银行", gene_score: { total_score: 50.1 } },
        ],
      },
      isLoading: false,
    });
    quoteMock.mockReturnValue({
      data: {
        "600519": { name: "贵州茅台", price: 1800.5, change_pct: 1.15, limit_up_price: 1958 },
        "000001": { name: "平安银行", price: 12.34, change_pct: 1.15, limit_up_price: 13.42 },
      },
    });
    renderBoard();
    expect(screen.getByText("贵州茅台")).toBeInTheDocument();
    expect(screen.getByText("平安银行")).toBeInTheDocument();
  });

  it("持仓状态徽章渲染（holding → 徽章）", () => {
    briefingMock.mockReturnValue({
      data: { final_candidates: [{ code: "600519", name: "贵州茅台" }] },
      isLoading: false,
    });
    statesMock.mockReturnValue({
      data: { date: "2026-08-22", states: [{ code: "600519", status: "holding" }], counts: { holding: 1 } },
    });
    renderBoard();
    expect(screen.getByText("持仓")).toBeInTheDocument();
  });

  it("封板状态渲染（price >= limit_up_price → 封板）", () => {
    briefingMock.mockReturnValue({
      data: { final_candidates: [{ code: "600519", name: "贵州茅台" }] },
      isLoading: false,
    });
    quoteMock.mockReturnValue({
      data: { "600519": { name: "贵州茅台", price: 1958, change_pct: 10.0, limit_up_price: 1958 } },
    });
    renderBoard();
    expect(screen.getByText(/封板/)).toBeInTheDocument();
  });

  it("无 quote 数据 → 标「实时价格待接入」", () => {
    briefingMock.mockReturnValue({
      data: { final_candidates: [{ code: "600519", name: "贵州茅台" }] },
      isLoading: false,
    });
    renderBoard();
    expect(screen.getByText("实时价格待接入")).toBeInTheDocument();
  });

  it("参考值非执行指令标注", () => {
    briefingMock.mockReturnValue({
      data: { final_candidates: [{ code: "600519", name: "贵州茅台" }] },
      isLoading: false,
    });
    renderBoard();
    expect(screen.getByText(/参考值，非执行指令/)).toBeInTheDocument();
  });
});
