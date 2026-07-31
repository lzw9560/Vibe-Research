# Spec: S003 — 后端 API 冒烟测试缺陷修复批次

> 状态：已实现(2026-07-29)
> 作者：Claude  日期：2026-07-29
> 关联：`ARCHITECTURE.md` §"已知问题"、S001（chat 已修）、S002
> 测试基线：2026-07-29 对**当前 develop 代码**起的全新 uvicorn(:8902) 实测 105 端点。

## 1. 问题 / 目标

对当前代码起全新后端实例，逐端点冒烟测试 105 个 API，发现 **1 个 CRITICAL + 4 个 HIGH + 1 组 MEDIUM** 共 6 类缺陷。本 spec 汇总修复方案，使全部端点恢复 2xx（数据源本身不可用时降级为空结果/501 而非 500/502 崩溃）。chat 500 已由 S001 修复，但**用户当前运行的 :8900 进程是 S001 修复前启动的陈旧进程**（见 §8 运维项）。

## 2. 背景 / 实测数据

| 端点 | 实测 | 根因定位 |
|---|---|---|
| `GET /api/risk/dashboard` `oneday/list` `seats` `stock/{code}` | 挂起 >90s，并**拖垮全站** | `routers/risk.py` `async def` 内顺序 `await risk.update_one_day_risk_realtime()` ×50/100，该函数及 `_get_dragon_tiger_risk`/`_calculate_volatility` 等在 async 函数里做**同步阻塞网络 I/O**（astock em_get），未走 `asyncio.to_thread`，**阻塞事件循环**。单次请求即令所有 async 与 sync(threadpool 派发依赖事件循环) 端点全部 stall。已并发验证：risk/dashboard 挂起期间 weather/pardon、workflow/status 同步 stall 90s+。 |
| `GET /api/market/sti/latest` | 502 `module 'limitup_sti' has no attribute 'BEIJING_TZ'` | `routers/sti.py:28` 用 `ls_sti.BEIJING_TZ`，但 `limitup_sti` 包 `__init__.py` 未导出 `BEIJING_TZ`；真实定义在 `limitup_sti/service.py:35` 为**私有** `_BEIJING_TZ`。 |
| `GET /api/limitup/metrics` | 502 `'ScreenerResult' object has no attribute 'candidates'` | `routers/limitup/metrics.py:50/57/58` 访问 `screener_result.candidates`，但 `ScreenerResult` 仅有 `qualified`/`high_gene`/`gene_scores`（见 `pre_market_workflow.py` 用法）。 |
| `GET /api/scheduled-tasks/types` | 422 `int_parsing` | `routers/scheduled_tasks.py` `/{task_id}`(int) 路由注册在 `/types` 之前，FastAPI 按注册序匹配，`/types` 被 `/{task_id}` 捕获。前端 `getScheduledTaskTypes()` 直接坏。 |
| `GET /api/kline-history/stats`、`/api/kline-history/{code}` | 502 `no such table: kline` | `routers/kline_history.py` 查 `data/kline_history.db` 的 `kline` 表，表不存在（库未建表/未同步）。 |
| `GET /api/disclosure` `kline` `finance` | 502 `string indices must be integers` / `not enough values to unpack (expected 2, got 0)` | `astock.disclosure`(akshare) / `kline`,`finance`(mootdx) 解析器未处理空/异常返回，裸解包崩溃。 |
| `GET /api/recommendation/{code}` | 404 `未找到该股票的推荐数据` | 600519 非当日候选池标的，无推荐。**数据可得性，非缺陷**——但前端对任意个股调用，建议返回空而非 404。 |

> 已确认**非缺陷**：`/api/sentiment/weather/*`（latest/factors/strategy/fuse/timeline/events/auction/seal-risk/pardon/fuse-history）在当前代码均 0.0s 返回 200；smoke 里的 weather 超时全是 risk 阻塞事件循环的级联副作用。`/api/workflow/*` 同理（单独调用均正常）。chat（S001 已修）。

## 3. 需求清单

