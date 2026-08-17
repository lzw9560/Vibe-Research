// S075 078：StrategyAttributionTab 战法归因深看测试。
// mock useFirstBoardCandidates，验证：
//   - 候选 × 多战法 match_strategies 矩阵渲染
//   - 同股多战法不排除标注
//   - §44 未 validated 仅复盘参考标注
import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";

import { StrategyAttributionTab } from "@/pages/workflow/components/StrategyAttributionTab";
import type { FirstBoardCandidatesResponse } from "@/lib/api";

const mockData: FirstBoardCandidatesResponse = {
  date: "2026-08-18",
  zt_pool_count: 106,
  first_board_count: 91,
  candidates: [
    {
      code: "001358", name: "兴欣新材", total: 63.4, rank: 1,
      scores: { sector: 60, hot_money: 70, seal_strength: 80, chip: 50, auction: 50, northbound: 50, institution: 50, theme: 50, event: 50 },
    },
    {
      code: "002567", name: "唐人神", total: 58.2, rank: 2,
      scores: { sector: 55, hot_money: 65, seal_strength: 70, chip: 50, auction: 50, northbound: 50, institution: 50, theme: 50, event: 50 },
    },
  ],
  excluded: [],
  env_flags: { market_drop_pct: 1.41, high_risk: false, max_boards: 4, ladder_broken: false },
  note: "9维度评分§44未validated仅参考；阈值/权重待回测校准",
};

function renderTab(data: FirstBoardCandidatesResponse | null = mockData) {
  return render(
    <MemoryRouter>
      <StrategyAttributionTab data={data} />
    </MemoryRouter>,
  );
}

describe("StrategyAttributionTab 战法归因 (S075 078)", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it("§44 未 validated 仅复盘参考标注渲染（顶部）", () => {
    renderTab();
    expect(screen.getByText(/§44 未 validated 仅复盘参考/)).toBeInTheDocument();
    expect(screen.getByText(/战法归因结果基于 9 维度评分/)).toBeInTheDocument();
  });

  it("候选评分明细表渲染（9 维度列）", () => {
    renderTab();
    expect(screen.getByText("候选评分明细（9 维度）")).toBeInTheDocument();
    // 列头
    expect(screen.getByText("板块")).toBeInTheDocument();
    expect(screen.getByText("游资")).toBeInTheDocument();
    expect(screen.getByText("封板")).toBeInTheDocument();
    expect(screen.getByText("筹码")).toBeInTheDocument();
    expect(screen.getByText("竞价")).toBeInTheDocument();
    expect(screen.getByText("北向")).toBeInTheDocument();
    expect(screen.getByText("机构")).toBeInTheDocument();
    expect(screen.getByText("题材")).toBeInTheDocument();
    expect(screen.getByText("事件")).toBeInTheDocument();
  });

  it("战法 × 候选 命中矩阵渲染", () => {
    renderTab();
    expect(screen.getByText("战法 × 候选 命中矩阵")).toBeInTheDocument();
    // 8 战法列头（"突破"/"反包"等词在提示文案也出现 → getAllByText）
    expect(screen.getAllByText("突破").length).toBeGreaterThan(0);
    expect(screen.getAllByText("反包").length).toBeGreaterThan(0);
    expect(screen.getAllByText("低吸").length).toBeGreaterThan(0);
    expect(screen.getAllByText("接力").length).toBeGreaterThan(0);
    expect(screen.getAllByText("暴风雨反转").length).toBeGreaterThan(0);
    expect(screen.getAllByText("N字反击").length).toBeGreaterThan(0);
    expect(screen.getAllByText("首板").length).toBeGreaterThan(0);
    expect(screen.getAllByText("连板").length).toBeGreaterThan(0);
  });

  it("同股多战法命中不排除标注渲染", () => {
    renderTab();
    expect(screen.getByText("同股多战法命中不排除")).toBeInTheDocument();
    expect(screen.getByText(/一只股可能同时满足多个战法触发条件/)).toBeInTheDocument();
  });

  it("候选 total≥60 标记首板战法命中", () => {
    renderTab();
    // 001358 total=63.4 → 首板战法命中
    // 002567 total=58.2 → 首板战法未命中
    // "首板 ✓" 标记存在
    expect(screen.getAllByText(/首板/).length).toBeGreaterThan(0);
    // 001358 在评分表和命中矩阵两处出现 → getAllByText
    const cells1358 = screen.getAllByText("001358");
    expect(cells1358.length).toBeGreaterThan(0);
    // 命中矩阵行（命中矩阵在 "战法 × 候选 命中矩阵" 之后）
    const matrixSection = screen.getByText("战法 × 候选 命中矩阵").closest("div");
    const matrixRows = matrixSection?.querySelectorAll("tbody tr");
    expect(matrixRows).not.toBeUndefined();
    expect((matrixRows ?? []).length).toBeGreaterThan(0);
    // 第一行（001358）应有 "首板 ✓" 标记
    const firstRow = (matrixRows ?? [])[0];
    expect(firstRow).toBeDefined();
    expect(firstRow?.textContent).toContain("001358");
    expect(firstRow?.textContent).toContain("首板");
    expect(firstRow?.textContent).toContain("✓");
  });

  it("候选为空时不崩（空态）", () => {
    const emptyData: FirstBoardCandidatesResponse = {
      date: "2026-08-18",
      zt_pool_count: 0,
      first_board_count: 0,
      candidates: [],
      excluded: [],
      env_flags: { market_drop_pct: null, high_risk: false, max_boards: null, ladder_broken: false },
      note: "空",
    };
    renderTab(emptyData);
    // 候选池为空在评分表和命中矩阵两处渲染 → getAllByText
    expect(screen.getAllByText("候选池为空").length).toBeGreaterThan(0);
  });

  it("待 P4 占位标记（非首板战法）", () => {
    renderTab();
    expect(screen.getAllByText("待 P4").length).toBeGreaterThan(0);
  });
});
