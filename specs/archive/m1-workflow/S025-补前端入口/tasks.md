# 任务拆分 · S025 补前端入口（winrate + auction/monitor）

> 对应：`spec.md`（需求）、`plan.md`（技术方案）
> 粒度：原子任务（独立可验，1-2h/条）。每条含依赖、改动文件、验收方式、映射 AC。
> 规则：TDD（先写 vitest 测试→红→实现→绿→commit）；每条完成即跑对应测试；后端零改动；不碰 S023 文件（AC7）。
> 执行分支：`feature/S025-补前端入口`（off develop，见 plan §0.1）。

---

## 阶段 A · winrate lib 层（R1/R2 基础，AC1/AC2 前置）

| ID | 任务 | 依赖 | 改动文件 | 验收方式 |
|---|---|---|---|---|
| A1 | `WinRateRecordInput` + `WinRateRecordsResponse` 类型（字段对齐 `win_rate_tracker.py:18` WinRateRecord） | — | `frontend/src/lib/api/types.ts` | `tsc --noEmit` 过 |
| A2 | `winRateRecords` POST 封装（`post<WinRateRecordsResponse>("/winrate/records", records)`） | A1 | `frontend/src/lib/api.ts`（紧邻 :157 winRateStrategy） | `tsc` 过；`api.winRateRecords([])` 类型推断正确 |
| A3 | `useWinRateStats/Trends/Adjustments/Sector/Strategy` react-query 读 hooks（仿 `useAuctionTop`，windowSize 入 queryKey） | A1 | `frontend/src/lib/query.ts` | `tsc` 过；mock `api.winRateStats` → hook 返回 data |
| A4 | `useWinRateRecords` useMutation 写 hook（`onSuccess` invalidate stats/trends/sector/strategy） | A2 | `frontend/src/lib/query.ts` | 单测：mutate 成功 → invalidate 被调（spy queryClient） |
| A5 | `useAuctionMonitor` react-query hook（`refetchInterval` 按 `isInAuctionWindow()` 15s/false） | — | `frontend/src/lib/query.ts` | 单测：mock 窗口内→refetchInterval=15000；窗口外=false |

## 阶段 B · 胜率视图四区（R1，AC1）

| ID | 任务 | 依赖 | 改动文件 | 验收方式 |
|---|---|---|---|---|
| B1 | `StatsMetrics.tsx`：MetricCard 矩阵（总交易/胜数/胜率/平均收益/最大回撤/夏普），消费 `useWinRateStats` | A3 | `frontend/src/components/winrate/StatsMetrics.tsx` + `__tests__/StatsMetrics.test.tsx` | vitest：mock stats → 6 个 MetricCard 渲染 |
| B2 | `TrendsChart.tsx`：echarts 折线（复用 `KLineChart` 初始化模式），消费 `useWinRateTrends` | A3 | `frontend/src/components/winrate/TrendsChart.tsx` + 测试 | vitest：mock trends → echarts 容器渲染（mock echarts.init） |
| B3 | `BreakdownTable.tsx`：DataTable 按 sector + 按 strategy 下钻，消费 `useWinRateSector/Strategy` | A3 | `frontend/src/components/winrate/BreakdownTable.tsx` + 测试 | vitest：选 sector → 调 useWinRateSector → 表渲染 |
| B4 | `AdjustmentsCard.tsx`：GlassCard 呈现 `useWinRateAdjustments` | A3 | `frontend/src/components/winrate/AdjustmentsCard.tsx` + 测试 | vitest：mock adjustments → GlassCard 内容渲染 |
| B5 | `WinRateView.tsx`：FilterBar 窗口滑块（7/30/90）+ 四区编排（StatsMetrics/TrendsChart/BreakdownTable/AdjustmentsCard）+ 挂 RecordsForm | B1-B4,C2 | `frontend/src/components/winrate/WinRateView.tsx` + 测试 | vitest：切窗 7→30→90 → queryKey 变（spy hooks）；四区渲染 |

## 阶段 C · records 录入（R2，AC2）

| ID | 任务 | 依赖 | 改动文件 | 验收方式 |
|---|---|---|---|---|
| C1 | `RecordsForm` 受控表单组件骨架（stock_code/entry_date/exit_date 必填校验 + 其余可选） | A1 | `frontend/src/components/winrate/RecordsForm.tsx` | `tsc` 过；空提交 → 必填校验拦截 |
| C2 | `RecordsForm` 接 `useWinRateRecords`：提交→mutateAsync→成功 toast+清空；失败保留输入+错误 toast（展示 `added_count`/`errors`） | C1,A4 | 同上 + `__tests__/RecordsForm.test.tsx` | vitest：mock POST 成功 → 表单清空 + invalidate；mock 失败 → 保留输入 + 错误 toast |

## 阶段 D · backtest 散点图 + 页内 TabBar（R3，AC3）

| ID | 任务 | 依赖 | 改动文件 | 验收方式 |
|---|---|---|---|---|
| D1 | `ScatterChart.tsx`：echarts 散点（gene_score vs next_day_return），复用 KLineChart 模式 | — | `frontend/src/components/charts/ScatterChart.tsx` + 测试 | vitest：mock points → echarts 渲染 |
| D2 | `Backtest.tsx` 加 TabBar（回测结果 / 胜率趋势）：现有内容作 tab1，散点用 `<ScatterChart/>`，tab2 = `<WinRateView/>` | D1,B5 | `frontend/src/pages/Backtest.tsx` | vitest：tab 切换；tsc 过；散点图渲染（非纯文本列表） |

## 阶段 E · auction/monitor 监控栏（R4，AC4）

| ID | 任务 | 依赖 | 改动文件 | 验收方式 |
|---|---|---|---|---|
| E1 | `Monitor925.tsx`：消费 `useAuctionMonitor`；窗口内渲染 monitor+watchlist 实时；窗口外快照 + 下次窗口倒计时（`setInterval 60s` 算到次日 9:15） | A5 | `frontend/src/components/auction/Monitor925.tsx` + `__tests__/Monitor925.test.tsx` | vitest（fake timers）：窗口内→15s 触发 refetch；窗口外→显示快照+倒计时 |
| E2 | `AuctionScreener.tsx` 加 TabBar（竞价预案 TOP N / 盘中监控 9:25）：现有内容 tab1，`<Monitor925/>` tab2 | E1 | `frontend/src/pages/limitup/AuctionScreener.tsx` | vitest：tab 切换；tsc 过 |

## 阶段 F · 集成验收

| ID | 任务 | 依赖 | 改动文件 | 验收方式 |
|---|---|---|---|---|
| F1 | 全量前端类型检查 | A-E | — | `cd frontend && npx tsc --noEmit` 0 error |
| F2 | 全量 vitest | A-E | — | `cd frontend && npx vitest run` 全绿 |
| F3 | live 冒烟（手动）：起 vite → 胜率视图四区 + records 录入 + 9:25 监控栏 + backtest 散点 | A-E | — | 手测四区渲染/records 提交/tab 切换/散点图 |
| F4 | 后端零改动核查（AC6）+ 不碰 S023 文件核查（AC7） | A-E | — | `git diff develop -- backend/` 为空；`git diff develop -- backend/candidate_funnel/ backend/factors/ frontend/src/pages/workflow/PreMarketBriefing.tsx frontend/src/components/candidate/` 为空 |
| F5 | 合规自查：无 AI 提示词/交易信号生成；winrate 为历史统计呈现 | — | — | grep 无新增方向性买卖指令词 |
