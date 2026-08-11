// S051 D3 测试：GeneScreener 分段视图——qualified/all/custom 切换 + 未合格行降级 + warnings 回显。
// mock @/lib/limitup 的 getGeneScreener/saveGeneParams/triggerGenePrecompute/getGeneParams。
import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import type { GeneScore, ScreenerResult } from "@/lib/api";

const lMocks = vi.hoisted(() => ({
  getGeneScreener: vi.fn(),
  saveGeneParams: vi.fn(),
  triggerGenePrecompute: vi.fn(),
  getGeneParams: vi.fn(),
}));

vi.mock("@/lib/limitup", () => ({
  getGeneScreener: lMocks.getGeneScreener,
  saveGeneParams: lMocks.saveGeneParams,
  triggerGenePrecompute: lMocks.triggerGenePrecompute,
  getGeneParams: lMocks.getGeneParams,
}));

import GeneScreener from "@/pages/limitup/GeneScreener";

const SCORES: GeneScore[] = [
  { code: "600519", name: "贵州茅台", total_score: 64.39, qualify: true, high_gene: true, factors: {}, wilson_adjusted: 60, zt_count_250d: 1, last_zt_dates: [], backtest_points: [], backtest_summary: null } as unknown as GeneScore,
  { code: "600721", name: "百花医药", total_score: 55.05, qualify: true, high_gene: false, factors: {}, wilson_adjusted: 52, zt_count_250d: 0, last_zt_dates: [], backtest_points: [], backtest_summary: null } as unknown as GeneScore,
  { code: "002552", name: "宝鼎科技", total_score: 50.72, qualify: true, high_gene: false, factors: {}, wilson_adjusted: 48, zt_count_250d: 0, last_zt_dates: [], backtest_points: [], backtest_summary: null } as unknown as GeneScore,
  { code: "000001", name: "平安银行", total_score: 40.0, qualify: false, high_gene: false, factors: {}, wilson_adjusted: 38, zt_count_250d: 0, last_zt_dates: [], backtest_points: [], backtest_summary: null } as unknown as GeneScore,
];

function renderPage() {
  return render(<MemoryRouter><GeneScreener /></MemoryRouter>);
}

describe("GeneScreener 分段视图 (S051 D3)", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    lMocks.getGeneParams.mockResolvedValue({ gene_qualify_threshold: 50, gene_high_threshold: 60, lookback_days: 252 });
    lMocks.getGeneScreener.mockResolvedValue({ gene_scores: SCORES, data_freshness: "fresh" } as unknown as ScreenerResult);
    lMocks.saveGeneParams.mockResolvedValue({ status: "ok" });
    lMocks.triggerGenePrecompute.mockResolvedValue({ status: "started", date: "2026-08-11" });
  });

  it("默认 qualified 视图：只显示 qualify=true 行（3 行）", async () => {
    renderPage();
    await waitFor(() => {
      expect(screen.getByText("600519")).toBeInTheDocument();
    });
    // 000001 不合格不显示
    expect(screen.queryByText("000001")).not.toBeInTheDocument();
    // 摘要：合格 3 只（合格数字与「只」字分属不同 span，取数字所在 span）
    expect(screen.getByText("3")).toBeInTheDocument();
  });

  it("切「全部」→ 显示全量 4 行 + 未合格行降级（未合格标签）", async () => {
    renderPage();
    await waitFor(() => expect(screen.getByText("600519")).toBeInTheDocument());
    // 切全部（按钮文本精确匹配）
    const allBtn = screen.getByRole("button", { name: "全部" });
    fireEvent.click(allBtn);
    expect(await screen.findByText("000001")).toBeInTheDocument();
    expect(screen.getByText("未合格")).toBeInTheDocument();
  });

  it("切「自定义分数段」→ 按分数区间过滤", async () => {
    renderPage();
    await waitFor(() => expect(screen.getByText("600519")).toBeInTheDocument());
    // 切自定义
    fireEvent.click(screen.getByRole("button", { name: "自定义分数段" }));
    // 设置 minScore=50 maxScore=55 → 只留 50.72 和 55.05
    const inputs = screen.getAllByRole("spinbutton");
    fireEvent.change(inputs[0], { target: { value: "50" } });  // minScore
    fireEvent.change(inputs[1], { target: { value: "55" } });  // maxScore
    fireEvent.click(screen.getByRole("button", { name: "筛选" }));
    // 50.72 留，55.05 留，64.39 超出移除
    expect(await screen.findByText("002552")).toBeInTheDocument();  // 50.72
    await waitFor(() => {
      expect(screen.queryByText("600519")).not.toBeInTheDocument();  // 64.39 超出
    });
  });

  it("空态：qualified 模式无合格标的 → 提示「全部」查看", async () => {
    lMocks.getGeneScreener.mockResolvedValue({
      gene_scores: [{ code: "000001", name: "平安", total_score: 40, qualify: false, high_gene: false, factors: {}, wilson_adjusted: 38, zt_count_250d: 0, last_zt_dates: [] }],
      data_freshness: "fresh",
    } as unknown as ScreenerResult);
    renderPage();
    await waitFor(() => {
      expect(screen.getByText(/今日无合格标的/)).toBeInTheDocument();
    });
  });

  it("D2：保存并重算 → warnings 回显（阈值越界提醒）", async () => {
    lMocks.saveGeneParams.mockResolvedValue({
      status: "ok",
      warnings: ["高基因阈值 80 高于近 30 日最高分 70.63，high_gene 将恒为空"],
    });
    renderPage();
    await waitFor(() => expect(screen.getByText("600519")).toBeInTheDocument());
    // 展开阈值配置
    fireEvent.click(screen.getByText("阈值配置"));
    fireEvent.click(screen.getByText("保存并重算"));
    await waitFor(() => {
      expect(screen.getByText(/high_gene 将恒为空/)).toBeInTheDocument();
    });
  });
});
