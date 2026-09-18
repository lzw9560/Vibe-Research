# Plan: S178 — S176 OFI 盘中只读看板（技术方案）

> spec：`spec.md`。本文定「怎么做」：取舍、备选为何不选、模块拆分、依赖序、数据流。所有引用经 fresh grep/Read 核验。

## 0. 验证基底（核验过的事实，非记忆）

- `load_ofi(start, end)`（`intraday_accumulation_store.py:517-531`）返 11 字段，仅 `WHERE date >= ? AND date <= ?`，**无 LIMIT、无单日/单股过滤**。
- `_SCHEMA_OFI`（`intraday_accumulation_store.py:131-144`）：ofi REAL∈[-1,1]、regime TEXT(strong_trend/weak/bear)、buy_vols_json/sell_vols_json TEXT。
- `save_ofi`（488-514）、`_DB_PATH`（line 49，`.vibe-research/intraday_accumulation/`，gitignored）。
- `list_accumulation_dates`（467-481）UNION（472-477）含 rankings/quotes/baostock/auction，**不含 ofi_snapshots**。
- scheduler ofi_collect 已接线：`seed.py:208-219`（cron `*/3 9-14 * * 1-5`）+ `executors/__init__.py:60` dispatch + `:319-322` `_execute_ofi_collect` + `intraday.py:51` `ofi_collect()` → `collect_ofi_for_codes` → `save_ofi`。
- **无** `backend/routers/intraday_ofi.py`（gap 确认）；**无** `frontend/src/components/intraday/OfiDashboard.tsx`。
- router 范式：`journal.py:39-69`（`@router.get` + `asyncio.to_thread(_build)` + `Dict[str, Any]`）；个人数据隔离注释 `journal.py:7-9`（不 import chat/ai.tools）。
- `app.py` import 块 60-69 + `include_router` 块 265-289（配对模式）。
- 前端：`client.ts:36-67` `request<T>`，**line 66 `return (payload?.data ?? payload) as T`**（关键：auto-unwrap `data` key）；`api.ts:62-309` api 对象，`journalClosedLoop` 305-308 用 `get<T>(path)`；`journal.ts:149-156` `useClosedLoop` 用 `useQuery`+`api.journalClosedLoop`+`JOURNAL_STALE_MS`；`query/index.ts` barrel re-export；`JournalLedger.tsx`（GlassCard+ApiError+空态+honest 标签+表格）；`IntradayMonitor.tsx`（compose intraday 组件+SectionHeader+useIntraday* hook）；`router.tsx:14-27` `lazyEl` + `:69` `/workflow/intraday`；`components/intraday/` 5 件全情绪层。

## 1. 取舍与备选（为何不选）

### D1. 响应 envelope 用 `snapshots` key，不用 `data`

- **选**：`{ "snapshots": [...], "count": N, "date": str, "truncated": bool }`。
- **依据**：`client.ts:66` `payload?.data ?? payload`——若后端返 `{data: [...]}`，client 会 auto-unwrap 吐回数组，`count`/`truncated` 元数据丢失。用 `snapshots` key（非 `data`），client 走 `?? payload` 返完整对象，hook 按 `OfiResponse` 整体收，组件读 `resp.snapshots`。镜像 `journal.py:50` closed-loop 返 `{available, records, aggregate}`（无 `data` key）范式。
- **备选 `{data:[]}`**：不选。丢 `truncated` 元数据 → 无法诚实标「被截断」（R5/E2 honest 要求落空）。

### D2. 单股过滤在 router Python 层做，不改 `load_ofi` SQL

- **选**：router 调 `load_ofi(date, date)`（单日 start==end），再在 Python 按可选 `code` filter，再 `[:limit]` 截断。**不改 `intraday_accumulation_store.py`**。
- **依据**：`load_ofi` 是共享函数（save/collect 链路依赖），改签名爆炸半径大（违「最小改动」）。单日量级 ~5000 行（50 股 × ~100 ticks/日），Python filter+truncate 可接受（LIMIT 护的是前端 payload 非 DB load）。
- **备选 给 `load_ofi` 加 `code`/`limit` SQL 参数**：不选。爆炸半径过大 + 单日量级不需要 SQL 级过滤。**NOTE**：若未来支持多日范围查询，必须回头给 `load_ofi` 加 SQL 级 `code`+`LIMIT`（Python 层兜不住多日 12 万级），届时单独立 spec。

### D3. 单日强制（`date` required）而非多日区间

- **选**：`date: str = Query(...)` 单日必传。
- **依据**：`performance.md`「无界查询」红线——`load_ofi` 无 LIMIT，多日 = ~5000 行/日 × N 日，前端卡顿/大 payload。单日把上界钉在 ~5000 行。
- **备选 允许 start/end 多日 + LIMIT**：不选。OFI 是 per-3min 盘中微结构，单日时序已够看；多日聚合是 §44v2 conditioning harness 的活（S176 §9 deferred），不是本 read-only 看板。

### D4. 独立路由 `/workflow/intraday/ofi` + 薄 page，不嵌 IntradayMonitor

- **选**：新路由 → `@/pages/workflow/OfiDashboardPage`（薄包装：SectionHeader + honest banner + `<OfiDashboard />`）。
- **依据**：`IntradayMonitor.tsx` 是 Layer1-4 情绪辅助决策页，带 AskAi 上下文注入（line 3 注释「注入四层真实数据作上下文」）。OFI 是 conditioning 数据·非信号，嵌进去会（a）clutter 情绪页、（b）AskAi 可能把微结构数据注入 AI prompt——触 R6 防 signal-creep。独立路由隔离干净。
- **备选 嵌 IntradayMonitor 作 Layer5 section**：不选。污染情绪页 + 触发 AskAi 注入风险。独立路由 + 薄 page 更符合 YAGNI + 隔离。

