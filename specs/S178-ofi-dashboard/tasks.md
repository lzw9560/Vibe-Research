# Tasks: S178 — S176 OFI 盘中只读看板

> spec：`spec.md` ｜ plan：`plan.md`。每条带依赖序 + 验收点 + 测试命令。TDD：先测后码（backend）。fresh 核验过的引用见 plan §0。

## T1 — 定 API 契约（0 依赖，阻塞一切）
- [ ] 写 `lib/intraday-ofi-contract.ts` 骨架先（纸面契约）：`OfiSnapshot` 11 字段（date/ts/code/ofi/ofi_abs/bid_ask_pressure/buy_vols_json/sell_vols_json/seal_amount/regime/snapshot_at，类型对齐 `_SCHEMA_OFI:131-144`：ofi `number|null`、regime `'strong_trend'|'weak'|'bear'|null`、json 字段 `string|null`）+ `OfiResponse = { snapshots: OfiSnapshot[]; count: number; date: string; truncated: boolean }`。
- [ ] 定 endpoint：`GET /api/intraday/ofi?date=YYYY-MM-DD(必传)&code=(可选)&limit=(默认2000,1..10000)`，返 `OfiResponse`（用 `snapshots` key 不用 `data`，避 client.ts:66 auto-unwrap）。
- 验收点：契约字段数 = 11、envelope key = `snapshots`、`date` 标必传。
- 测试：人工 review 契约文件。

## T2 — backend router `intraday_ofi.py`（依赖 T1 + load_ofi 已存在）
- [ ] 先写测试 `backend/tests/test_intraday_ofi_router.py`（RED，TestClient 仿 journal router 测试）：① `?date=2026-09-10` 有数据返 11 字段；② 空 DB 返 `{snapshots:[],count:0,truncated:false}` 200；③ 缺 date→422；④ `limit=200000`→422；⑤ `limit=0`→422；⑥ `?code=000001` 过滤生效；⑦ count>limit 时 `truncated=true`。
- [ ] 写 `backend/routers/intraday_ofi.py`：`router = APIRouter(tags=["intraday-ofi"])`；`@router.get("/api/intraday/ofi")` + `async def` + `date: str = Query(...)` + `code: str | None = Query(None)` + `limit: int = Query(2000, ge=1, le=10000)`；`_build()` 调 `load_ofi(date, date)`（单日 start==end）→ 若 code 则 `[r for r in rows if r["code"]==code]` → `truncated = len(filtered) > limit` → `filtered[:limit]` → 返 `{snapshots, count:len(filtered), date, truncated}`；`return await asyncio.to_thread(_build)`。不 import chat/ai.tools（R6）。
- [ ] 跑测试转 GREEN。
- 验收点：A1/A2/A3/A6/A7。
- 测试：`cd backend && .venv/bin/python -m pytest tests/test_intraday_ofi_router.py -m "not live" -v`

## T3 — `app.py` 注册（依赖 T2，+2 行）
- [ ] import 块（仿 :60-69）加 `from routers import intraday_ofi as intraday_ofi_router`。
- [ ] include_router 块（仿 :265-289）加 `app.include_router(intraday_ofi_router.router)  # S178：OFI 盘中只读看板`。
- 验收点：`from app import app` 不报 ImportError；TestClient `GET /api/intraday/ofi?date=X` 路由可达（非 404）。
- 测试：`cd backend && .venv/bin/python -c "from app import app; from starlette.testclient import TestClient; c=TestClient(app); print(c.get('/api/intraday/ofi?date=2026-09-10').status_code)"`（期 200 或 422-若 DB 空，非 404）

## T4 — frontend 契约文件（依赖 T1，可与 T2 并行）
- [ ] 写 `frontend/src/lib/intraday-ofi-contract.ts`（T1 纸面转实文件）：`OfiSnapshot` interface + `OfiResponse` interface。
- 验收点：字段与 load_ofi 11 字段 EXACTLY 匹配（contract-first 双向锁）。
- 测试：`cd frontend && npx tsc --noEmit`（0 error）

## T5 — `lib/api.ts` 加 `intradayOfi` 方法（依赖 T4）
- [ ] api 对象（:62-309）加（仿 :305-308）：
  `intradayOfi: (date: string, code?: string, limit = 2000) => get<OfiResponse>(\`/intraday/ofi?date=${date}${code ? \`&code=${code}\` : ""}&limit=${limit}\`)`。
- [ ] import `OfiResponse` from `@/lib/intraday-ofi-contract`。
- 验收点：path 不带 `/api` 前缀（request 内加）；类型 `<OfiResponse>`。
- 测试：`cd frontend && npx tsc --noEmit`

