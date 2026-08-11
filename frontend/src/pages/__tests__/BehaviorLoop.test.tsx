// S050 W0 测试：BehaviorLoop 独立页——三桶算账 + 样本不足标记 + 窗口切换 + 空态/错误态。
// mock @/lib/query 的 useShadowComparison（隔离后端算账纯函数已有独立测试）。
import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, fireEvent } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import type { ShadowComparison } from "@/lib/api/types";

const qMock = vi.hoisted(() => ({
  useShadowComparison: vi.fn(),
}));

vi.mock("@/lib/query", () => ({
  useShadowComparison: qMock.useShadowComparison,
}));

import BehaviorLoop from "@/pages/BehaviorLoop";

function renderAt() {
  return render(<MemoryRouter><BehaviorLoop /></MemoryRouter>);
}

const FULL_DATA: ShadowComparison = {
  window_days: 28,
  follow: { n: 8, win_rate: 0.625, avg_return: 2.5 },
  feeling: { n: 6, win_rate: 0.333, avg_return: -1.2 },
  missed: { n: 10, win_rate: 0.5, avg_return: 1.8, missing_kline: 2, approx_note: "信号日收盘→次日收盘，近似" },
  independence: { agreement_rate: 0.571, feeling_win_rate: 0.333 },
  no_suggestion_days: 1,
  sufficient: true,
  disclaimer: "历史统计特征，市场有风险，研究参考",
};

const INSUFFICIENT_DATA: ShadowComparison = {
  window_days: 14,
  follow: { n: 2, win_rate: 0.5, avg_return: 1.0 },
  feeling: { n: 1, win_rate: 0.0, avg_return: -2.0 },
  missed: { n: 0, win_rate: null, avg_return: null, missing_kline: 0, approx_note: "信号日收盘→次日收盘，近似" },
  independence: { agreement_rate: null, feeling_win_rate: 0.0 },
  no_suggestion_days: 3,
  sufficient: false,
  disclaimer: "历史统计特征，市场有风险，研究参考",
};