### D5. TanStack `useQuery` hook，不用组件内直 fetch

- **选**：`lib/query/intraday-ofi.ts` `useIntradayOfi` 用 `useQuery`，staleTime 30s。
- **依据**：`JournalLedger.tsx`（最近似 data-page analog）用 TanStack hook（`useClosedLoop` from `@/lib/query`），带缓存/重试/状态。镜像 `journal.ts:149` 范式。OFI 采集 3min 一次，staleTime 30s（半采集周期）平衡新鲜度与节流。
- **备选 组件内 useState/useEffect+fetch（MultiArmPanel 范式）**：不选。`MultiArmPanel.tsx` 是信号展示页（一次性 load），OFI 是高频时序需缓存+refetch 状态，TanStack 更合。

### D6. date picker 自由输入默认今日，不做日期下拉

- **选**：前端 date input 自由输入 YYYY-MM-DD，默认今日（从 `useDateTriplet().today` 取，镜像 `IntradayMonitor.tsx:74` 时区锚定范式）。
- **依据**：日期下拉须后端暴露 `list_accumulation_dates`（当前无 API）+ 修 UNION gap（line 472-477 缺 ofi）。MVP 不必，YAGNI。
- **备选 日期下拉**：不选 MVP。降级 P2（T11 修 UNION + 加 dates 端点，独立后置）。

## 2. 模块拆分

| 层 | 文件 | 职责 | 行数估 |
|---|---|---|---|
| backend router | `backend/routers/intraday_ofi.py` (NEW) | `GET /api/intraday/ofi`，`asyncio.to_thread(_build)` wrap load_ofi+filter+truncate | ~35 |
| backend register | `backend/app.py` | +import +include_router | +2 |
| FE contract | `frontend/src/lib/intraday-ofi-contract.ts` (NEW) | `OfiSnapshot`/`OfiResponse` 类型（匹配 load_ofi 11 字段 EXACTLY） | ~30 |
| FE api | `frontend/src/lib/api.ts` | `intradayOfi(date,code?,limit)` 方法 | +3 |
| FE hook | `frontend/src/lib/query/intraday-ofi.ts` (NEW) | `useIntradayOfi` useQuery + barrel re-export | ~25 |
| FE component | `frontend/src/components/intraday/OfiDashboard.tsx` (NEW) | 表格+regime 色标+honest 标签+空态+ApiError+truncated 警告+date picker | ~140 |
| FE page | `frontend/src/pages/workflow/OfiDashboardPage.tsx` (NEW) | 薄包装：SectionHeader+honest banner+`<OfiDashboard/>` | ~30 |
| FE route | `frontend/src/router.tsx` | +1 路由行 | +1 |
| (P2) store fix | `backend/data/intraday_accumulation_store.py` | `list_accumulation_dates` UNION 补 ofi | +1 |

## 3. 依赖序

1. **API 契约定稿**（T1：字段=11 字段、envelope=`{snapshots,count,date,truncated}`、params=`date`必传+`code`?+`limit`、LIMIT 上界）——0 依赖，阻塞一切。
2. **后端 router**（T2，依赖 T1 + `load_ofi` 已存在）与 **前端契约+api+hook**（T4/T5/T6，依赖 T1 契约）——**T1 定稿后可并行写代码**。
3. **app.py 注册**（T3，紧跟 T2，+2 行）。
4. **前端组件**（T7，依赖 T6 hook + GlassCard/ApiError 已有）——验证需 backend 跑起来（验证耦合，T2/T3 须先可手动起）。
5. **page + 路由挂载**（T8，依赖 T7）。
6. **全量门**（T10，tsc+pytest）。
7. **(P2) UNION fix**（T11，完全独立，可后置并行）。

## 4. 数据流

```
scheduler ofi_collect (cron */3 9-14)
  → tencent 五档 fetch (不封 IP)
  → collect_ofi_for_codes (engine/intraday_ofi_collector.py)
  → save_ofi (intraday_accumulation_store.py:488)
  → intraday_ofi_snapshots 表 (.vibe-research/intraday_accumulation/intraday_microstructure.db)

[本 spec 新增只读链]
GET /api/intraday/ofi?date=&code=&limit=
  → router _build(): load_ofi(date, date)  ← 共享函数，不改
  → (code? filter in Python) → [:limit] truncate
  → {snapshots:[...], count, date, truncated}
  → api.intradayOfi (api.ts)
  → useIntradayOfi useQuery (query/intraday-ofi.ts, staleTime 30s)
  → OfiDashboard.tsx (表格 + regime 色标 + sparkline)
  → OfiDashboardPage.tsx (薄包装) → /workflow/intraday/ofi
```

## 5. 性能与诚实落地

- **无界防护**：`date` Query(...) 必传 + `limit` Query(2000, ge=1, le=10000) + `truncated` 元数据回传 → 单日上界 ~5000 行，LIMIT 2000 默认截断（前端 honest 标「结果截断至 N 行」）。
- **空库诚实**：load_ofi 空返 `[]` → router 返 `{snapshots:[], count:0, truncated:false}` → 组件空态「暂无 OFI 快照（盘中采集后显示）」不臆造。
- **honest 标签常显**：「conditioning 数据收集 · 非交易信号」banner 常驻页顶（非空态才显），对齐 S176 §8 R8 + §9 deferred。
- **非交易时段**：OFI 表无当日行 → 空态，不假造盘中数据。