# Spec: S178 — S176 OFI 盘中数据只读看板（前端 dashboard）

> 状态：已实现（backend router 7 tests passed + tsc0；2026-09-10）
> 关联：`../S176-盘中conditioning数据收集器/spec.md`（后端采集器，已实现 b2e4ca6）、`../S167-盘中微结构数据累积/spec.md`（store 基建）
> 分级：medium（medium 免 feature 分支但走 issue 层单轮 review；非纯文档/typo 故不免 SDD；无数据输出/AI 提示词/交易信号，弱合规仅核工程底线）

## 1. 问题 / 目标

S176 后端 OFI 五档采集器已就绪（`ofi_collect` cron `*/3 9-14` 写 `intraday_ofi_snapshots` 表），但采集到的数据**不可见**——用户无法监控采集质量、看不到五档盘口微结构快照。需求：建一个 **read-only 看板**可视化已采集的 OFI 快照（监控采集质量 + 为未来 §44v2 conditioning lift 验证备料视图），明确**非信号生成器**（honest label「conditioning 数据收集 · 非交易信号」）。

UI 先行（memory `ui-first-implementation-order`）：先定 API 契约（字段/过滤/envelope），再 backend router（trivial wrap `load_ofi`），再前端组件。

## 2. 背景

### 2.1 后端数据层（已就绪，fresh 核验）

- `load_ofi(start, end)`（`backend/data/intraday_accumulation_store.py:517-531`）返 11 字段：`date/ts/code/ofi/ofi_abs/bid_ask_pressure/buy_vols_json/sell_vols_json/seal_amount/regime/snapshot_at`，按 `date,ts,code` 排序。**注意：签名仅 `(start, end)` 区间，无单日/单股过滤参数、无 LIMIT**——全量返 date 区间。
- `_SCHEMA_OFI`（同文件 :131-144）：`ofi` REAL ∈ [-1,1]（跨股可比归一化）、`ofi_abs`=Σbuy-Σsell、`bid_ask_pressure`=Σbuy/Σsell（涨停 sell=0 cap 999）、`regime` TEXT（strong_trend/weak/bear，conditioning 分层用）、`buy_vols_json`/`sell_vols_json` TEXT（五档量，重算用）、`seal_amount`（涨停封单额）。
- `save_ofi`（:488-514）幂等写 PK(date,ts,code) INSERT OR REPLACE。
- DB 路径 `_DB_PATH`（:49）= `.vibe-research/intraday_accumulation/intraday_microstructure.db`，gitignored（CLAUDE.md §1.2 工程底线：私有数据隔离）。

### 2.2 采集器已接线（fresh 核验）

- `scheduler/seed.py:208-219` seed `ofi_collect` 任务（cron `*/3 9-14 * * 1-5`）。
- `scheduler/executors/__init__.py:60` dispatch 注册 + `:319-322` `_execute_ofi_collect` → `scheduler/executors/intraday.py:51` `ofi_collect()` → `engine.intraday_ofi_collector.collect_ofi_for_codes` → `save_ofi`。数据在采集中。

### 2.3 现状缺口（fresh 核验）

- **无 API**：`backend/routers/` 下无 OFI 端点（仅 `intraday_sentiment.py` 是 S063 情绪 router，非 OFI）。`ls backend/routers/intraday_ofi.py` → 不存在。
- **无前端**：`frontend/src/components/intraday/` 现有 5 件（EmotionTrendChart/HoldingsEmotionTable/ScenarioCards/StateMachineDashboard/T1ProjectionPanel）全情绪 Layer1-4，无 OFI 组件。
- **无 api client 方法**：`frontend/src/lib/api.ts` api 对象（:62-309）无 ofi 方法。
- **无路由**：`frontend/src/router.tsx`（:29-96）仅 `/workflow/intraday`→IntradayMonitor（情绪页），无 OFI 路由。
- **(minor) `list_accumulation_dates`**（intraday_accumulation_store.py:467-481）UNION（:472-477）含 rankings/quotes/baostock/auction 四表但**不含 ofi_snapshots**——date picker 可用日期会漏 OFI-only 日。

