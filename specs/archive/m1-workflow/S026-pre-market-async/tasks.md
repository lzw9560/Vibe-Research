# 任务拆分 · S026 pre-market 异步化

> 对应：`spec.md`（需求）、设计见 spec §5
> 粒度：原子任务（独立可验，1-2h/条）。TDD（先写测试→红→实现→绿→commit）。
> 分支：`feature/S026-pre-market-async`（栈式 off feature/S023）。

---

## 阶段 A · registry 异步采集（R1，AC4）

| ID | 任务 | 依赖 | 改动文件 | 验收方式 |
|---|---|---|---|---|
| A1 | `async afetch_all(date, config)`：`asyncio.gather(*[asyncio.to_thread(f.fetch, date, config) for f in factors])`；sync `fetch_all` 保留 | — | `backend/factors/registry.py` | 单测：mock 2 factor.fetch → afetch_all 并行调用（断言 gather+to_thread）；结果顺序对齐 factors |

## 阶段 B · refresh 端点 + 缓存 + 并发守卫（R2/R4，AC1/AC2/AC5）

| ID | 任务 | 依赖 | 改动文件 | 验收方式 |
|---|---|---|---|---|
| B1 | `_cache` dict + `_lock` asyncio.Lock + `_now_iso` helper | — | `backend/routers/workflow.py` | tsc/导入不报错 |
| B2 | `_collect(rid, target)` async：`await afetch_all` + `await asyncio.to_thread(_fetch_market_emotion)` → 写缓存 done；except 写 error | A1 | `backend/routers/workflow.py` | 单测：mock afetch_all 成功→cache.status=done+factors；抛错→status=error |
| B3 | `POST /api/workflow/pre-market/refresh`：lock 内检查 running→返"已有采集"+原 run_id；否则置 running + `asyncio.create_task(_collect)` 不 await → 返 run_id | B2 | `backend/routers/workflow.py` | 单测：refresh 返 running+run_id；并发两次→第二次返"已有采集在跑"+原 run_id |

## 阶段 C · GET 改返缓存（R3，AC3）

| ID | 任务 | 依赖 | 改动文件 | 验收方式 |
|---|---|---|---|---|
| C1 | `GET /api/workflow/pre-market` 改：idle→`{status:"idle",msg}`；running→`{status:"running",run_id}`；done→`{status:"done",factors,...}`；error→`{status:"error",error}`。删现采逻辑（保留 fallback 旧路径作 error 时降级可选） | B2 | `backend/routers/workflow.py` | 单测：各 status 返回正确字段；idle 不触发采集 |

## 阶段 D · funnel rerun 不阻塞（R5，AC6）

| ID | 任务 | 依赖 | 改动文件 | 验收方式 |
|---|---|---|---|---|
| D1 | funnel rerun 端点（`candidates.py` rerun）用 `asyncio.to_thread` 包 sync rerun（首版最小修复，不阻塞事件循环即可） | — | `backend/routers/candidates.py` | 单测：rerun 在 to_thread 调用（mock run_layer rerun）；handler 不阻塞（无 sync 长调） |

## 阶段 E · 前端轮询（R6，AC7）

| ID | 任务 | 依赖 | 改动文件 | 验收方式 |
|---|---|---|---|---|
| E1 | `lib/query.ts`：`usePreMarket`（useQuery，`refetchInterval: data?.status==="running"?5000:false`）+ `usePreMarketRefresh`（useMutation POST refresh） | C1 | `frontend/src/lib/query.ts` | tsc 过 |
| E2 | `PreMarketBriefing.tsx`：进入若 idle/无→触发 refresh；running 显示"采集中"态 + 轮询；done 渲染因子分区（复用现有） | E1 | `frontend/src/pages/workflow/PreMarketBriefing.tsx` + 测试 | vitest：idle→触发 refresh；running→显示态；done→渲染 |

## 阶段 F · 集成验收

| ID | 任务 | 依赖 | 改动文件 | 验收方式 |
|---|---|---|---|---|
| F1 | 后端全量离线测试 | A-E | — | `backend/.venv/bin/python -m pytest backend/factors/tests/ backend/candidate_funnel/tests/ backend/routers/ -m "not live"` 全绿 |
| F2 | **核心 live 冒烟**：起 uvicorn → POST refresh → **立即 GET /api/health（应 < 500ms 200，证明事件循环不冻）** → 轮询 GET pre-market 到 done | A-E | — | health 在采集期间 200；pre-market 终态 done |
| F3 | 前端：`npx tsc --noEmit` + vitest | E | — | 0 error；vitest 全绿 |
| F4 | 合规自查：无新数据源/无臆造；em_get 限流未动 | — | — | grep 无新增方向词；factors/*.py 未改 fetch 内部 |
