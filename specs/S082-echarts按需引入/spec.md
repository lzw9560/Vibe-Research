# S082 echarts 按需引入优化

> 状态：阶段2 完成（2026-08-19）—— tsc 过、6 echarts 测试 44/44 绿、useECharts chunk 558.93KB/gzip 190.45KB（graph/tree 下沉至 Topology chunk 72.87KB/gzip 25.60KB，首页不再背），未达自定 <500/180KB 目标，渲染回归待用户确认。commit 6eafb7f。
> 分级：medium（跨源文件 + 测试 mock + 构建产物 + 渲染回归）

## 问题/目标

前端生产 build 的 `useECharts` chunk 1.13MB（gzip 379KB），是全包最大头。根因：`useECharts.ts` 与 `STITimelineChart.tsx` 全量 `import * as echarts from "echarts"`（echarts 6 全包）。echarts 6 支持 `echarts/core` + `echarts.use()` 按需注册，只打包项目实际用到的 chart/component/renderer。

## 按需注册清单（基于 src 实际使用扫描）

扫描依据：
- option 顶层 key：title(30) / tooltip(10) / grid(10) / legend(3) / markArea(1) / graphic(1) + radar 坐标系(2)
- series type：line / scatter / radar / graph / **tree**（GraphView buildTreeOption）
- 运行时 API：`echarts.init`（默认 canvas renderer）、`echarts.graphic.LinearGradient`

注册清单：
- charts: `LineChart`, `ScatterChart`, `RadarChart`, `GraphChart`, `TreeChart`
- components: `TitleComponent`, `TooltipComponent`, `GridComponent`, `LegendComponent`, `RadarComponent`, `MarkAreaComponent`, `GraphicComponent`
- renderers: `CanvasRenderer`

## 需求

1. `useECharts.ts`：`import * as echarts from "echarts"` → `from "echarts/core"` + 模块顶层 `echarts.use([...按需...])` 注册一次（hook 模块加载时执行）。阶段2 起不含 GraphChart/TreeChart（下沉到需求 6）
2. `STITimelineChart.tsx`：`import * as echarts from "echarts"` → `from "echarts/core"`（仅为 `echarts.graphic.LinearGradient`；不重复 `use`，复用 useECharts 已注册）
3. `GraphView.tsx`：`import type * as echarts from "echarts"` → runtime `import * as echarts from "echarts/core"` + `import type { EChartsOption } from "echarts"` + 顶层 `echarts.use([GraphChart, TreeChart])`（见需求 6）
4. 6 个测试文件 `vi.mock("echarts", ...)` → `vi.mock("echarts/core", () => ({ init, use: vi.fn() }))`：拦截路径随 import 改变，且补 `use` 避免 `echarts.use(...)` 在 mock 下 TypeError
5. 不动任何图表业务 option 逻辑、不动 dead code（如 STITimeline 未用的 visualMap 局部变量，不在本任务范围）
6. 阶段2（graph/tree 下沉）：`GraphView.tsx` 顶层 `echarts.use([GraphChart, TreeChart])`，从 `useECharts` 的 use 列表移除二者。graph 力导向 + tree 树布局算法随 GraphView chunk（仅 Topology 页引用），首页/其他页不再加载。`EChartsOption` 返回类型 `echarts.EChartsOption` → `EChartsOption`（core 不导出该类型，走 `import type` from "echarts" 擦除不打包）。

## 受影响文件

- 后端：无（纯前端）
- `frontend/src/hooks/useECharts.ts`（import + 顶层 use 注册）
- `frontend/src/components/sti/STITimelineChart.tsx`（import 路径）
- `frontend/src/components/topology/GraphView.tsx`（type import 路径）
- 测试 mock（6 处，IntradayMonitor mock 的是 `@/hooks/useECharts` 整个 hook 不动）：
  - `src/components/winrate/__tests__/TrendsChart.test.tsx`
  - `src/components/winrate/__tests__/WinRateView.test.tsx`
  - `src/components/topology/__tests__/GraphView.test.tsx`
  - `src/components/charts/__tests__/TrendChart.test.tsx`
  - `src/components/charts/__tests__/ScatterChart.test.tsx`
  - `src/pages/__tests__/Backtest.test.tsx`

## 验收标准

- [x] `tsc -b` 0 类型错（按需 named exports 全部存在；`EChartsOption` 走 `import type` from "echarts"，type-only 擦除不打包）
- [x] `vitest run`：echarts 相关 6 测试文件 44/44 绿；13 fail 全在 `Workflow.test.tsx`（`@/lib/query` mock 缺 `useFirstBoardCandidates` 导出），系别 agent 加首板流卡片入口未补 mock 的 pre-existing 债，与 echarts 无关、无新回归
- [x] `npm run build`（阶段2）：useECharts chunk 558.93KB / gzip 190.45KB（阶段1 620.08/210.26 → 阶段2 移走 graph/tree）；Topology chunk 72.87KB / gzip 25.60KB（graph 力导向 + tree 树布局下沉至此，访问 Topology 才加载）。首页 useECharts 1128→558KB（-50%）。未达自定 <500/<180：剩 line/scatter/radar + components + zrender canvas renderer，首页都要用，砍不动
- [ ] **渲染回归（待用户确认）**：vitest mock 了 `echarts.init`，测不了真实图表渲染。需在 :5899 dev 看 line（TrendChart/STITimeline，重点 STITimeline 渐变面积 `graphic.LinearGradient`）、scatter（ScatterChart）、radar、graph + tree（GraphView，重点——注册刚从 useECharts 移到 GraphView）各能画出

## 合规自查（弱合规·工程底线）

- 不臆造数据：改 import 不涉数据输出 ✓
- 私有数据隔离：不动 `.vibe-research/` ✓
- 防封：不碰 `em_get` / 东财端点 ✓

纯前端构建优化，工程底线无风险。
