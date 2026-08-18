// S041 测试：TrendChart 折线——echarts.init 模式（useEffect+init+setOption+resize+dispose）。
// 仿 ScatterChart.test.tsx：mock echarts.init 返回带 setOption/dispose/resize 的实例；
// 断言 series.type=line、data 顺序、y 轴百分比格式、空数据占位、resize/dispose。
import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen } from "@testing-library/react";

// echarts mock：init 返回共享 setOption/dispose/resize 的实例，便于断言调用。
const echartsMocks = vi.hoisted(() => {
  const setOption = vi.fn();
  const dispose = vi.fn();
  const resize = vi.fn();
  const init = vi.fn(() => ({ setOption, dispose, resize }));
  return { init, setOption, dispose, resize };
});

vi.mock("echarts/core", () => ({ init: echartsMocks.init, use: vi.fn(), default: { init: echartsMocks.init, use: vi.fn() } }));

import {
  HitRateChart,
  AvgReturnChart,
  StrategyWinRateChart,
} from "../TrendChart";
import type { BacktestSnapshotRow } from "@/lib/api";

// lite 行：hit_rate=0.5 → 50%；avg_return=0.0123 → 1.23%（小数，×100 转y轴）
const liteRows: BacktestSnapshotRow[] = [
  {
    snapshot_date: "2026-08-07",
    engine: "lite",
    hit_rate: 0.5,
    avg_return: 0.0123,
    max_drawdown: -3,
    sharpe_ratio: 1.1,
    total_signals: 20,
    percentile_json: null,
    strategy_breakdown_json: null,
    created_at: "2026-08-07T17:00:00",
  },
  {
    snapshot_date: "2026-08-09",
    engine: "lite",
    hit_rate: 0.6,
    avg_return: 0.025,
    max_drawdown: -2,
    sharpe_ratio: 1.3,
    total_signals: 22,
    percentile_json: null,
    strategy_breakdown_json: null,
    created_at: "2026-08-09T17:00:00",
  },
];

// strategy 行：strategy_breakdown_json 含 2 战法（验证 2 线 + 按日聚正确）
const strategyRows: BacktestSnapshotRow[] = [
  {
    snapshot_date: "2026-08-07",
    engine: "strategy",
    hit_rate: null,
    avg_return: null,
    max_drawdown: null,
    sharpe_ratio: null,
    total_signals: null,
    percentile_json: null,
    strategy_breakdown_json: JSON.stringify([
      { strategy_code: "first_plate", strategy_name: "首板挖掘", win_rate: 0.4, avg_return: 1.0, sample_size: 10 },
      { strategy_code: "consecutive_relay", strategy_name: "连板接力", win_rate: 0.5, avg_return: 2.0, sample_size: 8 },
    ]),
    created_at: "2026-08-07T17:00:00",
  },
  {
    snapshot_date: "2026-08-09",
    engine: "strategy",
    hit_rate: null,
    avg_return: null,
    max_drawdown: null,
    sharpe_ratio: null,
    total_signals: null,
    percentile_json: null,
    strategy_breakdown_json: JSON.stringify([
      { strategy_code: "first_plate", strategy_name: "首板挖掘", win_rate: 0.6, avg_return: 1.5, sample_size: 10 },
      { strategy_code: "consecutive_relay", strategy_name: "连板接力", win_rate: 0.5, avg_return: 1.8, sample_size: 9 },
    ]),
    created_at: "2026-08-09T17:00:00",
  },
];

const allRows = [...liteRows, ...strategyRows];

