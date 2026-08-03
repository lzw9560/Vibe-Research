// S024-A1 测试：GraphView 共用图引擎——echarts graph（力导向）/tree 渲染 + 节点点击回调。
// 仿 ScatterChart.test.tsx：mock echarts.init 返回 setOption/dispose/resize/on 实例；
// 断言 graph/tree 两种布局的 series 类型、nodes/links 映射、节点点击回调触发、resize/dispose、空数据占位。
import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, act } from "@testing-library/react";

// echarts mock：init 返回共享 setOption/dispose/resize/on 的实例，便于断言。
const echartsMocks = vi.hoisted(() => {
  const setOption = vi.fn();
  const dispose = vi.fn();
  const resize = vi.fn();
  const on = vi.fn();
  const init = vi.fn(() => ({ setOption, dispose, resize, on }));
  return { init, setOption, dispose, resize, on };
});

vi.mock("echarts", () => ({
  init: echartsMocks.init,
  default: { init: echartsMocks.init },
}));

import { GraphView } from "../GraphView";
import type { GraphData, GraphNode } from "../types";

const mockData: GraphData = {
  nodes: [
    { id: "n1", name: "标的A", category: "涨停", code: "000001", value: 10 },
    { id: "n2", name: "标的B", category: "涨停", code: "600519", value: 8 },
    { id: "n3", name: "标的C", category: "连板", code: "300750", value: 5 },
  ],
  edges: [
    { source: "n1", target: "n2", type: "sector", weight: 1 },
    { source: "n2", target: "n3", type: "fund_flow", weight: 2 },
  ],
};

describe("GraphView (S024-A)", () => {
  beforeEach(() => vi.clearAllMocks());

  it("graph 模式 → 调 echarts.init + setOption（series.type=graph, layout=force）", () => {
    render(<GraphView data={mockData} />);
    expect(echartsMocks.init).toHaveBeenCalledTimes(1);
    expect(echartsMocks.setOption).toHaveBeenCalledTimes(1);
    const option = echartsMocks.setOption.mock.calls[0][0];
    expect(option.series[0].type).toBe("graph");
    expect(option.series[0].layout).toBe("force");
  });

  it("graph 模式 → nodes/links 正确映射（含 id/name/code）", () => {
    render(<GraphView data={mockData} />);
    const option = echartsMocks.setOption.mock.calls[0][0];
    const series = option.series[0];
    expect(series.data).toHaveLength(3);
    expect(series.data[0]).toMatchObject({ id: "n1", name: "标的A", code: "000001" });
    expect(series.links).toHaveLength(2);
    expect(series.links[0]).toMatchObject({ source: "n1", target: "n2" });
    expect(series.links[1]).toMatchObject({ source: "n2", target: "n3" });
  });

  it("graph 模式 → 按边类型着色（sector/fund_flow 不同色）", () => {
    render(<GraphView data={mockData} />);
    const option = echartsMocks.setOption.mock.calls[0][0];
    const links = option.series[0].links;
    // 边按 type 着色，两类边颜色不同
    expect(links[0].lineStyle.color).not.toBe(links[1].lineStyle.color);
  });

  it("graph 模式 → categories 来自节点 category（去重）", () => {
    render(<GraphView data={mockData} />);
    const option = echartsMocks.setOption.mock.calls[0][0];
    const catNames = option.series[0].categories.map((c: { name: string }) => c.name);
    expect(catNames).toEqual(["涨停", "连板"]);
  });

  it("tree 模式 → series.type=tree，根节点为无入边的节点", () => {
    render(<GraphView data={mockData} layout="tree" />);
    expect(echartsMocks.setOption).toHaveBeenCalledTimes(1);
    const option = echartsMocks.setOption.mock.calls[0][0];
    expect(option.series[0].type).toBe("tree");
    // n1 无入边 → 根；其 children 含 n2
    const root = option.series[0].data[0];
    expect(root.name).toBe("标的A");
    expect(root.children[0].name).toBe("标的B");
  });

  it("节点点击 → 触发 onNodeClick 回调（含完整 GraphNode）", () => {
    const onNodeClick = vi.fn();
    render(<GraphView data={mockData} onNodeClick={onNodeClick} />);
    // echarts on("click", handler) 已注册
    expect(echartsMocks.on).toHaveBeenCalledWith("click", expect.any(Function));
    const handler = echartsMocks.on.mock.calls[0][1];
    act(() => {
      handler({ dataType: "node", data: { id: "n1", name: "标的A" } });
    });
    const expected: GraphNode = {
      id: "n1",
      name: "标的A",
      category: "涨停",
      code: "000001",
      value: 10,
    };
    expect(onNodeClick).toHaveBeenCalledWith(expected);
  });

  it("点击非节点（如边/画布）→ 不触发 onNodeClick", () => {
    const onNodeClick = vi.fn();
    render(<GraphView data={mockData} onNodeClick={onNodeClick} />);
    const handler = echartsMocks.on.mock.calls[0][1];
    act(() => {
      handler({ dataType: "edge", data: {} });
    });
    expect(onNodeClick).not.toHaveBeenCalled();
  });

  it("空数据 → 不 init，显示占位", () => {
    render(<GraphView data={{ nodes: [], edges: [] }} />);
    expect(echartsMocks.init).not.toHaveBeenCalled();
    expect(screen.getByText("暂无拓扑数据")).toBeInTheDocument();
  });

  it("窗口 resize → 调 instance.resize", () => {
    render(<GraphView data={mockData} />);
    act(() => {
      window.dispatchEvent(new Event("resize"));
    });
    expect(echartsMocks.resize).toHaveBeenCalled();
  });

  it("卸载 → 调 instance.dispose", () => {
    const { unmount } = render(<GraphView data={mockData} />);
    unmount();
    expect(echartsMocks.dispose).toHaveBeenCalledTimes(1);
  });
});
