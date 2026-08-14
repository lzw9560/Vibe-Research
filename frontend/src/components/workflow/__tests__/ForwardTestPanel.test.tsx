// S066 §11.4 ForwardTestPanel 组件测试。
import { describe, it, expect, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { ForwardTestPanel } from "@/components/workflow/ForwardTestPanel";

const mockSummary = vi.hoisted(() => ({ useForwardTestSummary: vi.fn() }));

vi.mock("@/lib/query/strategy", () => ({
  useForwardTestSummary: mockSummary.useForwardTestSummary,
}));

import { ForwardTestPanel as Panel } from "@/components/workflow/ForwardTestPanel";

function renderPanel() {
  return render(
    <MemoryRouter>
      <Panel />
    </MemoryRouter>,
  );
}

describe("ForwardTestPanel (S066)", () => {
  it("loading 态显示 Skeleton", () => {
    mockSummary.useForwardTestSummary.mockReturnValue({ isLoading: true, data: undefined });
    const { container } = renderPanel();
    // Skeleton 渲染（无文案）
    expect(screen.queryByText("前向测试（Paper Trading）")).not.toBeInTheDocument();
  });

  it("无数据 → 显示未取得", () => {
    mockSummary.useForwardTestSummary.mockReturnValue({ isLoading: false, data: undefined });
    renderPanel();
    expect(screen.getByText("前向测试数据未取得")).toBeInTheDocument();
  });

  it("通过测试 → 显示通过横幅", () => {
    mockSummary.useForwardTestSummary.mockReturnValue({
      isLoading: false,
      data: {
        total_days: 20, total_recommendations: 40, settled_count: 40,
        win_count: 32, win_rate: 80.0, avg_return: 1.5,
        benchmark_win_rate: 60.0, pass_threshold: 48.0,
        passed: true, consecutive_loss: 1, note: "前向测试通过",
      },
    });
    renderPanel();
    // "前向测试通过" 出现在横幅标题 + note，用 getAllByText
    expect(screen.getAllByText(/前向测试通过/).length).toBeGreaterThanOrEqual(1);
    expect(screen.getAllByText(/80\.0%/).length).toBeGreaterThanOrEqual(1);
  });

  it("不通过 → 显示进行中", () => {
    mockSummary.useForwardTestSummary.mockReturnValue({
      isLoading: false,
      data: {
        total_days: 5, total_recommendations: 10, settled_count: 10,
        win_count: 3, win_rate: 30.0, avg_return: -0.5,
        benchmark_win_rate: 60.0, pass_threshold: 48.0,
        passed: false, consecutive_loss: 2,
        note: "样本不足：5/20 交易日",
      },
    });
    renderPanel();
    expect(screen.getByText("前向测试进行中")).toBeInTheDocument();
    expect(screen.getByText("5/20 日")).toBeInTheDocument();
  });

  it("kill criteria 预警（连续亏损>=5）", () => {
    mockSummary.useForwardTestSummary.mockReturnValue({
      isLoading: false,
      data: {
        total_days: 20, total_recommendations: 40, settled_count: 40,
        win_count: 10, win_rate: 25.0, avg_return: -1.0,
        benchmark_win_rate: 60.0, pass_threshold: 48.0,
        passed: false, consecutive_loss: 6,
        note: "胜率 25% < 阈值 48%；连续亏损预警",
      },
    });
    renderPanel();
    expect(screen.getByText("Kill Criteria 预警")).toBeInTheDocument();
  });

  it("显示核心指标卡片", () => {
    mockSummary.useForwardTestSummary.mockReturnValue({
      isLoading: false,
      data: {
        total_days: 20, total_recommendations: 40, settled_count: 40,
        win_count: 32, win_rate: 80.0, avg_return: 1.5,
        benchmark_win_rate: 60.0, pass_threshold: 48.0,
        passed: true, consecutive_loss: 1, note: "通过",
      },
    });
    renderPanel();
    expect(screen.getByText("已结算推荐")).toBeInTheDocument();
    expect(screen.getByText("胜率")).toBeInTheDocument();
    expect(screen.getByText("平均收益")).toBeInTheDocument();
    expect(screen.getByText("连续亏损")).toBeInTheDocument();
  });

  it("显示验证进度条", () => {
    mockSummary.useForwardTestSummary.mockReturnValue({
      isLoading: false,
      data: {
        total_days: 10, total_recommendations: 20, settled_count: 20,
        win_count: 12, win_rate: 60.0, avg_return: 0.5,
        benchmark_win_rate: 60.0, pass_threshold: 48.0,
        passed: false, consecutive_loss: 0, note: "进行中",
      },
    });
    renderPanel();
    expect(screen.getByText("验证进度")).toBeInTheDocument();
    expect(screen.getByText("10/20 交易日")).toBeInTheDocument();
  });

  it("跑赢基准显示 alpha 存在", () => {
    mockSummary.useForwardTestSummary.mockReturnValue({
      isLoading: false,
      data: {
        total_days: 20, total_recommendations: 40, settled_count: 40,
        win_count: 32, win_rate: 80.0, avg_return: 1.5,
        benchmark_win_rate: 60.0, pass_threshold: 48.0,
        passed: true, consecutive_loss: 1, note: "通过",
      },
    });
    renderPanel();
    expect(screen.getByText(/跑赢基准，alpha 存在/)).toBeInTheDocument();
  });
});