### 2.4 范式已摸清（fresh 核验）

- 后端 router：`backend/routers/journal.py:39-69`——`@router.get("/api/...")` + `async def` + `asyncio.to_thread(_build)` 返 `Dict[str, Any]`；个人数据隔离注释 `:7-9`（「本路由不 import chat/ai.tools」）。
- `app.py`：router import 块（:60-69）+ `app.include_router(...)` 块（:265-289）配对。
- 前端 client：`frontend/src/lib/api/client.ts:36-67` `request<T>`，**`:66` `return (payload?.data ?? payload) as T`**——auto-unwrap `data` key（设计 D1 据此决定用 `snapshots` key 不用 `data`）；`:5-9` `ApiError`。
- 前端 api 对象：`frontend/src/lib/api.ts:62-309`，`journalClosedLoop`（:305-308）用 `get<T>(path)`（path 不带 `/api` 前缀，`request` 内 `:50` `fetch(\`/api${path}\`)` 加前缀）。
- 前端 hook：`frontend/src/lib/query/journal.ts:149-156` `useClosedLoop` 用 `useQuery`+`api.journalClosedLoop`+`JOURNAL_STALE_MS`（5min）；`query/index.ts` barrel re-export 各域文件。
- 前端组件：`JournalLedger.tsx`（GlassCard + ApiError + useQuery hook + honest 标签 PaperNotRealBanner + 空态 :192-205「暂无闭环交易记录」+ 表格）；`IntradayMonitor.tsx`（compose intraday 组件 + SectionHeader + AskAiButton + useIntraday* hook + 时区锚定 `useDateTriplet`）。
- 路由：`router.tsx:14-27` `lazyEl(() => import("@/pages/..."))` + `:69` `/workflow/intraday`。

## 3. 需求清单

- [ ] **R1 backend API**：新增 `backend/routers/intraday_ofi.py`，`GET /api/intraday/ofi?date=&code=&limit=`（wrap `load_ofi` + `asyncio.to_thread`，仿 journal.py:39）。`date` 必传（单日，防无界）；`code` 可选（6 位裸 code，Python 层 filter）；`limit` 默认 2000、上限 10000（防无界 payload）。返 `{snapshots:[], count, date, truncated}` envelope（用 `snapshots` key 不用 `data`，避 client.ts:66 auto-unwrap 吞元数据——见 plan D1）。
- [ ] **R2 前端组件**：新增 `frontend/src/components/intraday/OfiDashboard.tsx`，仿 JournalLedger.tsx。含 OFI 时序表（date/ts/code/ofi/bid_ask_pressure/seal_amount/regime 列）+ regime 分层色标（strong_trend 绿/weak 黄/bear 红）+ 单股 sparkline（ofi 时序）+ date picker（默认今日，`useDateTriplet` 时区锚定）。
- [ ] **R3 api client + hook**：`lib/api.ts` 加 `intradayOfi(date, code?, limit)` 方法（仿 :305-308）；`lib/query/intraday-ofi.ts` 加 `useIntradayOfi(date, code?, limit)` hook（仿 journal.ts:149，TanStack useQuery，staleTime 30s——OFI 3min 采集一次，30s stale 平衡新鲜度与节流）；`query/index.ts` barrel re-export；`lib/intraday-ofi-contract.ts` 类型（`OfiSnapshot` 11 字段 + `OfiResponse` envelope，contract-first 仿 journal-contract.ts）。
- [ ] **R4 路由挂载**：`router.tsx` 加 `{ path: "/workflow/intraday/ofi", element: lazyEl(() => import("@/pages/workflow/OfiDashboardPage")) }`（仿 :69）；新增薄 page `OfiDashboardPage.tsx`（SectionHeader + honest banner + `<OfiDashboard />`，仿 Journal 页包装 JournalLedger）。
- [ ] **R5 honest 呈现**：空数据 → 「暂无 OFI 快照（盘中采集后显示）」空态（仿 JournalLedger :192-205）；常显 honest label 「conditioning 数据收集 · 非交易信号」banner（对齐 S176 §8 R8「不喂 trade_journal」+ §9 deferred conditioning harness）；`truncated=true` 时显「结果截断至 N 行（单日上界，调高 limit 或缩小 code）」。
- [ ] **R6 不接入 AI prompt**：`backend/routers/intraday_ofi.py` 不 import `chat`/`ai.tools`（仿 journal.py:7-9）。**前提纠正**（核心六条 #1）：测绘将此框为「个人数据隔离」，但 OFI 是公开盘口微结构数据（五档量/封单），**非个人持仓/key**——故准确口径是「防 signal-creep：conditioning 数据默认不进 AI 工具链避免被误用为交易信号源」，非隐私隔离。公开盘口数据本身可呈现，无个股隐藏需求。