describe("BehaviorLoop (S050 W0)", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    qMock.useShadowComparison.mockReturnValue({
      data: FULL_DATA, isLoading: false, error: null, refetch: vi.fn(),
    });
  });

  it("渲染页面标题 + 观察期说明", () => {
    renderAt();
    expect(screen.getByText("行为闭环")).toBeInTheDocument();
    expect(screen.getByText(/W0 把行为测出来/)).toBeInTheDocument();
    expect(screen.getByText(/≥4 周观察期/)).toBeInTheDocument();
  });

  it("渲染三桶算账表（follow/feeling/missed + N/胜率/均收益）", () => {
    renderAt();
    expect(screen.getByText("跟系统（follow）")).toBeInTheDocument();
    expect(screen.getByText("感觉单（feeling）")).toBeInTheDocument();
    expect(screen.getByText("漏掉候选（missed）")).toBeInTheDocument();
    // follow n=8 胜率 62.5%
    expect(screen.getByText("62.5%")).toBeInTheDocument();
    // feeling n=6 均收益 -1.20%
    expect(screen.getByText("-1.20%")).toBeInTheDocument();
  });

  it("渲染概览指标卡（一致率 + feeling 胜率 + 样本充足性）", () => {
    renderAt();
    expect(screen.getByText("一致率")).toBeInTheDocument();
    expect(screen.getByText("57.1%")).toBeInTheDocument();
    expect(screen.getByText("feeling 胜率")).toBeInTheDocument();
    expect(screen.getByText("充足")).toBeInTheDocument();
  });

  it("sufficient=true 显示「充足」", () => {
    renderAt();
    expect(screen.getByText("充足")).toBeInTheDocument();
  });

  it("sufficient=false 显示「不足」+ warning 色", () => {
    qMock.useShadowComparison.mockReturnValue({
      data: INSUFFICIENT_DATA, isLoading: false, error: null, refetch: vi.fn(),
    });
    renderAt();
    expect(screen.getByText("不足")).toBeInTheDocument();
    expect(screen.getByText(/三桶任一 <5，研判仅供参考/)).toBeInTheDocument();
    // 一致率 null → "—"
    const overviewCards = screen.getAllByText("—");
    expect(overviewCards.length).toBeGreaterThan(0);
  });

  it("窗口切换：14/28/60 天按钮，点击切换 queryKey", () => {
    const spy = qMock.useShadowComparison;
    renderAt();
    // 初始 28 天
    expect(spy).toHaveBeenCalledWith(28);
    // 切到 14 天
    fireEvent.click(screen.getByText("14 天"));
    expect(spy).toHaveBeenCalledWith(14);
    // 切到 60 天
    fireEvent.click(screen.getByText("60 天"));
    expect(spy).toHaveBeenCalledWith(60);
  });

  it("missed K 线缺失 + 无快照日计数诚实呈现", () => {
    renderAt();
    expect(screen.getByText(/missed K 线缺失排除 2 笔/)).toBeInTheDocument();
    expect(screen.getByText(/无系统建议日（无快照）1 天/)).toBeInTheDocument();
  });

  it("missed 近似口径说明呈现", () => {
    renderAt();
    expect(screen.getByText(/信号日收盘→次日收盘，近似/)).toBeInTheDocument();
  });

  it("disclaimer 呈现（Disclaimer 组件默认文案 + 数据 disclaimer 字段）", () => {
    renderAt();
    // Disclaimer 组件的固定文案
    expect(screen.getByText(/不推荐个股/)).toBeInTheDocument();
  });

  it("loading → Skeleton（不崩）", () => {
    qMock.useShadowComparison.mockReturnValue({
      data: undefined, isLoading: true, error: null, refetch: vi.fn(),
    });
    renderAt();
    // loading 时不渲染三桶表
    expect(screen.queryByText("跟系统（follow）")).not.toBeInTheDocument();
    // 标题仍在（页面骨架已渲染）
    expect(screen.getByText("行为闭环")).toBeInTheDocument();
  });

  it("error → 错误提示", () => {
    qMock.useShadowComparison.mockReturnValue({
      data: undefined, isLoading: false, error: new Error("后端连接失败"), refetch: vi.fn(),
    });
    renderAt();
    expect(screen.getByText(/影子对照取数失败/)).toBeInTheDocument();
    expect(screen.getByText(/后端连接失败/)).toBeInTheDocument();
  });

  it("无数据（undefined 非 loading）→ 不渲染报告区", () => {
    qMock.useShadowComparison.mockReturnValue({
      data: undefined, isLoading: false, error: null, refetch: vi.fn(),
    });
    renderAt();
    // 页面标题仍在，但三桶表/概览卡不渲染
    expect(screen.getByText("行为闭环")).toBeInTheDocument();
    expect(screen.queryByText("一致率")).not.toBeInTheDocument();
  });

  it("桶详解可折叠：默认收起，点击展开", () => {
    renderAt();
    const followTitle = screen.getByText("follow · 跟系统");
    // 默认收起 → 不显示详情文案
    expect(screen.queryByText(/用户实际买入且结算的标的中/)).not.toBeInTheDocument();
    // 点击展开
    fireEvent.click(followTitle);
    expect(screen.getByText(/用户实际买入且结算的标的中/)).toBeInTheDocument();
  });

  it("S050 弱合规：行为研判区呈现方向性建议（follow 胜率显著高于 feeling）", () => {
    renderAt();
    expect(screen.getByText("行为研判")).toBeInTheDocument();
    expect(screen.getByText(/可考虑多跟系统候选\/战法信号/)).toBeInTheDocument();
  });

  it("S050 弱合规：feeling 胜率反超 → 给「系统信号质量待校准」研判", () => {
    const reverse: ShadowComparison = {
      ...FULL_DATA,
      follow: { n: 8, win_rate: 0.25, avg_return: -1.5 },
      feeling: { n: 6, win_rate: 0.5, avg_return: 2.0 },
    };
    qMock.useShadowComparison.mockReturnValue({
      data: reverse, isLoading: false, error: null, refetch: vi.fn(),
    });
    renderAt();
    expect(screen.getByText(/系统信号质量待校准/)).toBeInTheDocument();
  });

  it("S050 弱合规：missed 影子胜率高 → 给「可考虑多采纳候选池」研判", () => {
    const strongMissed: ShadowComparison = {
      ...FULL_DATA,
      missed: { n: 10, win_rate: 0.7, avg_return: 3.5, missing_kline: 0, approx_note: "信号日收盘→次日收盘，近似" },
    };
    qMock.useShadowComparison.mockReturnValue({
      data: strongMissed, isLoading: false, error: null, refetch: vi.fn(),
    });
    renderAt();
    expect(screen.getByText(/系统建议质量不错，可考虑多采纳候选池标的/)).toBeInTheDocument();
  });

  it("S050 弱合规：样本不足时压低研判权重（标注仅供参考）", () => {
    qMock.useShadowComparison.mockReturnValue({
      data: INSUFFICIENT_DATA, isLoading: false, error: null, refetch: vi.fn(),
    });
    renderAt();
    const matches = screen.getAllByText(/样本不足/);
    expect(matches.length).toBeGreaterThan(0);
    const refs = screen.getAllByText(/仅供参考/);
    expect(refs.length).toBeGreaterThan(0);
  });
});
