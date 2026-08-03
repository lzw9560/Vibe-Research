# Spec: S025 — 补前端入口（打板闭环：winrate + auction/monitor）

> 状态：已实现 ｜ 已 squash 合并 develop（主 `fc87a65` + review fix `951ae4e`/`501b3d3`/`b0161f8`/`2a39940`/`30e9239`）｜ code review 14/14 findings 闭环，tsc 0 error + vitest 16 files/98 tests 绿 ｜ 完成于 2026-08-04
> 覆盖分析依据：workflow `wf_71089e37-5a0`（12 组 143 端点，13 agent）

---

## 1. 问题 / 目标

体检遗留"30+ 后端路由无前端"，但覆盖矩阵核验为**假命题**：3 组已全覆盖、1 组 has-page、真实缺口 ~35 端点。其中**打板闭环**两块最该补：

- **winrate 反馈环**（6 端点）：5 个有封装零调用 + `POST /api/winrate/records` 无封装无调用 → 胜率系统数据摄入可能断链；nav 死链「胜率趋势」无落地页。
- **auction/monitor**（2 端点）：9:25 盘中确认信号零呈现（封装存在零调用）。

**目标**：补这两块前端入口，打通 holding→settled→胜率→策略调整闭环 + 9:25 竞价确认可视化。**纯前端消费现有后端端点，后端零改动。**

## 2. 背景

- **覆盖矩阵**（wf_71089e37）结论：3 组已全覆盖（value-funnel / prediction-sti / portfolio-watchlist-radar，不进 S025）；candidates-funnel has-page 仅打磨；真实缺口集中在 backtest-winrate（HIGH）+ ~35 MEDIUM 端点。10 个"有封装无 call-site"是假阳性（复合端点已内联数据），已排除。
- **P1 母本** `docs/superpowers/specs/2026-08-02-daban-workflow-p1-polish-design.md` = S023（因子解耦）+ S024（拓扑），**不含 winrate / auction / 状态机前端** → S025 与 P1 无意图冲突。
- **B2（workflow 决策：战法匹配器 / 手动触发 / WinRatePanel）与 S023/S024 重叠**（PreMarketBriefing 重构 + Workflow hub 拓扑入口）→ 移 **S026** 栈式 off S023/S024，本 spec 不含。
- **打板七态状态机当前无前端 UI**（grep `settled` 零命中组件）→ records 录入入口放胜率页表单，不依赖状态机 UI。
- **用户点名的 5 个**实际覆盖：/candidates ✓has-page、/funnel/config ✓has-page、/predict ✓has-page、/backtest 🟡partial（winrate 半组是缺口）、/proxy ❌none（**后端 router 未在 app.py 注册＝双端死代码**，且功能被 live /api/chat 覆盖，移 S027 单独处理）。

## 3. 需求清单

### B1 · winrate 闭环（6 端点，后端全在 `win_rate.py`）
- **R1 胜率视图**：`Backtest.tsx` 加 TabBar（回测结果 / 胜率趋势），激活 nav 死链「胜率趋势」。胜率视图 = FilterBar 窗口滑块（7/30/90 日）+ 四区：概览 MetricCard 矩阵（`winrate/stats`）、趋势折线（`winrate/trends`）、拆分 DataTable（`winrate/sector` + `winrate/strategy` 下钻）、调整建议 GlassCard（`winrate/adjustments`）。
- **R2 records 录入**：胜率视图加「记入胜率」表单（字段如 code/日期/收益/战法，**plan 阶段核对 `win_rate.py:100+` record dict schema 后对齐**）→ `POST /api/winrate/records`（body=records 列表）→ 乐观更新 + 失败回滚 + 刷新 stats/trends。
- **R3 backtest 散点图升级**：纯文本列表 → 散点图（复用 chart 组件，`backtest/scatter`）。

### B3 · auction/monitor（2 端点，后端在 `bidding.py`）
- **R4 盘中监控栏**：`AuctionScreener.tsx` 加 TabBar「盘中监控 9:25」栏：9:15–9:30 窗口 15s refetch `auction/monitor` + `auction/watchlist`；窗口外静态快照 + 下次窗口倒计时。

### 非目标（移 S026/S027）
- S026：战法匹配器、workflow 手动触发按钮、WinRatePanel 挂 Workflow hub、settled 状态机 UI。
- S027：个股深度 StockDeep 桩→真实页、ai_proxy /proxy（含后端 router 注册）、外送/运维（飞书推送、extreme、fuse）。

## 4. 受影响文件

| 文件 | 改动 |
|---|---|
| `frontend/src/pages/Backtest.tsx` | 改：加 TabBar（回测结果/胜率趋势），host 胜率视图 |
| `frontend/src/components/winrate/WinRateView.tsx` | 新建：胜率视图主体（FilterBar + 四区） |
| `frontend/src/components/winrate/RecordsForm.tsx` | 新建：records 录入表单（乐观更新/回滚） |
| `frontend/src/components/winrate/{StatsMetrics,TrendsChart,BreakdownTable,AdjustmentsCard}.tsx` | 新建：四区子组件 |
| `frontend/src/pages/limitup/AuctionScreener.tsx` | 改：加「盘中监控 9:25」TabBar 栏 |
| `frontend/src/components/auction/Monitor925.tsx` | 新建：9:25 监控（15s refetch + 窗口外降级） |
| `frontend/src/lib/api.ts` | 改：加 `winRateRecords` POST 封装（**唯一缺失**；winRateStats/Adjustments/Trends/Sector/Strategy + auctionMonitor/Watchlist 封装已存在） |
| `frontend/src/lib/api/types.ts` | 改：加 WinRateRecordInput 类型 |
| `frontend/src/components/layout/navigation.ts` | 不改：sub-item「胜率趋势」key 已在，页内 tab 直接复用 |
| `frontend/src/router.tsx` | 不改：用页内 TabBar，不新增路由 |
| **后端** | **零改动**（6 winrate + 2 auction 端点全在） |