- [ ] R1（CRITICAL）risk 端点不再阻塞事件循环：阻塞 I/O 全部走 `asyncio.to_thread`；`/api/risk/dashboard`、`/api/risk/oneday/list` 对 50/100 只票的循环改为并发（`asyncio.gather`+`return_exceptions=True`）+ 上限（如 ≤20）+ 路由级缓存（`cache_response`）；并验证调用期间 `/api/sentiment/weather/pardon`、`/api/workflow/status` 不被拖累（<2s）。
- [ ] R2（HIGH）`limitup_sti` 包 `__init__.py` 导出 `BEIJING_TZ`（或在 `routers/sti.py` 内 `from limitup_sti.service import _BEIJING_TZ as BEIJING_TZ`）；`/api/market/sti/latest` 返回 200。
- [ ] R3（HIGH）`routers/limitup/metrics.py` 将 `.candidates` 改为正确属性（`qualified` 或 `gene_scores`，按语义选）；`/api/limitup/metrics` 返回 200。
- [ ] R4（HIGH）`routers/scheduled_tasks.py` 将 `/api/scheduled-tasks/types` 路由**移到** `/{task_id}` 之前（或用独立前缀）；`/api/scheduled-tasks/types` 返回 200 + 类型列表。
- [ ] R5（HIGH）`kline_history.db` 缺 `kline` 表：建表 schema（与 `kline_sync` 写入一致），并在路由层捕获"无表"返回 `{"data": [], "syncing": false}` 而非 502；触发一次 `kline_sync` 初始化。
- [ ] R6（MEDIUM）`astock.disclosure/kline/finance` 解析器对空/异常返回做守卫（空则返回 `[]`/`{}` 或抛 `DependencyMissing`→501），不再裸解包 502。
- [ ] R7（LOW）`/api/recommendation/{code}` 无数据时返回 `{"data": null}` + 200（或空数组），而非 404，避免前端误判。
- [ ] R8（运维）`:8900` 陈旧进程需重启以生效 S001 与 candidates 路由（见 §8）。

## 4. 受影响文件

| 文件 | 改动 |
|---|---|
| `backend/routers/risk.py` | R1：`to_thread` + 并发 + 上限 + `cache_response` |
| `backend/risk_models.py` | R1：阻塞网络调用包进 `asyncio.to_thread`，或新增 async 包装；保留同步内核 |
| `backend/limitup_sti/__init__.py` | R2：`__all__` 与 import 增加 `BEIJING_TZ`（re-export `service._BEIJING_TZ`） |
| `backend/routers/sti.py` | R2：如不改包则改为 `from limitup_sti.service import _BEIJING_TZ as BEIJING_TZ` |
| `backend/routers/limitup/metrics.py` | R3：`.candidates` → `qualified`/`gene_scores`（核对字段语义） |
| `backend/routers/scheduled_tasks.py` | R4：调整路由注册顺序（`/types` 在 `/{task_id}` 前） |
| `backend/routers/kline_history.py` | R5：缺表守卫 + 建表初始化 |
| `backend/kline_sync.py`（或新建 schema） | R5：`CREATE TABLE IF NOT EXISTS kline ...` |
| `backend/astock.py` | R6：`disclosure`/`kline`/`finance` 空返回守卫 |
| `backend/routers/recommendation.py` | R7：无数据返回 200+null 而非 404 |

## 5. 设计方案

- **R1（核心）**：`risk_models.update_one_day_risk_realtime` 是 `async def` 但内部 `_get_dragon_tiger_risk` 等做同步 `requests`/`em_get`。方案：保留同步数据层不动，在 router 层用 `await asyncio.to_thread(risk.update_one_day_risk_realtime, code)`，并 `gather` 并发（信号量限 8）跑前 20 只（dashboard）/前 50 只（oneday/list）；加 `cache_response(ttl=120)`。备选：把 risk 端点改成 `def`（同步，跑 threadpool，天然不阻塞事件循环）——更省改动，但 50 顺序调用仍慢，故仍需并发+上限。**取舍**：优先 to_thread+并发+缓存。
- **R2**：包 `__init__` re-export 最干净，向后兼容。不动 `service.py` 私有名。
- **R3**：核对 `ScreenerResult` 字段——`qualified`（合格池）即 metrics 想要的"候选"，把 3 处 `.candidates` 改 `.qualified`；`avg_fbt` 字段确认 `GeneScore` 是否有，无则跳过该胜率分项。
- **R4**：FastAPI 按声明顺序匹配，仅把 `@router.get("/api/scheduled-tasks/types")` 上移到 `/{task_id}` 之前即可；或 `/types` 改 `/api/scheduled-tasks-types`（不选，破坏前端契约）。
- **R5**：`_get_kline_db()` 打开后 `CREATE TABLE IF NOT EXISTS kline(code, date, open, high, low, close, volume, amount, name, PRIMARY KEY(code,date))`（字段以 `kline_sync` 写入为准）；路由缺表 catch 返回空集。
- **R6**：`disclosure`：akshare 返回非 dict/空时返回 `[]`；`kline`/`finance`：mootdx 返回空元组时返回 `{"data": []}` / `None`，或抛 `DependencyMissing("mootdx 未返回数据")`→501。
- **R7**：`recommendation_stock` 找不到时 `return {"data": None}`。

