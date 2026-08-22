# 任务拆分 · S039 StockDeep 接线

> 级别：medium，直接 develop 提交。后端零改动。

## 阶段 A · React Query hook（R1）

| ID | 任务 | 依赖 | 改动文件 | 验收方式 | AC |
|---|---|---|---|---|---|
| A1 | `lib/query/stock.ts` 新建 `useStockDeep(code, options?)` | — | `frontend/src/lib/query/stock.ts` | tsc 过 | — |
| A2 | 确认 queryKey = `["stock", "deep", code]` | A1 | — | 检查 key 格式 | — |

## 阶段 B · 页面重建（R2-R6）

| ID | 任务 | 依赖 | 改动文件 | 验收方式 | AC |
|---|---|---|---|---|---|
| B1 | `StockDeep.tsx` 用 `useParams` 取 code + `useStockDeep` 取数据 | A1 | `frontend/src/pages/StockDeep.tsx` | tsc 过 | A1 |
| B2 | PageHeader：code + name + 实时价格/涨跌幅（红涨绿跌） | B1 | `frontend/src/pages/StockDeep.tsx` | 渲染行情摘要 | A1 |
| B3 | KLineChart 复用：传 `kline as Bar[]` | B1 | `frontend/src/pages/StockDeep.tsx` | K 线渲染 | A2 |
| B4 | EarningsSnapshot 复用：传 valuation + financials + percentile | B1 | `frontend/src/pages/StockDeep.tsx` | 财务速览渲染 | A3 |
| B5 | 资金流：新建简单 DataTable 展示 FundFlowRow | B1 | `frontend/src/pages/StockDeep.tsx` | 表格渲染 | A1 |
| B6 | 加载态：FullScreenSpinner | B1 | `frontend/src/pages/StockDeep.tsx` | loading 时 spinner | A5 |
| B7 | 错误态：ErrorState + 重试按钮 | B1 | `frontend/src/pages/StockDeep.tsx` | error 时显示 | A5 |
| B8 | 数据缺失态：各块 null -> "暂无数据"占位 | B2-B5 | `frontend/src/pages/StockDeep.tsx` | null 不崩溃 | A4 |
| B9 | Disclaimer 保留底部 | B1 | `frontend/src/pages/StockDeep.tsx` | 组件存在 | A9 |

## 阶段 C · 测试 + 验收

| ID | 任务 | 依赖 | 改动文件 | 验收方式 | AC |
|---|---|---|---|---|---|
| C1 | vitest：mock stockDeep 全量 -> 四块渲染 | B2-B5 | `frontend/.../__tests__/StockDeep.test.tsx` | vitest 过 | A7 |
| C2 | vitest：mock 部分 null -> 对应块"暂无数据" | B8 | 同上 | vitest 过 | A7 |
| C3 | vitest：loading -> spinner；error -> ErrorState | B6,B7 | 同上 | vitest 过 | A7 |
| C4 | `npx tsc --noEmit` 全过 | B1-B9 | — | 全绿 | A6 |
| C5 | `git diff backend/` 为空确认 | — | — | 无后端改动 | A8 |
| C6 | live 冒烟：`/stock/600519` 四块渲染 | C4 | — | 肉眼确认 | A1 |
