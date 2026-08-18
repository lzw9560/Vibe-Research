// S025-D1 测试：ScatterChart 散点——echarts.init 模式（useEffect+init+resize+dispose）。
// 仿 TrendsChart.test.tsx：mock echarts.init 返回带 setOption/dispose/resize 的实例；
// 断言 series.type=scatter、data 为 [gene_score,next_day_return] 对、x/y 轴命名、空数据占位、resize/dispose。
import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, act } from "@testing-library/react";

// echarts mock：init 返回共享 setOption/dispose/resize 的实例，便于断言调用。
const echartsMocks = vi.hoisted(() => {
  const setOption = vi.fn();
  const dispose = vi.fn();
  const resize = vi.fn();
  const init = vi.fn(() => ({ setOption, dispose, resize }));
  return { init, setOption, dispose, resize };
});

vi.mock("echarts/core", () => ({ init: echartsMocks.init, use: vi.fn(), default: { init: echartsMocks.init, use: vi.fn() } }));

import { ScatterChart } from "../ScatterChart";

const points = [
  { gene_score: 60, next_day_return: 0.03, code: "000001" },
  { gene_score: 45, next_day_return: -0.02, code: "600519" },
  { gene_score: 72, next_day_return: 0.05, code: "300750" },
];

describe("ScatterChart (D1)", () => {
  beforeEach(() => vi.clearAllMocks());

  it("success → 调 echarts.init + setOption（散点 + gene_score/next_day_return 数据对）", () => {
    render(<ScatterChart points={points} />);
    expect(echartsMocks.init).toHaveBeenCalledTimes(1);
    expect(echartsMocks.setOption).toHaveBeenCalledTimes(1);
    const option = echartsMocks.setOption.mock.calls[0][0];
    expect(option.series[0].type).toBe("scatter");
    expect(option.series[0].data).toEqual([
      { value: [60, 0.03], code: "000001" },
      { value: [45, -0.02], code: "600519" },
      { value: [72, 0.05], code: "300750" },
    ]);
    expect(option.xAxis.name).toBe("基因得分");
    expect(option.yAxis.name).toBe("次日收益");
  });

  it("空数据 → 不 init echarts，显示占位", () => {
    render(<ScatterChart points={[]} />);
    expect(echartsMocks.init).not.toHaveBeenCalled();
    expect(screen.getByText("暂无散点数据")).toBeInTheDocument();
  });

  it("窗口 resize → 调 instance.resize", () => {
    render(<ScatterChart points={points} />);
    act(() => {
      window.dispatchEvent(new Event("resize"));
    });
    expect(echartsMocks.resize).toHaveBeenCalled();
  });

  it("卸载 → 调 instance.dispose", () => {
    const { unmount } = render(<ScatterChart points={points} />);
    unmount();
    expect(echartsMocks.dispose).toHaveBeenCalledTimes(1);
  });
});