## 6. 验收标准

- [ ] A1 `/api/risk/dashboard` 在 ≤30s 内返回 200；调用期间并发 `/api/sentiment/weather/pardon`、`/api/workflow/status` 均 ≤2s 返回 200。
- [ ] A2 `/api/market/sti/latest` → 200。
- [ ] A3 `/api/limitup/metrics` → 200。
- [ ] A4 `/api/scheduled-tasks/types` → 200 + 字符串列表。
- [ ] A5 `/api/kline-history/stats`、`/api/kline-history/{code}` → 200（空集也 200，不再 502）。
- [ ] A6 `/api/disclosure`、`/api/kline`、`/api/finance` 对 600519：数据源有数据→200；无数据→空集 200 或 501（不再 502 崩溃）。
- [ ] A7 `/api/recommendation/600519` → 200 + `{"data": null}`。
- [ ] A8 `pytest -m "not live"` 全过；重跑 `smoke_test_apis.py` 失败端点为 0。
- [ ] A9 合规自查（§7）逐条通过。

## 7. 合规自查（投研红线，逐条确认）

- [x] R1–R7 仅修可用性/降级，不引入方向性建议、不预置标的、不排名、不预测。
- [x] 不触碰涨停四池原始个股名接 API/UI；不破坏 `market._emotion` 聚合。
- [x] 不改 `chat.SYSTEM_PROMPT` 中立规则。
- [x] 不涉及用户私有数据（持仓/研报/key）读写变更。
- [x] R5 新建表/同步不新增东财端点；R1 调用 `risk_models` 复用既有 `em_get` 限流路径，不裸调 requests。

## 8. 测试计划

- 单测：`tests/test_risk_async.py`——mock `update_one_day_risk_realtime`，验证并发、上限、缓存、不阻塞（`asyncio` 内并发另一请求）；`test_sti_env.py` 验证 `BEIJING_TZ` 导出；`test_scheduled_tasks_route.py` 验证 `/types` 优先匹配。
- 集成：重跑 `backend/smoke_test_apis.py`（已留存），目标失败 0；对 risk 端点单独并发验证 A1。
- 手动：重启 :8900（运维项 R8）后用浏览器打开风险仪表盘 / 情绪气象站 / 定时任务新建页确认无 500/超时。

## 9. 风险与回滚

- R1 改 risk 并发可能放大东财 QPS——必须保留 `em_get` 限流/熔断；信号量 ≤8，避免被封 IP。回滚：恢复顺序 `await`。
- R2 re-export `BEIJING_TZ` 影响面小，回滚删 import 即可。
- R5 建表若字段与 `kline_sync` 不一致会写入失败——实现时以 `kline_sync` 实际 INSERT 列为准对齐。
- R8 重启 :8900 会短暂中断（秒级），并使运行中定时任务调度器重启（SQLite 持久化，任务不丢）。

## 10. 运维项（R8，非代码）

当前 `:8900` 是 S001 修复前启动的陈旧进程：`/api/settings/llm-env-status`、`/api/chat` 仍 500，candidates/funnel 路由未注册（404）。**需重启后端**以加载 S001 修复 + candidates 路由：
```
# 找到并停止旧 :8900 进程后
cd backend && .venv/Scripts/python.exe -m uvicorn app:app --host 127.0.0.1 --port 8900 --reload
```
重启后 chat/candidates 即恢复；本 spec 的 R1–R7 修复也需重启生效。