## 4. 受影响文件

| 文件 | 改动 |
|---|---|
| `backend/routers/intraday_ofi.py` (NEW) | `GET /api/intraday/ofi`，wrap `load_ofi(date,date)` + Python filter code + truncate limit，`asyncio.to_thread`，~35 行 |
| `backend/app.py` | +2 行：import（仿 :60-69 块）+ `app.include_router`（仿 :265-289 块） |
| `frontend/src/lib/intraday-ofi-contract.ts` (NEW) | `OfiSnapshot`（11 字段匹配 load_ofi）+ `OfiResponse`（{snapshots,count,date,truncated}）类型 |
| `frontend/src/lib/api.ts` | api 对象加 `intradayOfi(date, code?, limit=2000)` 方法（仿 :305-308），+3 行 |
| `frontend/src/lib/query/intraday-ofi.ts` (NEW) | `useIntradayOfi` useQuery hook（staleTime 30s），~25 行 |
| `frontend/src/lib/query/index.ts` | barrel 加 `export * from "./intraday-ofi"` |
| `frontend/src/components/intraday/OfiDashboard.tsx` (NEW) | 表格 + regime 色标 + sparkline + date picker + honest 标签 + 空态 + ApiError 处理，~140 行 |
| `frontend/src/pages/workflow/OfiDashboardPage.tsx` (NEW) | 薄包装：SectionHeader + honest banner + `<OfiDashboard />`，~30 行 |
| `frontend/src/router.tsx` | +1 路由行（仿 :69） |
| (optional P2) `backend/data/intraday_accumulation_store.py` | `list_accumulation_dates` UNION（:472-477）补 ofi_snapshots，+1 行 |

## 5. 设计方案

见同目录 `plan.md`。要点：① envelope 用 `snapshots` key（避 client.ts:66 auto-unwrap 吞 `truncated` 元数据）；② 单股过滤在 router Python 层做不改共享 `load_ofi`（最小爆炸半径，单日 ~5000 行可接受）；③ 单日强制（防无界，对齐 performance.md）；④ 独立路由不嵌 IntradayMonitor（避免 AskAi 把微结构数据注入 AI prompt 触 R6）；⑤ TanStack useQuery hook（仿 JournalLedger 数据页范式）；⑥ date picker 自由输入默认今日，日期下拉 P2 后置（避 list_accumulation_dates UNION gap）。

## 6. 验收标准

