// S093 T19：StrategyPage 渲染测试。
// mock @tanstack/react-query（useQuery）+ @/lib/api/client（request）+ @/lib/query/strategy（useStrategyBacktest）。
// MemoryRouter 驱动 Link。
import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";

// ---- mock hooks ----
const strategyMocks = vi.hoisted(() => ({
  useStrategyBacktest: vi.fn(),
}));

vi.mock("@/lib/query/strategy", () => ({
  useStrategyBacktest: strategyMocks.useStrategyBacktest,
}));

// mock useQuery（registry 查询）+ request（避免真请求）
const useQueryMock = vi.fn();
vi.mock("@tanstack/react-query", () => ({
  useQuery: (...args: unknown[]) => useQueryMock(...args),
}));
vi.mock("@/lib/api/client", () => ({
  request: vi.fn(),
}));

import StrategyPage from "@/pages/strategy/StrategyPage";

/** 假战法注册表（2 条，覆盖有/无回测数据两种情况）。 */
const MOCK_REGISTRY = [
  {
    code: "breakout",
    name: "突破战法",
    entry_type: "limitup",
    entry_condition: "close > 20日新高",
    stop_loss_condition: "跌破 5 日均线",
    take_profit_condition: "+10%",
    exit_condition: "持有到期或止损",
    max_hold_days: 3,
    weather_regimes: ["sunny"],
    aliases: [],
  },
  {
    code: "reversal",
    name: "反转战法",
    entry_type: "market_scan",
    entry_condition: "STI < 30 且缩量",
    stop_loss_condition: "跌破前低",
    take_profit_condition: "+8%",
    exit_condition: "持有到期或止损",
    max_hold_days: 5,
    weather_regimes: ["storm"],
    aliases: [],
  },
];

/** 假回测数据（只有 breakout 有回测，reversal 无回测——测 "—" 降级）。 */
const MOCK_BACKTEST = [
  {
    strategy: "突破战法",
    strategy_code: "breakout",
    win_rate: 0.55,
    avg_return: 2.3,
    sample_size: 20,
    available_days: 60,
    note: "",
  },
];

function renderPage() {
  return render(
    <MemoryRouter initialEntries={["/strategy"]}>
      <StrategyPage />
    </MemoryRouter>,
  );
}

describe("StrategyPage (S093 T19)", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    // useQuery mock：registry 查询返 MOCK_REGISTRY
    useQueryMock.mockReturnValue({ data: MOCK_REGISTRY, isLoading: false });
    // useStrategyBacktest mock：返 MOCK_BACKTEST
    strategyMocks.useStrategyBacktest.mockReturnValue({
      data: MOCK_BACKTEST,
      isLoading: false,
    });
  });

  it("渲染 PageHeader 标题'战法管理'", () => {
    renderPage();
    expect(screen.getByText("战法管理")).toBeInTheDocument();
  });

  it("渲染返回工作流链接", () => {
    renderPage();
    const backLink = screen.getByText("返回工作流");
    expect(backLink.closest("a")).toHaveAttribute("href", "/workflow");
  });

  it("渲染战法战绩表——注册表条目全部出现", () => {
    renderPage();
    expect(screen.getByText("突破战法")).toBeInTheDocument();
    expect(screen.getByText("反转战法")).toBeInTheDocument();
  });

  it("有回测数据的战法显示胜率/均收益/样本", () => {
    renderPage();
    // breakout: win_rate=0.55 → "55.0%"
    expect(screen.getByText("55.0%")).toBeInTheDocument();
    // breakout: avg_return=2.3
    expect(screen.getByText("2.3")).toBeInTheDocument();
    // breakout: sample_size=20
    expect(screen.getByText("20")).toBeInTheDocument();
  });

  it("无回测数据的战法字段显示'—'", () => {
    renderPage();
    // reversal 无回测——胜率/均收益/样本应显"—"
    const dashes = screen.getAllByText("—");
    // 至少 3 个 "—"（胜率/均收益/样本各 1）
    expect(dashes.length).toBeGreaterThanOrEqual(3);
  });

  it("渲染持有日列——max_hold_days", () => {
    renderPage();
    // breakout max_hold_days=3, reversal max_hold_days=5
    expect(screen.getByText("3")).toBeInTheDocument();
    expect(screen.getByText("5")).toBeInTheDocument();
  });

  it("渲染入场条件列", () => {
    renderPage();
    expect(screen.getByText("close > 20日新高")).toBeInTheDocument();
    expect(screen.getByText("STI < 30 且缩量")).toBeInTheDocument();
  });

  it("渲染前向测试入口 EntryCard", () => {
    renderPage();
    expect(screen.getByText("前向测试 §44")).toBeInTheDocument();
    expect(screen.getByText("60 日复验 lift/winrate/validation_status")).toBeInTheDocument();
  });

  it("渲染阈值配置入口 EntryCard", () => {
    renderPage();
    expect(screen.getByText("战法阈值配置")).toBeInTheDocument();
    expect(screen.getByText("S081 阈值 + funnel config（可改）")).toBeInTheDocument();
  });

  it("渲染历史统计特征标注", () => {
    renderPage();
    expect(screen.getByText("参考值，非执行指令；市场有风险")).toBeInTheDocument();
  });

  it("加载中——显示加载提示", () => {
    useQueryMock.mockReturnValue({ data: undefined, isLoading: true });
    strategyMocks.useStrategyBacktest.mockReturnValue({
      data: undefined,
      isLoading: false,
    });
    renderPage();
    expect(screen.getByText("加载中…")).toBeInTheDocument();
  });

  it("空数据——显示暂无战法数据", () => {
    useQueryMock.mockReturnValue({ data: [], isLoading: false });
    strategyMocks.useStrategyBacktest.mockReturnValue({
      data: [],
      isLoading: false,
    });
    renderPage();
    expect(screen.getByText("暂无战法数据")).toBeInTheDocument();
  });
});
