# 技术方案 · S039 StockDeep 个股深度页面接线

> 对应：`spec.md`（需求/验收）、`tasks.md`（原子任务）
> 级别：medium，直接 develop 提交。后端零改动。

## 1. 文件结构与职责

### 新增
| 文件 | 职责 |
|---|---|
| `frontend/src/lib/query/stock.ts` | `useStockDeep(code, options?)` React Query hook |

### 改动
| 文件 | 改动 |
|---|---|
| `frontend/src/pages/StockDeep.tsx` | 桩重建为真实数据渲染 |

### 不改
后端 `routers/stock_data.py`、`api.ts`、`types.ts` 均已就绪，零改动。

## 2. hook 设计

```typescript
// lib/query/stock.ts
import { useQuery } from "@tanstack/react-query";
import { api } from "@/lib/api";
import type { StockDeep } from "@/lib/api/types";
import type { Opts } from "./types";

export function useStockDeep(code: string, options?: Opts<StockDeep>) {
  return useQuery({
    queryKey: ["stock", "deep", code] as const,
    queryFn: () => api.stockDeep(code),
    ...options,
  });
}
```

## 3. 页面布局

```
PageHeader (code + name + 实时价格/涨跌幅)
KLineChart (全宽 420px，传 kline as Bar[])
两列网格:
  左: 行情摘要 (Quote 字段表格)
  右: EarningsSnapshot (valuation + financials + percentile)
资金流 (全宽 FundFlowRow 表格)
Disclaimer
```

## 4. 组件复用

- `KLineChart`：`kline as Bar[]`（字段全对齐 date/open/high/low/close/volume/amount）
- `EarningsSnapshot`：传 `val/fin/pctl` props
- `FullScreenSpinner` / `ErrorState`：从 `State.tsx` 复用
- 资金流：新建简单 DataTable（FundFlowRow 5 字段）

## 5. 数据缺失处理

后端 `_safe_call` 返 null 是正常降级。每块 `null` -> 显示"暂无数据"占位，不崩溃。
