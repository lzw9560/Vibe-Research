// S218 C4: ValidatedEdgeCard 测试——诚实性 gate。
import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen } from "@testing-library/react";

const hooks = vi.hoisted(() => ({
  useSignalsStatus: vi.fn(),
}));

vi.mock("@/lib/query/signals", () => ({ useSignalsStatus: hooks.useSignalsStatus }));

// mock echarts to avoid canvas/render issues
const echartsMocks = vi.hoisted(() => {
  const setOption = vi.fn();
  const dispose = vi.fn();
  const resize = vi.fn();
  const init = vi.fn(() => ({ setOption, dispose, resize }));
  return { init, setOption, dispose, resize };
});

vi.mock("echarts/core", () => ({
  init: echartsMocks.init,
  use: vi.fn(),
  default: { init: echartsMocks.init, use: vi.fn() },
}));

import { ValidatedEdgeCard } from "../ValidatedEdgeCard";

function mockBearStale() {
  hooks.useSignalsStatus.mockReturnValue({
    data: {
      regime: { current: "bear", freshness: { last_cache_date: "2026-09-10", stale: true, days_since: 3 } },
      arms: {},
    },
    isLoading: false,
    isError: false,
    error: null,
  });
}

function mockBullFresh() {
  hooks.useSignalsStatus.mockReturnValue({
    data: {
      regime: { current: "bull", freshness: { last_cache_date: "2026-09-18", stale: false, days_since: 0 } },
      arms: {},
    },
    isLoading: false,
    isError: false,
    error: null,
  });
}

function mockLoading() {
  hooks.useSignalsStatus.mockReturnValue({ data: undefined, isLoading: true, isError: false, error: null });
}

// mockLoading used in loading test below
describe("ValidatedEdgeCard loading state", () => {
  it("shows loading spinner", () => {
    mockLoading();
    render(<ValidatedEdgeCard />);
    expect(document.body.innerHTML).toContain("加载信号状态");
  });
});

describe("ValidatedEdgeCard (S218 C4)", () => {
  beforeEach(() => vi.clearAllMocks());

  it("test_dashboard_card_not_safe_to_act: label in {provisional, within-regime only, 衰减中}; '可放心照做' absent", () => {
    mockBearStale();
    render(<ValidatedEdgeCard />);
    const html = document.body.innerHTML;
    const safeLabels = ["provisional", "within-regime only", "衰减中"];
    const hasLabel = safeLabels.some((l) => html.includes(l));
    expect(hasLabel).toBe(true);
    expect(html).not.toContain("可放心照做");
  });

  it("test_paper_only_pnl_label: '模拟盘名义额' + '非真钱' + '接券商前所有战绩 paper' present", () => {
    mockBearStale();
    render(<ValidatedEdgeCard />);
    expect(screen.getByText(/模拟盘名义额/)).toBeInTheDocument();
    expect(screen.getByText(/非真钱/)).toBeInTheDocument();
    expect(screen.getByText(/接券商前所有战绩 paper/)).toBeInTheDocument();
  });

  it("test_effective_cap_reflects_regime: bear stale shows ×0.5; bull fresh shows ×0.75", () => {
    mockBearStale();
    const { rerender } = render(<ValidatedEdgeCard />);
    expect(document.body.innerHTML).toContain("×0.5");

    mockBullFresh();
    rerender(<ValidatedEdgeCard />);
    expect(document.body.innerHTML).toContain("×0.75");
  });

  it("test_decay_trajectory_displayed: train 1.57% + test 1.04% + 衰减 34% rendered", () => {
    mockBullFresh();
    render(<ValidatedEdgeCard />);
    expect(screen.getByText(/1\.57%/)).toBeInTheDocument();
    expect(screen.getByText(/1\.04%/)).toBeInTheDocument();
    expect(screen.getByText(/34%/)).toBeInTheDocument();
  });

  it("test_regime_stale_indicator: stale=true shows red '实际 ×0.5'", () => {
    mockBearStale();
    render(<ValidatedEdgeCard />);
    expect(screen.getByText(/实际 ×0\.5/)).toBeInTheDocument();
  });
});
