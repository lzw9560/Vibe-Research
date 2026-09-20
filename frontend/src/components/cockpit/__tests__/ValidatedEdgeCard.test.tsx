// S218 C4: ValidatedEdgeCard 测试——诚实性 gate + 后端单源 cap/verified_numbers。
// 方向2：cap/verified_numbers 改读 useSignalsDaily（cap.effective + verified_numbers.chrono_*），
// 不再硬编码 effectiveCap() + DECAY_* 常量。与 TodaySignalsPanel 同源。
import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen } from "@testing-library/react";

const hooks = vi.hoisted(() => ({
  useSignalsDaily: vi.fn(),
}));

vi.mock("@/lib/query/signals", () => ({
  useSignalsDaily: hooks.useSignalsDaily,
}));

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

/** 构造 SignalsDailyResponse-shaped data，override 局部字段（regime/cap/verified）。 */
function makeData(overrides: Record<string, unknown> = {}) {
  return {
    date: "2026-09-20",
    arm: "consecutive_relay",
    regime: {
      current: "bull",
      edge_status: "oos_supporting",
      freshness: {
        last_cache_date: "2026-09-20",
        stale: false,
        days_since: 0,
        n_dates: 561,
      },
    },
    cap: {
      effective: 1.0,
      base: 1.0,
      decay: 0.75,
      regime_factor: 1.0,
      zuoT_factor: 1.0,
      note: "bull x1.0",
    },
    hardstop: { active: false, reason: null },
    filters: { total_scanned: 100, tradable: 1, exploratory: 0, avoid: 0 },
    signals: [],
    // 真实字段名 chrono_*（非任务草稿的 decay_pct/p/wr），单位与后端一致：
    // chrono_wr 为百分点（52.7）非小数（0.527）；chrono_train/test 为百分点收益。
    verified_numbers: {
      chrono_train: 1.77,
      chrono_test: 1.25,
      chrono_decay_pct: 30,
      chrono_p: 0.000019,
      chrono_wr: 53,
      deep_dive_lbc2: 0.9,
      deep_dive_lbc3: 2.05,
    },
    disclaimers: [],
    ...overrides,
  };
}

function mockDaily(overrides: Record<string, unknown> = {}) {
  hooks.useSignalsDaily.mockReturnValue({
    data: makeData(overrides),
    isLoading: false,
    isError: false,
    error: null,
  });
}

function mockBearStale() {
  mockDaily({
    regime: {
      current: "bear",
      edge_status: "within-regime only",
      freshness: {
        last_cache_date: "2026-09-10",
        stale: true,
        days_since: 3,
        n_dates: 561,
      },
    },
    cap: {
      effective: 0.5,
      base: 1.0,
      decay: 0.75,
      regime_factor: 0.5,
      zuoT_factor: 1.0,
      note: "bear x0.5",
    },
  });
}

function mockBullFresh(cap = 1.0) {
  mockDaily({
    cap: {
      effective: cap,
      base: 1.0,
      decay: 0.75,
      regime_factor: 1.0,
      zuoT_factor: 1.0,
      note: `bull x${cap}`,
    },
  });
}

function mockLoading() {
  hooks.useSignalsDaily.mockReturnValue({
    data: undefined,
    isLoading: true,
    isError: false,
    error: null,
  });
}

describe("ValidatedEdgeCard loading state", () => {
  it("shows loading spinner", () => {
    mockLoading();
    render(<ValidatedEdgeCard />);
    expect(document.body.innerHTML).toContain("加载信号状态");
  });
});

describe("ValidatedEdgeCard (S218 C4, 方向2 backend cap/verified)", () => {
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

  it("test_effective_cap_reads_backend: cap.effective=1.0 → shows ×1.0, not hardcoded ×0.75", () => {
    mockBullFresh(1.0);
    render(<ValidatedEdgeCard />);
    expect(document.body.innerHTML).toContain("×1.0");
    expect(document.body.innerHTML).not.toContain("×0.75");
  });

  it("test_effective_cap_conservative: cap.effective=0.5 → shows ×0.5 (single source)", () => {
    mockBullFresh(0.5);
    render(<ValidatedEdgeCard />);
    expect(document.body.innerHTML).toContain("×0.5");
  });

  it("test_decay_reads_verified_numbers: train 1.77% + test 1.25% + 衰减 30% + WR 53% from backend, old hardcoded 1.57/1.04/52.7 absent", () => {
    mockBullFresh();
    render(<ValidatedEdgeCard />);
    expect(screen.getByText(/1\.77%/)).toBeInTheDocument();
    expect(screen.getByText(/1\.25%/)).toBeInTheDocument();
    expect(screen.getByText(/30%/)).toBeInTheDocument();
    expect(screen.getByText(/53%/)).toBeInTheDocument();
    // 旧硬编码常量已删，不应出现
    expect(document.body.innerHTML).not.toContain("1.57");
    expect(document.body.innerHTML).not.toContain("1.04");
    expect(document.body.innerHTML).not.toContain("52.7");
  });

  it("test_regime_stale_indicator: stale=true + cap.effective=0.5 → shows red '实际 ×0.5'", () => {
    mockBearStale();
    render(<ValidatedEdgeCard />);
    expect(screen.getByText(/实际 ×0\.5/)).toBeInTheDocument();
  });
});