## T6 — `lib/query/intraday-ofi.ts` hook + barrel（依赖 T5）
- [ ] 写 `frontend/src/lib/query/intraday-ofi.ts`（仿 journal.ts:149-156）：
  `export function useIntradayOfi(date: string, code?: string, limit = 2000, options?: Opts<OfiResponse>) { return useQuery({ queryKey: ["intraday-ofi", date, code, limit] as const, queryFn: () => api.intradayOfi(date, code, limit), staleTime: 30 * 1000, ...options }); }`。
- [ ] import `useQuery` from `@tanstack/react-query`、`api` from `@/lib/api`、`Opts` from `./types`、`OfiResponse` from `@/lib/intraday-ofi-contract`。
- [ ] barrel `frontend/src/lib/query/index.ts` 加 `export * from "./intraday-ofi";  // S178：OFI 盘中只读看板`。
- 验收点：`useIntradayOfi` 可从 `@/lib/query` 导入。
- 测试：`cd frontend && npx tsc --noEmit`

## T7 — `OfiDashboard.tsx` 组件（依赖 T6 + GlassCard/ApiError 已有）
- [ ] 写 `frontend/src/components/intraday/OfiDashboard.tsx`（仿 JournalLedger.tsx）：
  - props: `{ date: string; code?: string; limit?: number }`；内部 `const q = useIntradayOfi(date, code, limit)`。
  - `q.error` → ApiError 横幅（仿 JournalLedger :170-177）。
  - `q.isLoading` → 「加载 OFI 快照…」。
  - 空（`q.data?.snapshots.length === 0`）→ GlassCard 空态「暂无 OFI 快照（盘中采集后显示）」+ 「S178 conditioning 数据收集 · 非交易信号」副标。
  - 有数据 → 表格列：ts / code / ofi（色标：>0 绿 <0 红）/ bid_ask_pressure / seal_amount / regime（strong_trend 绿/weak 黄/bear 红 徽章）；可选单股 ofi sparkline（inline SVG，最小）。
  - `q.data?.truncated` → 顶部黄条「结果截断至 N 行（单日上界，调高 limit 或指定 code）」。
  - 顶部常显 honest banner「conditioning 数据收集 · 非交易信号 · 数据来自盘中 ofi_collect 采集器」。
- 验收点：A5（空态 + banner + 截断标签）；tsc 0 error。
- 测试：`cd frontend && npx tsc --noEmit`；手验浏览器空态。

## T8 — page wrapper + 路由挂载（依赖 T7）
- [ ] 写 `frontend/src/pages/workflow/OfiDashboardPage.tsx`（仿 Journal 页包装 JournalLedger）：`export default function OfiDashboardPage()` → SectionHeader（标题「OFI 盘中微结构看板」+ 副标「S178 · conditioning 数据 · 非交易信号」）+ date input（默认 `useDateTriplet().today`，时区锚定仿 IntradayMonitor:74）+ code input（可选）+ `<OfiDashboard date={date} code={code} />`。
- [ ] `router.tsx`（仿 :69）加：`{ path: "/workflow/intraday/ofi", element: lazyEl(() => import("@/pages/workflow/OfiDashboardPage")) }`。
- 验收点：`/workflow/intraday/ofi` 可达（非 404）；date 切换触发 refetch。
- 测试：`cd frontend && npx tsc --noEmit`；浏览器访问路由。

## T9 — backend 全量 pytest 回归（依赖 T2/T3）
- [ ] 跑 backend 全量加 deselect flaky：`cd backend && .venv/bin/python -m pytest -m "not live" --deselect` newsradar/s040/s032 flaky（见 memory）。
- 验收点：新增 router 测试全绿 + 不破既有。
- 测试：上述命令。

## T10 — 全量门（依赖全部）
- [ ] `cd frontend && npx tsc --noEmit` → 0 error。
- [ ] `cd backend && .venv/bin/python -m pytest -m "not live" --deselect <flaky>` → 0 failed（除已知 flaky）。
- [ ] grep 验收 R6：`grep -E "chat|ai\.tools|trade_journal" backend/routers/intraday_ofi.py` → 无匹配（A6）。
- [ ] 手验：盘中跑过 ofi_collect 后刷新 `/workflow/intraday/ofi` 见当日行；空库 → 空态 + banner。
- 验收点：A1-A7 全过。

## T11 — (optional P2) `list_accumulation_dates` UNION 补 ofi（独立，可后置并行）
- [ ] `intraday_accumulation_store.py:472-477` UNION 加 `UNION SELECT date FROM intraday_ofi_snapshots`（+1 行）。
- [ ] 可选加 `GET /api/intraday/ofi/dates`（wrap `list_accumulation_dates`）供 date 下拉。
- 验收点：`python -c "from data.intraday_accumulation_store import list_accumulation_dates; print(list_accumulation_dates())"` 含 OFI-only 日。
- 测试：手验 dates 返回含 ofi 日期。
- 注：MVP 不依赖（T8 date picker 用自由输入），P2 后置。