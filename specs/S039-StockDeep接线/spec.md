# Spec: S039 — StockDeep 个股深度页面接线（消费已有端点，第一批核心四块）

> 状态：已实现（2026-08-09）
> 作者：Codex  日期：2026-08-08
> 关联：`../S025-补前端入口/spec.md`（S027 范围中 StockDeep 项）、`backend/routers/stock_data.py:213`（`/api/stock/{code}/deep` 端点已实现）、`frontend/src/lib/api/types.ts:451`（StockDeep 接口类型已定义）、`frontend/src/lib/api.ts:140`（stockDeep API 封装已就绪）
>
> 级别：**medium**（纯前端页面重建，消费已有后端端点，后端零改动；>50 行页面重写）

## 1. 问题 / 目标

`StockDeep.tsx`（60 行桩）：用 `setTimeout` + 假数据 `{code, name: "示例股票"}` 渲染一个极简页面（一个 GlassCard 展示 code/name + Disclaimer）。但后端 `/api/stock/{code}/deep` 端点已完整实现（聚合 12 个数据源），前端 API 封装 `stockDeep(code)` 和类型 `StockDeep` 接口也已就绪——只差页面接线。

**目标**：重建 StockDeep 页面，消费已有端点，渲染核心四块（quote / kline / fund_flow / financials）。第二批 8 块视使用情况增量补。

## 2. 背景

- 后端端点 `/api/stock/{code}/deep`（`routers/stock_data.py:213`）：`async def stock_deep(code)` → 12 个 `_safe_call` 并行聚合（任一失败返 null，不影响整体）。已注册在 `app.py`。
- 前端 API 封装：`api.ts:140` — `stockDeep: (code: string) => get<StockDeep>('/stock/${code}/deep')`
- 前端类型 `StockDeep`（`types.ts:451`）：12 字段全定义（quote / kline / valuation / percentile / fund_flow / dragon_tiger / limitup / financials / blocks / hot_concepts / announcements / reports）。
- 可复用组件：
  - `KLineChart`（`components/charts/KLineChart.tsx`）— `bars: Bar[]` prop，`Bar` 字段与 `KlineBar` 类型完全对齐（date/open/high/low/close/volume/amount）。
  - `EarningsSnapshot`（`components/ui/EarningsSnapshot.tsx`）— `val/fin/pctl` props，消费 Valuation + Financials + ValPercentile。
- 路由已注册：`router.tsx:43` — `{ path: "/stock/:code", element: lazyEl(...) }`。
- 无 React Query hook：`lib/query/` 下无 `useStockDeep`——需新建。
- 入口：candidates 列表、portfolio 持仓可跳转（`/stock/:code`）。

## 3. 需求清单

### 第一批（核心四块）

- [ ] R1 新建 `frontend/src/lib/query/stock.ts`：`useStockDeep(code, options?)` hook，调 `api.stockDeep(code)`，React Query 管理 loading/error/cache。
- [ ] R2 重建 `StockDeep.tsx`：用 `useParams` 取 code → `useStockDeep(code)` 取数据 → 渲染四块：
  - **行情摘要**：`Quote` 字段（name/price/change_pct/pe_ttm/pb/turnover_rate/limit_up_price/limit_down_price），红涨绿跌 A 股口径。
  - **K 线图**：复用 `KLineChart`，传 `kline: KlineBar[]`。
  - **资金流**：`FundFlowRow[]` 表格或柱状图展示主力净流入趋势。
  - **财务速览**：复用 `EarningsSnapshot`，传 valuation + financials + percentile。
- [ ] R3 加载态：全屏 spinner（复用 `State.tsx` 的 FullScreenSpinner）。
- [ ] R4 错误态：复用 `State.tsx` 的 ErrorState，显示重试按钮。
- [ ] R5 数据缺失态：各块 `null` 时显示"暂无数据"占位，不崩溃（后端 `_safe_call` 返 null 是正常降级）。
- [ ] R6 保留 `Disclaimer` 组件底部免责声明。

### 不做（第二批）

- valuation / percentile 独立块（已由 EarningsSnapshot 内消费）
- dragon_tiger / limitup / blocks / hot_concepts / announcements / reports——增量补

## 4. 受影响文件

| 文件 | 改动 |
|---|---|
| `frontend/src/pages/StockDeep.tsx` | 重建：桩 → 真实数据渲染 |
| `frontend/src/lib/query/stock.ts`（新） | R1 useStockDeep hook |

## 5. 设计方案

### D1 页面布局

个股深度页是工具型页面——按 S025 B1 的"quiet, utilitarian"设计导向：不用 hero，不用 marketing 布局。结构：

1. PageHeader（code + name + 实时价格/涨跌幅）
2. K 线图（全宽，高度 420px，复用 KLineChart）
3. 两列网格：行情摘要（左）+ 财务速览（右，复用 EarningsSnapshot）
4. 资金流（全宽表格或柱状图）
5. Disclaimer

### D2 hook 隔离

新建 `lib/query/stock.ts` 放 `useStockDeep`——不和 `lib/query/limitup.ts` 混放（语义分离）。React Query key = `["stock", "deep", code]`。

### D3 后端零改动

端点已实现，API 封装已有，类型已定义——纯前端接线。`git diff backend/` 为空。

### D4 组件复用优先

`KLineChart` 直接传 `kline`（字段对齐），`EarningsSnapshot` 传 valuation/financials/percentile。不造新组件，除非现有组件无法满足（资金流表格可能需新建简单 DataTable 展示）。

## 6. 验收标准

- [ ] A1 `/stock/600519` 页面渲染：行情摘要 + K 线图 + 财务速览 + 资金流四块
- [ ] A2 K 线图复用 KLineChart，红涨绿跌 A 股口径
- [ ] A3 财务速览复用 EarningsSnapshot
- [ ] A4 任一数据块 null 时显示"暂无数据"，不崩溃
- [ ] A5 加载态全屏 spinner，错误态显示重试按钮
- [ ] A6 `npx tsc --noEmit` 通过
- [ ] A7 vitest 新测试通过（页面渲染四块 + null 降级 + loading/error 态）
- [ ] A8 后端零改动（`git diff backend/` 为空）
- [ ] A9 Disclaimer 保留

## 7. 合规与工程底线自查

- [ ] 只消费现有后端端点，无新数据源、无臆造
- [ ] 个股行情/K线/财务/资金流均客观数据呈现，无方向性研判
- [ ] `EarningsSnapshot` 已合规设计（只客观机械分档陈述，不推荐/不预测/不评级）
- [ ] 不涉及用户私有数据
- [ ] 不涉及东财端点新增（后端端点已存在）

## 8. 测试计划

- **vitest**：
  - mock `stockDeep` 返全量数据 → 四块渲染
  - mock 返部分 null → 对应块显示"暂无数据"
  - loading 态 → spinner
  - error 态 → ErrorState + 重试
- **离线**：`cd frontend && npx tsc --noEmit && npx vitest run`
- **live 冒烟**（手动）：`/stock/600519` 看四块渲染

## 9. 风险与回滚

- 🟢 低风险：纯前端消费已有端点，后端零改动。
- 🟡 `KLineChart` 的 `Bar` 接口与 `KlineBar` 字段需确认完全对齐——已核实（date/open/high/low/close/volume/amount 全对齐），直接传 `kline as Bar[]`。
- 🟡 资金流展示无现成组件——可能需新建简单表格。工作量可控（FundFlowRow 5 字段）。
- 🟢 回滚：`git revert`（medium 直接 develop）。