## 5. 设计方案

- **路由策略**：Backtest.tsx 页内 TabBar（key=result/winrate，对齐 nav sub-item 无 `to:` 的页内 tab 模式），**不新增顶层路由、不改 router.tsx**。nav sub-item「胜率趋势」key 已在，由 Backtest 页读 active sub-key 切 tab。
- **数据流**：复用 `lib/api.ts` 现有 `winRateStats/Adjustments/Trends/Sector/Strategy` + `auctionMonitor/Watchlist`；**仅加 `winRateRecords` POST 封装**。hooks 模式（`useWinRateStats` 等，若不存在则建 thin hook）。
- **records 乐观更新**：POST 成功 → 本地 cache invalidate + 刷新 stats/trends；失败 → 回滚 + 错误 toast（复用 ui 组件）。
- **9:25 refetch**：9:15–9:30 用 `setInterval` 15s + `AbortController` 防竞态；窗口外 `clearInterval` 显示最近快照 + 下次窗口倒计时。
- **错误态**：复用 `EmptyState` / `Skeleton` / `ErrorBoundary`。
- **复用 UI**：FilterBar, TabBar, MetricCard, DataTable, GlassCard, 现有 chart 组件。
- **records 请求体**：`POST /api/winrate/records` 接 `records: List[Dict]`（`win_rate.py:93`）；单条录入按 1 元素数组提交。**plan 阶段须核对 record dict 字段**（从 `win_rate.py:100+` + `win_rate_tracker.py` 取 schema）。

## 6. 验收标准

- **AC1** nav「胜率趋势」可点 → 胜率视图渲染四区；FilterBar 窗口滑块切 7/30/90 日 → 数据刷新。
- **AC2**「记入胜率」表单提交 → `POST /api/winrate/records` 成功 → stats/trends 刷新；失败 → 回滚 + 错误提示。
- **AC3** backtest 散点图渲染（非纯文本列表）。
- **AC4** AuctionScreener「盘中监控 9:25」栏：9:15–9:30 内 15s 刷新 `auction/monitor`+`watchlist`；窗口外显示快照 + 倒计时。
- **AC5** `npx tsc --noEmit` 通过；vitest 新组件测试通过。
- **AC6** 后端零改动（`git diff backend/` 为空）。
- **AC7** 不碰 S023 工作树文件（PreMarketBriefing/FunnelLayers/candidate_funnel/ 等）。

## 7. 合规与工程底线自查（弱合规·逐条确认）

私人投研助理定位（CLAUDE.md §1）。工程底线（非合规仪式，保护用户钱与数据）逐条：

- **判断可复现 / 不臆造**：✅ 纯消费现有后端端点（`/winrate/*` `/auction/*`），无新数据源、无臆造、无心算。胜率是历史统计呈现，数据来自既有 `win_rate.py` 路由可复算。
- **用户私有数据隔离**：✅ 不涉及持仓/研报/API key 落 `.vibe-research/`。records 录入是用户手动填交易记录 → POST 后端 winrate 表（后端既有存储，非新增私有目录）。无新增私有数据落盘。
- **防封**：✅ 不新增东财端点调用；auction/monitor 走既有后端封装（后端侧 `em_get` 限流/熔断已有）。前端仅消费 JSON。
- **仪式类**（免责声明 / 中立措辞 / 不代客决策）：N/A——无 AI 提示词、无交易信号生成；胜率是客观历史统计呈现。

**结论**：未触工程底线。spec 合规自查通过（弱合规下仅核查工程底线）。

## 8. 测试计划

- **离线 vitest**（复用 `DataTable.test`/`FilterBar.test` 范式，AAA 结构）：
  ① WinRateView 四区渲染 + 窗口滑块切换数据；
  ② RecordsForm 提交流（乐观更新 / 回滚；mock POST 成功+失败两路）；
  ③ Monitor925 15s refetch 时序（fake timers）+ 窗口外降级 + AbortController 防竞态；
  ④ AuctionScreener tab 切换。
- **前端**：`cd frontend && npx tsc --noEmit`。
- **live 冒烟**（手动）：起 vite → 胜率视图四区 + records 录入 + 9:25 监控栏。

## 9. 风险与回滚

- **依赖 S023 工作树状态**（主要风险）：S023 未合并（工作树有 `funnel.py`/`models.py`/`candidate_funnel_factor.py`/`vr_paths.py`+新 test 未提交）。S025 纯前端、不碰 S023 文件（AC7），但起 `feature/S025` 分支前须先处理 S023 工作树（commit 到 S023 feature 分支 / stash），否则 checkout entangle（§0.1 两起回退事故同类）。**建议起分支顺序**：S023 先 commit 其 feature 分支 → S025 off develop（干净）；或 S025 暂仅在当前 HEAD 改 `frontend/`（不动 backend/）直到 S023 落定。
- **records 请求体 schema 未核**：plan 阶段核对 `win_rate.py:100+` + `win_rate_tracker.py` 的 record dict 字段，前端表单对齐。
- **回滚**：纯前端。删 `components/winrate/` + `components/auction/Monitor925.tsx` + 还原 `Backtest.tsx` / `AuctionScreener.tsx` / `router.tsx` / `navigation.ts` / `lib/api.ts`+`types.ts` = 全部还原，无副作用。
