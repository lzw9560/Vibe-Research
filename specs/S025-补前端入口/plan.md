# 技术方案 · S025 补前端入口（打板闭环：winrate + auction/monitor）

> 对应：`spec.md`（需求/验收）、`tasks.md`（原子任务）
> 原则：TDD、DRY、YAGNI、勤 commit。纯前端消费现有后端端点，后端零改动。
> 覆盖分析：workflow `wf_71089e37-5a0`；范围 B1（winrate 6 端点）+ B3（auction/monitor 2 端点）。B2→S026。

## 1. 文件结构与职责

### 新增 `frontend/src/components/winrate/`
| 文件 | 职责 |
|---|---|
| `WinRateView.tsx` | 胜率视图主体：FilterBar 窗口滑块 + 四区编排（概览/趋势/拆分/调整）+ 挂 RecordsForm |
| `StatsMetrics.tsx` | 概览区：MetricCard 矩阵（总交易/胜数/胜率/平均收益/最大回撤/夏普），消费 `winrate/stats` |
| `TrendsChart.tsx` | 趋势区：echarts 折线（胜率/收益随时间），消费 `winrate/trends` |
| `BreakdownTable.tsx` | 拆分区：DataTable 按 sector + 按 strategy 下钻，消费 `winrate/sector`+`winrate/strategy` |
| `AdjustmentsCard.tsx` | 调整建议区：GlassCard 呈现 `winrate/adjustments` |
| `RecordsForm.tsx` | 「记入胜率」表单 → POST `winrate/records`，乐观更新 + 失败回滚 |

### 新增 `frontend/src/components/auction/`
| 文件 | 职责 |
|---|---|
| `Monitor925.tsx` | 9:25 盘中监控：9:15–9:30 窗口内 15s refetch `auction/monitor`+`auction/watchlist`；窗口外静态快照 + 倒计时 |

### 改动
| 文件 | 改动 |
|---|---|
| `frontend/src/lib/api.ts` | 加 `winRateRecords` POST 封装（唯一缺失；winRateStats/Adjustments/Trends/Sector/Strategy + auctionMonitor/Watchlist 已在 :148-160） |
| `frontend/src/lib/api/types.ts` | 加 `WinRateRecordInput` 类型 |
| `frontend/src/lib/query.ts` | 加 `useWinRateStats/Adjustments/Trends/Sector/Strategy`（react-query，仿 `useAuctionTop`）+ `useWinRateRecords`（useMutation，成功 invalidate stats/trends）+ `useAuctionMonitor`（refetchInterval 按窗口） |
| `frontend/src/pages/Backtest.tsx` | 加 `TabBar`（回测结果 / 胜率趋势），key 对齐 nav sub-item；现有回测内容作 tab 1，`<WinRateView/>` 作 tab 2 |
| `frontend/src/pages/limitup/AuctionScreener.tsx` | 加 `TabBar`（竞价预案 TOP N / 盘中监控 9:25）；现有内容作 tab 1，`<Monitor925/>` 作 tab 2 |
| `frontend/src/components/charts/ScatterChart.tsx` | 新建：echarts 散点（gene_score vs next_day_return），复用 KLineChart 的 echarts 初始化模式；Backtest 散点升级用它 |
| 后端 | **零改动** |

> nav sub-item「胜率趋势」(key=winrate) 已在 `navigation.ts:140`，页内 TabBar 读 active key 切换，不改 router/navigation。

## 2. 接口设计

### 2.1 lib/api.ts — winRateRecords POST 封装
```ts
// types.ts
export interface WinRateRecordInput {
  stock_code: string;       // 必填
  stock_name?: string;
  strategy_used?: string;
  entry_date: string;       // 必填
  entry_price?: number;
  exit_date: string;        // 必填
  exit_price?: number;
  return_pct?: number;
  is_win?: boolean;
  gene_score?: number;
  sti_label?: string;
  sector?: string;
}
export interface WinRateRecordsResponse {
  data: {
    added: string[];            // 录入成功的 stock_code
    added_count: number;
    errors: { index: number; error: string }[];
    error_count: number;
  };
}

// api.ts（紧邻 winRateStrategy :157 之后）
winRateRecords: (records: WinRateRecordInput[]) =>
  post<WinRateRecordsResponse>("/winrate/records", records),
```
> 后端 `POST /api/winrate/records`（`win_rate.py:92`）接 `List[Dict]`，返 `{data:{added,added_count,errors,error_count}}`。字段映射 `WinRateRecord`（`win_rate_tracker.py:18`）。

