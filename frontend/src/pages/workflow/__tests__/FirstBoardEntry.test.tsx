// S075 076：Workflow 首页卡片入口测试。
// mock useFirstBoardCandidates + 原状态机 hooks，验证：
//   - 首板流卡片显示候选 N 只状态徽章
//   - 首板流卡片可点击跳转 /workflow/first-board
//   - 连板流等卡片灰显待实现
//   - workflow 降级入口卡片显示并可切到原状态机看板
import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, fireEvent } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";

const qMocks = vi.hoisted(() => ({
  useWorkflowStatus: vi.fn(),
  usePreMarketBriefing: vi.fn(),
  usePreMarketDates: vi.fn(),
  useWorkflowStates: vi.fn(),
  useFirstBoardCandidates: vi.fn(),
}));

vi.mock("@/lib/query", () => ({
  useWorkflowStatus: qMocks.useWorkflowStatus,
  usePreMarketBriefing: qMocks.usePreMarketBriefing,
  usePreMarketDates: qMocks.usePreMarketDates,
  useWorkflowStates: qMocks.useWorkflowStates,
  useFirstBoardCandidates: qMocks.useFirstBoardCandidates,
}));

// PipelineProgressBar 内部不依赖 query，直接渲染
vi.mock("@/components/workflow/PipelineProgressBar", () => ({
  PipelineProgressBar: () => <div data-testid="pipeline-progress" />,
}));

import Workflow from "@/pages/Workflow";

function renderPage(entry = "/workflow") {
  return render(
    <MemoryRouter initialEntries={[entry]}>
      <Workflow />
    </MemoryRouter>,
  );
}

const mockFirstBoardData = {
  date: "2026-08-18",
  zt_pool_count: 106,
  first_board_count: 91,
  candidates: [
    { code: "001358", name: "兴欣新材", total: 63.4, scores: { sector: 60, hot_money: 70, seal_strength: 80, chip: 50, auction: 50, northbound: 50, institution: 50, theme: 50, event: 50 }, rank: 1 },
    { code: "002567", name: "唐人神", total: 58.2, scores: { sector: 55, hot_money: 65, seal_strength: 70, chip: 50, auction: 50, northbound: 50, institution: 50, theme: 50, event: 50 }, rank: 2 },
  ],
  excluded: [
    { code: "xxx1", layer: 1, reason: "炸板2次" },
    { code: "xxx2", layer: 2, reason: "换手30%筹码松动" },
  ],
  env_flags: { market_drop_pct: 1.41, high_risk: false, max_boards: 4, ladder_broken: false },
  note: "9维度评分§44未validated仅参考；阈值/权重待回测校准",
};

describe("Workflow 首页卡片入口 (S075 076)", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    qMocks.useWorkflowStatus.mockReturnValue({ data: null, isLoading: false, isFetching: false, refetch: vi.fn() });
    qMocks.usePreMarketBriefing.mockReturnValue({ data: null });
    qMocks.usePreMarketDates.mockReturnValue({ data: null });
    qMocks.useWorkflowStates.mockReturnValue({ data: null });
    qMocks.useFirstBoardCandidates.mockReturnValue({ data: mockFirstBoardData, isLoading: false });
  });

  it("首板流卡片渲染 + 状态徽章（候选 N 只）", () => {
    renderPage();
    expect(screen.getByText("首板流")).toBeInTheDocument();
    // 候选数徽章
    expect(screen.getByText(/候选 2 只/)).toBeInTheDocument();
    // 已建仓/T+1卖出徽章
    expect(screen.getByText(/已建仓 0 只/)).toBeInTheDocument();
    expect(screen.getByText(/T\+1 卖出 0 只/)).toBeInTheDocument();
  });

  it("首板流卡片可点击跳转（Link 包裹，href 含 /workflow/first-board）", () => {
    renderPage();
    const card = screen.getByText("首板流").closest("a");
    expect(card).not.toBeNull();
    expect(card?.getAttribute("href")).toContain("/workflow/first-board");
  });

  it("连板流/炸板回交流等卡片灰显待实现（无 Link 跳转）", () => {
    renderPage();
    expect(screen.getByText("连板流")).toBeInTheDocument();
    expect(screen.getByText("炸板回交流")).toBeInTheDocument();
    expect(screen.getByText("低吸流")).toBeInTheDocument();
    expect(screen.getByText("反包流")).toBeInTheDocument();
    expect(screen.getByText("N字反击流")).toBeInTheDocument();
    // 待实现卡片不应该是 Link（不可点击）
    expect(screen.getByText("连板流").closest("a")).toBeNull();
  });

  it("workflow 降级入口卡片渲染 + 点击切到原状态机看板", () => {
    renderPage();
    expect(screen.getByText(/状态机看板（降级入口）/)).toBeInTheDocument();
    expect(screen.getByText(/盘前 · 盘中 · 盘后 状态机/)).toBeInTheDocument();
    // 点击降级入口卡片
    fireEvent.click(screen.getByText(/盘前 · 盘中 · 盘后 状态机/));
    // 切换后应显示原状态机看板标题 "Workflow"
    expect(screen.getAllByText("Workflow").length).toBeGreaterThan(0);
    expect(screen.getByText(/← 返回卡片入口/)).toBeInTheDocument();
  });

  it("首板流卡片标注 §44 未 validated", () => {
    renderPage();
    expect(screen.getByText(/§44 未 validated 仅参考/)).toBeInTheDocument();
  });
});