describe("HitRateChart (C2)", () => {
  beforeEach(() => vi.clearAllMocks());

  it("success → 调 echarts.init + setOption（line + hit_rate×100 百分比，升序）", () => {
    render(<HitRateChart rows={allRows} />);
    expect(echartsMocks.init).toHaveBeenCalledTimes(1);
    expect(echartsMocks.setOption).toHaveBeenCalledTimes(1);
    const option = echartsMocks.setOption.mock.calls[0][0];
    expect(option.series[0].type).toBe("line");
    // hit_rate 0.5→50, 0.6→60，且按日期升序
    expect(option.series[0].data).toEqual([50, 60]);
    expect(option.xAxis.data).toEqual(["2026-08-07", "2026-08-09"]);
    expect(option.yAxis.name).toBe("命中率(%)");
  });

  it("空数据 → 不 init echarts，显示占位", () => {
    render(<HitRateChart rows={[]} />);
    expect(echartsMocks.init).not.toHaveBeenCalled();
    expect(screen.getByText("暂无命中率快照数据")).toBeInTheDocument();
  });

  it("卸载 → 调 instance.dispose", () => {
    const { unmount } = render(<HitRateChart rows={allRows} />);
    unmount();
    expect(echartsMocks.dispose).toHaveBeenCalledTimes(1);
  });
});

describe("AvgReturnChart (C2)", () => {
  beforeEach(() => vi.clearAllMocks());

  it("success → avg_return×100 转百分比，升序", () => {
    render(<AvgReturnChart rows={allRows} />);
    expect(echartsMocks.setOption).toHaveBeenCalledTimes(1);
    const option = echartsMocks.setOption.mock.calls[0][0];
    expect(option.series[0].type).toBe("line");
    // avg_return=0.0123, 0.025（小数）→ ×100 = 1.23, 2.5
    expect(option.series[0].data).toEqual([1.23, 2.5]);
    expect(option.yAxis.name).toBe("平均收益(%)");
  });

  it("空数据 → 占位", () => {
    render(<AvgReturnChart rows={[]} />);
    expect(echartsMocks.init).not.toHaveBeenCalled();
    expect(screen.getByText("暂无平均收益快照数据")).toBeInTheDocument();
  });
});

describe("StrategyWinRateChart (C3)", () => {
  beforeEach(() => vi.clearAllMocks());

  it("success → 2 战法 2 条线，每线 win_rate×100，按日聚对齐", () => {
    render(<StrategyWinRateChart rows={strategyRows} />);
    expect(echartsMocks.init).toHaveBeenCalledTimes(1);
    expect(echartsMocks.setOption).toHaveBeenCalledTimes(1);
    const option = echartsMocks.setOption.mock.calls[0][0];
    expect(option.xAxis.data).toEqual(["2026-08-07", "2026-08-09"]);
    // 2 个 series（2 战法）
    expect(option.series).toHaveLength(2);
    // 战法名走 series.name
    const names = option.series.map((s: { name: string }) => s.name);
    expect(names).toEqual(expect.arrayContaining(["首板挖掘", "连板接力"]));
    // first_plate：0.4→40, 0.6→60；consecutive_relay：0.5→50, 0.5→50
    const first = option.series.find((s: { name: string }) => s.name === "首板挖掘");
    const relay = option.series.find((s: { name: string }) => s.name === "连板接力");
    expect(first.data).toEqual([40, 60]);
    expect(relay.data).toEqual([50, 50]);
    // 颜色用 STRATEGY_PALETTE 锁色（first_plate 红、consecutive_relay 橙）
    expect(first.lineStyle.color).toBe("#ef4444");
    expect(relay.lineStyle.color).toBe("#f97316");
  });

  it("空数据 → 占位", () => {
    render(<StrategyWinRateChart rows={[]} />);
    expect(echartsMocks.init).not.toHaveBeenCalled();
    expect(screen.getByText("暂无战法胜率快照数据")).toBeInTheDocument();
  });

  it("strategy_breakdown_json 损坏 → 不崩，整图走占位或断线", () => {
    const badRows: BacktestSnapshotRow[] = [
      {
        ...strategyRows[0],
        strategy_breakdown_json: "{not valid json",
      },
    ];
    // 该日解析失败 → values 全 null → 但 dates 有 1 行 → 仍 init（走 series.data=[null] 断线）
    // 不抛错即通过
    expect(() => render(<StrategyWinRateChart rows={badRows} />)).not.toThrow();
  });

  it("卸载 → 调 instance.dispose", () => {
    const { unmount } = render(<StrategyWinRateChart rows={strategyRows} />);
    unmount();
    expect(echartsMocks.dispose).toHaveBeenCalledTimes(1);
  });
});