### 2.2 lib/query.ts — react-query hooks（仿 useAuctionTop）
```ts
// 读 hooks（窗口参数入 queryKey，切窗自动重查）
export const useWinRateStats = (windowSize: number) =>
  useQuery({ queryKey: ["winrate","stats",windowSize], queryFn: () => api.winRateStats(windowSize) });
export const useWinRateTrends = (windowSize: number) =>
  useQuery({ queryKey: ["winrate","trends",windowSize], queryFn: () => api.winRateTrends(windowSize) });
export const useWinRateAdjustments = (windowSize: number) =>
  useQuery({ queryKey: ["winrate","adj",windowSize], queryFn: () => api.winRateAdjustments(windowSize) });
export const useWinRateSector = (sector: string, windowSize: number) =>
  useQuery({ queryKey: ["winrate","sector",sector,windowSize],
             queryFn: () => api.winRateSector(sector, windowSize), enabled: !!sector });
export const useWinRateStrategy = (strategy: string, windowSize: number) =>
  useQuery({ queryKey: ["winrate","strategy",strategy,windowSize],
             queryFn: () => api.winRateStrategy(strategy, windowSize), enabled: !!strategy });

// 写 hook：录入，成功后失效 stats/trends 触发刷新
export const useWinRateRecords = () =>
  useMutation({
    mutationFn: (records: WinRateRecordInput[]) => api.winRateRecords(records),
    onSuccess: (_data, records) => {
      queryClient.invalidateQueries({ queryKey: ["winrate","stats"] });
      queryClient.invalidateQueries({ queryKey: ["winrate","trends"] });
      // 若录入含 sector/strategy，也失效对应拆分
      const sectors = [...new Set(records.map(r => r.sector).filter(Boolean))];
      const strategies = [...new Set(records.map(r => r.strategy_used).filter(Boolean))];
      sectors.forEach(s => queryClient.invalidateQueries({ queryKey: ["winrate","sector",s] }));
      strategies.forEach(s => queryClient.invalidateQueries({ queryKey: ["winrate","strategy",s] }));
    },
  });
```

### 2.3 Monitor925 — 9:25 窗口 refetch
```ts
// 判定 9:15-9:30 窗口（客户端本地时间）
function isInAuctionWindow(): boolean {
  const now = new Date();
  const hm = now.getHours() * 60 + now.getMinutes();
  return now.getDay() >= 1 && now.getDay() <= 5 && hm >= 9*60+15 && hm <= 9*60+30;
}
// lib/query.ts
export const useAuctionMonitor = () =>
  useQuery({
    queryKey: ["auction","monitor"],
    queryFn: () => Promise.all([api.auctionMonitor(), api.auctionWatchlist()]),
    refetchInterval: isInAuctionWindow() ? 15000 : false,  // 窗口内 15s，窗口外停
    staleTime: 0,
  });
```
> react-query 内部用 AbortController 处理竞态，无需手写。窗口外 refetchInterval=false 停拉，组件显示最近快照 + 下次窗口倒计时（`setInterval(60s)` 算到次日 9:15）。

### 2.4 组件 props
```ts
// WinRateView：窗口滑块 + 四区 + RecordsForm
interface WinRateViewProps { defaultWindow?: 7 | 30 | 90 }  // 默认 30
// RecordsForm：受控表单 → useWinRateRecords().mutateAsync
interface RecordsFormProps { onSubmitted?: () => void }
// ScatterChart：echarts 散点
interface ScatterChartProps { points: { gene_score: number; next_day_return: number; code: string }[] }
```

## 3. 交互流程

### 3.1 records 录入（乐观更新/回滚）
1. 用户在胜率视图填「记入胜率」表单（stock_code/entry_date/exit_date 必填，其余可选）。
2. 提交 → `useWinRateRecords().mutateAsync([record])`（单条按 1 元素数组）。
3. react-query `onSuccess` → invalidate stats/trends/sector/strategy → 四区自动刷新。
4. 失败 → `mutateAsync` 抛出 → 表单 catch → toast 错误（`error_count`/`errors` 展示哪条失败）→ 表单保留输入不滚。
5. 后端返 `error_count>0`（部分失败）→ toast 提示 `added_count` 成功 + `errors` 详情。

### 3.2 Backtest 页内 TabBar
1. nav 点「胜率趋势」(key=winrate) → Backtest 页读 active sub-key → 切到 tab 2。
2. tab 1（回测结果）= 现有 startDate/endDate + scatter/result 内容（散点升级用 `<ScatterChart points={scatter}/>`)。
3. tab 2（胜率趋势）= `<WinRateView defaultWindow={30}/>`。

### 3.3 AuctionScreener 页内 TabBar
1. tab 1（竞价预案 TOP N）= 现有 useAuctionTop + STI 摘要 + TOP N 列表。
2. tab 2（盘中监控 9:25）= `<Monitor925/>`：窗口内 15s 刷新 monitor+watchlist；窗口外快照 + 倒计时。

## 4. 数据链路
- 复用 `lib/api.ts` 现有 `winRate*`（:148-157）+ `auctionMonitor/Watchlist`（:159-160）；**仅加 `winRateRecords` POST**。
- 读路径走 `lib/query` react-query hooks（仿 `useAuctionTop`），窗口/sector/strategy 入 queryKey 自动重查。
- 写路径（records）走 `useMutation` + `invalidateQueries` 触发读路径刷新。
- chart 用 echarts 6（复用 `components/charts/KLineChart.tsx` 初始化模式：`useEffect` + `echarts.init` + resize）。
- 后端零改动：6 winrate 端点（`win_rate.py`）+ 2 auction 端点（`bidding.py`）全在。