- [ ] **A1** 后端 TestClient `GET /api/intraday/ofi?date=2026-09-10` 返 `snapshots` 数组，每元素含 load_ofi 11 字段（ofi/ofi_abs/bid_ask_pressure/buy_vols_json/sell_vols_json/seal_amount/regime 非空当有数据）。
- [ ] **A2** 空 DB（无 ofi_snapshots 行）→ `{snapshots:[], count:0, truncated:false}` 不崩（200，非 500）。
- [ ] **A3** 缺 `date` 参数 → 422（`Query(...)` required）；`limit=200000`（超 le=10000）→ 422；`limit=0` → 422（ge=1）。
- [ ] **A4** `cd frontend && npx tsc --noEmit` → 0 error。
- [ ] **A5** 前端空数据 → 「暂无 OFI 快照（盘中采集后显示）」空态 + 「conditioning 数据收集 · 非交易信号」banner 常显（浏览器手验）；`truncated=true` → 截断警告显示。
- [ ] **A6** `grep -E "chat|ai\.tools|trade_journal" backend/routers/intraday_ofi.py` → 无匹配（R6 防 signal-creep，不接 AI 工具链）。
- [ ] **A7** 单日强制生效：`load_ofi(date, date)` 单日调用，router 内 `[:limit]` 截断后 `truncated = (原 count > limit)`，前端可见截断标签——无多日无界 payload。

## 7. 合规与工程底线自查（逐条确认）

- [x] **研判/推荐/买卖时机**：本 spec 纯 read-only 数据查看器，不产推荐/信号/买卖时机。honest label 明示「非交易信号」。通过（弱合规·风险提醒级）。
- [x] **判断可复现/不臆造**：数据来自已采集 `intraday_ofi_snapshots` 表（`load_ofi` 纯读），不臆造。空库显空态不假造。通过（工程底线）。
- [x] **涨停四池/连板个股**：不涉。通过。
- [x] **用户私有数据隔离**：OFI 是公开盘口微结构数据（非持仓/key/研报），DB 在 `.vibe-research/`（gitignored）。read-only 不写私有数据。通过（工程底线）。
- [x] **`em_get` 防封**：本 spec 不触发任何东财端点——数据已由 S176 采集器（tencent 五档，不封 IP）采好，router 纯读 `load_ofi`。通过（工程底线，防封不涉）。
- [x] **不接入 AI prompt**：router 不 import chat/ai.tools（R6 防 signal-creep）。通过。

## 8. 测试计划

- **后端**：`backend/.venv/bin/python -m pytest backend/tests/test_intraday_ofi_router.py -m "not live"`（NEW，用 TestClient，仿 journal router 测试范式）。用例：① 有数据返 11 字段；② 空 DB 返 `{snapshots:[],count:0}`；③ 缺 date→422；④ limit 越界→422；⑤ code 过滤生效；⑥ truncated 标记。
- **前端**：`cd frontend && npx tsc --noEmit`（0 error）；可选 `npx vitest run` 若有组件测试基线（JournalLedger 无独立测试，对齐其范式可免单测，靠 tsc + 手验）。
- **手验**：盘中跑过 `ofi_collect` 后刷新 `/workflow/intraday/ofi` 见当日 OFI 时序行；非交易时段/未起 scheduler → 空态。
- **全量回归**：`backend/.venv/bin/python -m pytest -m "not live" --deselect` 加已知 flaky（newsradar/s040/s032，见 memory）。

## 9. 风险与回滚

- **风险 1（性能·主要）**：`load_ofi` 无 LIMIT，单日 ~50 股 × ~100 ticks = ~5000 行可接受，但若未来放开多日则 12 万级卡顿。**缓解**：API 强制单日 + limit 上界 10000。**回滚**：删 router + 前端路由（read-only 无数据副作用，删之即回）。
- **风险 2（次要）**：`list_accumulation_dates` UNION 缺 ofi → date 下拉（若 P2 做）漏 OFI-only 日。MVP 用自由输入避开。
- **风险 3（次要）**：非交易时段/未起 scheduler 空库 → 须 honest 空态不臆造（R5 兜底）。
- **回滚**：全 read-only，无写操作无数据副作用。删 `intraday_ofi.py` + 前端 5 文件 + app.py 2 行 + router 1 行即完全回滚，不影响 S176 采集器（独立链路）。