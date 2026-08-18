// S024-B DRY 抽公共：echarts 生命周期 hook。
// 封装 init + setOption + resize 监听 + dispose，消除 5 处 chart 组件的重复样板。
// 用法：const ref = useRef<HTMLDivElement>(null);
//       useECharts(ref, () => option, [data], { skip: isEmpty, onReady: i => i.on("click", h) });
import { useEffect, useRef, type RefObject, type DependencyList } from "react";
import * as echarts from "echarts/core";
import type { EChartsOption } from "echarts";
import { LineChart, ScatterChart, RadarChart } from "echarts/charts";
import {
  TitleComponent,
  TooltipComponent,
  GridComponent,
  LegendComponent,
  RadarComponent,
  MarkAreaComponent,
  GraphicComponent,
} from "echarts/components";
import { CanvasRenderer } from "echarts/renderers";

// S082：按需注册——只打包项目实际用到的 chart/component/renderer。
// 阶段2：GraphChart/TreeChart 下沉到 GraphView.tsx 自行 use（仅 Topology 页用，随其 chunk）。
echarts.use([
  LineChart,
  ScatterChart,
  RadarChart,
  TitleComponent,
  TooltipComponent,
  GridComponent,
  LegendComponent,
  RadarComponent,
  MarkAreaComponent,
  GraphicComponent,
  CanvasRenderer,
]);

interface UseEChartsOptions {
  /** 为 true 时跳过 init（空数据 / loading 等守卫）。 */
  skip?: boolean;
  /** init + setOption 后回调：注册事件（click）或做额外 resize。 */
  onReady?: (instance: echarts.ECharts) => void;
  /** setOption notMerge 参数；默认 false。 */
  notMerge?: boolean;
  /** 是否挂 resize 监听；默认 true（GeneScoreChart 无需可传 false）。 */
  listenResize?: boolean;
}

/**
 * echarts 生命周期 hook：init → setOption → (onReady) → resize 监听 → dispose。
 *
 * @param ref        chart 容器 div 的 ref
 * @param buildOption 构建 echarts option 的函数（闭包捕获最新 props/state）
 * @param deps       触发重渲染的依赖列表（与 useEffect deps 语义一致）
 * @param options    可选配置：skip / onReady / notMerge / listenResize
 * @returns          echarts 实例 ref（组件可按需访问，通常不需直接用）
 */
export function useECharts(
  ref: RefObject<HTMLDivElement | null>,
  buildOption: () => EChartsOption,
  deps: DependencyList,
  options?: UseEChartsOptions,
): RefObject<echarts.ECharts | null> {
  const instanceRef = useRef<echarts.ECharts | null>(null);
  // 用 ref 持有 buildOption / options，避免其身份变化触发 effect 重跑
  // —— 只有 deps 变化才应触发 init→setOption 周期。
  const buildRef = useRef(buildOption);
  buildRef.current = buildOption;
  const optsRef = useRef(options);
  optsRef.current = options;

  useEffect(() => {
    const el = ref.current;
    if (!el || optsRef.current?.skip) return;

    const instance = echarts.init(el);
    instanceRef.current = instance;

    instance.setOption(buildRef.current(), optsRef.current?.notMerge ?? false);

    optsRef.current?.onReady?.(instance);

    const listenResize = optsRef.current?.listenResize ?? true;
    const onResize = () => instanceRef.current?.resize();
    if (listenResize) {
      window.addEventListener("resize", onResize);
    }

    return () => {
      if (listenResize) {
        window.removeEventListener("resize", onResize);
      }
      instanceRef.current?.dispose();
      instanceRef.current = null;
    };
    // deps 控制重渲染时机；buildOption/options 经 ref 不入依赖
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, deps);

  return instanceRef;
}
