import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, fireEvent } from "@testing-library/react";
import StockDeep from "../StockDeep";

// S039：StockDeep 消费 /stock/{code}/deep。mock useStockDeep 不经真实网络，
// mock useParams 固定 code（免 Router context）。

const qm = vi.hoisted(() => ({
  useStockDeep: vi.fn(),
}));

vi.mock("@/lib/query", async (importOriginal) => {
  const actual = await importOriginal<Record<string, unknown>>();
  return { ...actual, ...qm };
});

vi.mock("react-router-dom", async (importOriginal) => {
  const actual = await importOriginal<Record<string, unknown>>();
  return { ...actual, useParams: () => ({ code: "600519" }) };
});

const quote = {
  name: "贵州茅台",
  price: 1500,
  last_close: 1480,
  change_pct: 1.35,
  pe_ttm: 25,
  pb: 8,
  turnover_rate: 0.5,
  limit_up_price: 1628,
  limit_down_price: 1332,
};
const kline = [
  { date: "2026-08-08", open: 1480, high: 1510, low: 1470, close: 1500, volume: 100000, amount: 150000000 },
];
const fundFlow = [
  { date: "2026-08-08", main_net: 5000000, small_net: -1000000, mid_net: 500000, large_net: 2000000, super_net: 3000000 },
];
const financials = {
  period: "2026Q2",
  revenue: "800亿",
  revenue_yoy: "+15%",
  net_profit: "400亿",
  net_profit_yoy: "+20%",
  eps: "30",
  bvps: "200",
  roe: "30%",
  gross_margin: "90%",
  net_margin: "50%",
  op_cf_ps: "40",
};
const valuation = {
  name: "贵州茅台",
  code: "600519",
  price: 1500,
  mcap_yi: 1.8,
  pe_ttm: 25,
  pb: 8,
  eps_26e: null,
  eps_27e: null,
  pe_26e: null,
  cagr_pct: null,
  peg: null,
  digest_years: null,
  analyst_count: 5,
};
const percentile = {
  period: "2026",
  metrics: { pe_ttm: { current: 25, percentile: 50, min: 10, max: 40, p20: 15, p50: 25, p80: 35, n: 100 } },
};

beforeEach(() => {
  vi.clearAllMocks();
});

describe("S039 StockDeep", () => {
  it("全量数据渲染四块（行情/K线/财务/资金流）", () => {
    qm.useStockDeep.mockReturnValue({
      data: { quote, kline, fund_flow: fundFlow, financials, valuation, percentile },
      isLoading: false,
      error: null,
      refetch: vi.fn(),
    });
    render(<StockDeep />);
    expect(screen.getByText(/贵州茅台/)).toBeInTheDocument();
    expect(screen.getByText("行情摘要")).toBeInTheDocument();
    expect(screen.getByText("K 线图")).toBeInTheDocument();
    expect(screen.getByText("资金流向")).toBeInTheDocument();
    expect(screen.getByText("营业总收入")).toBeInTheDocument(); // EarningsSnapshot 渲染
  });

  it("字段 null 时各块显示暂无数据，不崩溃", () => {
    qm.useStockDeep.mockReturnValue({
      data: { quote: null, kline: null, fund_flow: null, financials: null, valuation: null, percentile: null },
      isLoading: false,
      error: null,
      refetch: vi.fn(),
    });
    render(<StockDeep />);
    expect(screen.getAllByText(/暂无/).length).toBeGreaterThanOrEqual(1);
    // K 线空数据：KLineChart 显示「暂无K线数据」
    expect(screen.getByText("暂无K线数据")).toBeInTheDocument();
  });

  it("loading 态显示 PageSkeleton（不渲染四块）", () => {
    qm.useStockDeep.mockReturnValue({ data: undefined, isLoading: true, error: null, refetch: vi.fn() });
    render(<StockDeep />);
    expect(screen.queryByText("行情摘要")).not.toBeInTheDocument();
    expect(screen.queryByText("K 线图")).not.toBeInTheDocument();
  });

  it("error 态显示 ErrorState + 重试按钮触发 refetch", () => {
    const refetch = vi.fn();
    qm.useStockDeep.mockReturnValue({
      data: undefined,
      isLoading: false,
      error: new Error("连接不到后端"),
      refetch,
    });
    render(<StockDeep />);
    expect(screen.getByText(/加载失败/)).toBeInTheDocument();
    fireEvent.click(screen.getByText("重试"));
    expect(refetch).toHaveBeenCalled();
  });
});
