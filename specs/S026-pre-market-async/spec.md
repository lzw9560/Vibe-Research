# Spec: S026 — pre-market 异步化（修复服务卡死）

> 状态：已实现并并入 S023（异步修复作为 S023 一部分 squash 合并 develop，commit ed0a0fe；非独立分支，S026 分支已删）｜ 创建：2026-08-03
> 依据：codex 会话诊断 + CC 独立代码核查（registry.py / workflow.py / factors/*.py）+ 用户批准

---

## 1. 问题 / 目标

`GET /api/workflow/pre-market`（`workflow.py`）是 `async def`，但内部 sync 调 `factor_registry.fetch_all` → 在事件循环线程跑 → **阻塞整个 uvicorn 事件循环**。期间 `/api/health` 等所有端点无响应，前端 90s 超时看不到数据。

**根因（CC 核查确认）**：
- `fetch_all`（`registry.py`）sync `for` 循环**串行**跑两因子。
- `CandidateFunnelFactor.fetch` → sync `run_funnel`（R2 全市场批 50 + em_get）→ 直接阻塞事件循环 ~60-90s。
- `LimitupScreenerFactor.fetch` → `_await` 用 `ThreadPoolExecutor.submit(...).result()`，`.result()` **同步等** → 事件循环仍阻塞 ~60-90s。
- 合计 ~120-180s，health 响应不了。

**目标**：pre-market 从"请求即采集"改"触发采集 + 轮询结果"，采集在**线程**跑（`asyncio.to_thread`）释放事件循环；health 等端点在采集期间正常响应。

## 2. 背景

- 此 bug 是 S023 pre-market 端点（D1）的运行期问题；S023 未合并 develop，故本 spec 栈式 off feature/S023。
- codex 会话已诊断 + 提方案（BackgroundTasks + 内存缓存 + 触发/轮询），用户批准；CC 补充关键技术修正：**BackgroundTasks 单独不够**（任务函数仍跑事件循环线程），必须 `asyncio.to_thread` 把 sync fetch 丢线程。另可 `asyncio.gather` 并行两因子 → 120-180s → 60-90s。
- Celery/Redis 升级记 TODO（用户：放下个 spec）。
- 不属 S025（前端补入口）；B2（workflow 决策 UI）顺延。

## 3. 需求清单

- **R1** `async afetch_all`（`registry.py`）：`asyncio.gather(*[asyncio.to_thread(f.fetch, date, config) for f in factors])`，并行 + 线程化；保留 sync `fetch_all` 供测试/CLI。
- **R2** `POST /api/workflow/pre-market/refresh`（`workflow.py`）：立即返 `{run_id, status:"running"}`；`asyncio.create_task` 后台跑采集；`asyncio.Lock` 防并发（第二个 refresh 返"已有采集在跑"+现有 run_id）。
- **R3** `GET /api/workflow/pre-market` 改返缓存：有 → `{status:"done", factors, data_date, as_of, market_emotion}`；无/running → `{status, msg}`；error → `{status:"error", error}`。
- **R4** 后台 `_collect`：`await afetch_all(target)` + `await asyncio.to_thread(_fetch_market_emotion, target)` → 写内存缓存（带 run_id/status/as_of/error）。
- **R5** funnel rerun 端点（`candidates.py` 的 rerun）同病同治：改异步触发 + 轮询（或至少 `asyncio.to_thread` 包 sync rerun）。
- **R6** 前端 `PreMarketBriefing.tsx`：进入先 GET 缓存；无/旧 → POST refresh；running 时每 5s 轮询 GET 直到 done；done 渲染（复用现有因子分区渲染）。

## 4. 受影响文件

| 文件 | 改动 |
|---|---|
| `backend/factors/registry.py` | 加 `async afetch_all`（to_thread+gather）；sync `fetch_all` 保留 |
| `backend/routers/workflow.py` | `GET /pre-market` 改返缓存；加 `POST /pre-market/refresh` + `_collect` + `_cache`+`_lock` |
| `backend/routers/candidates.py` | funnel rerun 端点异步化（触发+轮询 或 to_thread 包裹） |
| `frontend/src/pages/workflow/PreMarketBriefing.tsx` | 加 refresh 触发 + 5s 轮询 + status 态展示 |
| `frontend/src/lib/query.ts` | 加 `usePreMarketRefresh`（mutation）+ `usePreMarket`（query，polling until done） |
| 后端其它 | 零（不动 factors/* 的 fetch，只在外层 to_thread 包裹） |

## 5. 设计方案

```python
# registry.py
import asyncio
async def afetch_all(date, config=None):
    factors = list(_registry.values())
    return await asyncio.gather(*[asyncio.to_thread(f.fetch, date, config) for f in factors])
# 注：to_thread worker 无 running loop → LimitupScreenerFactor._await 走 asyncio.run 分支，无嵌套问题

# workflow.py
import asyncio, uuid
_cache: dict = {"run_id": None, "status": "idle", "factors": None, "data_date": None, "as_of": None, "market_emotion": None, "error": None}
_lock = asyncio.Lock()

@router.post("/api/workflow/pre-market/refresh")
async def refresh_pre_market(date=None):
    target = date or last_trading_date_str()
    async with _lock:
        if _cache["status"] == "running":
            return {"run_id": _cache["run_id"], "status": "running", "msg": "已有采集在跑"}
        rid = uuid.uuid4().hex[:8]
        _cache.update(run_id=rid, status="running", data_date=target, error=None)
    asyncio.create_task(_collect(rid, target))   # 不 await
    return {"run_id": rid, "status": "running"}

async def _collect(rid, target):
    try:
        factor_registry.register_default_factors()
        results = await factor_registry.afetch_all(target)
        me = await asyncio.to_thread(_fetch_market_emotion, target)
        _cache.update(status="done", factors=[_serialize_factor(r) for r in results],
                      market_emotion=me, as_of=_now_iso())
    except Exception as e:
        _cache.update(status="error", error=str(e))

@router.get("/api/workflow/pre-market")
async def get_pre_market_workflow(date=None):
    if _cache["status"] == "idle" or not _cache["factors"]:
        return {"status": "idle", "msg": "未采集，请先 POST /pre-market/refresh"}
    return {"status": _cache["status"], "factors": _cache["factors"],
            "data_date": _cache["data_date"], "as_of": _cache["as_of"],
            "market_emotion": _cache.get("market_emotion"), "error": _cache.get("error")}
```
- **并发守卫**：`_lock` 只护 status 检查+置 running，不护采集本身（采集在 task 里，锁即释放）。
- **进程重启丢缓存**：内存缓存，重启返 idle（前端重新 refresh）。可接受（盘前每日重采）。
- **frontend**：`usePreMarket` = `useQuery({ queryKey:["pre-market"], refetchInterval: data?.status==="running" ? 5000 : false })`；进入时若 idle → 触发 `usePreMarketRefresh().mutate()`。

## 6. 验收标准

- **AC1** `POST /pre-market/refresh` < 200ms 返 `{run_id, status:"running"}`，不阻塞。
- **AC2** 采集期间 `GET /api/health` 正常响应（**核心**：事件循环不冻）。
- **AC3** `GET /pre-market` running 时返 `{status:"running"}`；done 时返 factors；idle 时返提示。
- **AC4** 两因子并行（afetch_all gather）→ 采集耗时 ≈ max(两因子) 非 sum（实测降半）。
- **AC5** 并发 refresh：第二个返"已有采集在跑"+原 run_id，不重复跑。
- **AC6** funnel rerun 端点不阻塞事件循环（to_thread 或异步触发）。
- **AC7** 前端 PreMarketBriefing：进入触发→轮询→done 渲染；running 显示"采集中"态。
- **AC8** `pytest -m "not live"` 全绿（含新 afetch_all/cache/lock 单测）；`npx tsc --noEmit` 过。

## 7. 合规与工程底线自查（弱合规·逐条）

- **判断可复现 / 不臆造**：✅ 不改数据采集逻辑（factors/* 的 fetch 不动），只把 sync fetch 用 to_thread 包到线程。em_get 限流/熔断仍后端侧既有。无新数据源、无臆造。
- **私有数据隔离**：✅ 不涉及持仓/研报/API key。内存缓存只存盘前因子产出（公开市场数据），无私有数据落盘。
- **防封**：✅ 不新增东财端点调用；采集仍走 factors→em_get（后端限流已有）。前端只轮询自身缓存。
- **仪式类**：N/A（无 AI 提示词、无交易信号；pre-market 是客观因子产出）。

**结论**：未触工程底线。

## 8. 测试计划

- **后端单测**（`backend/factors/tests/` 或新 test）：① `afetch_all` 并行+线程化（mock 两 factor.fetch，断言 gather+to_thread 调用）；② `_collect` 成功写缓存 done；失败写 error；③ `_lock` 并发 refresh 守卫（两个并发 → 第二个 running）；④ `GET /pre-market` 各 status 返回；⑤ funnel rerun 不阻塞（to_thread 包裹）。
- **live 冒烟**（手动）：起 uvicorn → POST refresh → 立即 GET health（应 200）→ 轮询 GET pre-market 到 done → 渲染。
- **前端**：`npx tsc --noEmit`；vitest（PreMarketBriefing 轮询态）。

## 9. 风险与回滚

- **栈式 off S023**：S026 分支 base=feature/S023。S023 合并 develop 后，S026 rebase onto develop。S023 若还在动（codex），S026 rebase 可能冲突——届时处理。
- **内存缓存重启丢**：可接受（盘前每日重采）；后续 Celery/Redis 升级时改持久。
- **funnel rerun 复杂度**：rerun 端点改异步触发+轮询工作量大；首版可只 `asyncio.to_thread` 包裹 sync rerun（不阻塞事件循环即可达标 AC6），触发/轮询模式留后续。
- **回滚**：还原 `workflow.py`（删 refresh/cache/_collect，GET 改回现采）+ `registry.py`（删 afetch_all）+ PreMarketBriefing（还原）。纯增量，回滚干净。
