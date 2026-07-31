# S003 任务拆分 — 后端 API 缺陷修复（原子 task）

> 关联 spec：`spec.md`（根因/设计/验收详见彼）。
> 原则：每 task 原子（≤1~2 文件、可独立验收、有明确依赖），按 Phase 顺序推进，Phase 内可并行。
> 约定：每个代码 task 完成后跑 `pytest -m "not live"`；涉及端点的额外跑对应 curl/冒烟。

## Phase 0 — 前置运维（非代码）

### T0 · 重启 :8900 加载 S001 与 candidates 路由  `[R8]`
- **文件**：无（运维操作）
- **依赖**：无
- **改动**：停掉陈旧 :8900 → `cd backend && .venv/Scripts/python.exe -m uvicorn app:app --host 127.0.0.1 --port 8900 --reload`
- **验收**：`GET /api/settings/llm-env-status`→200；`POST /api/chat`→200 流式（非 500）；`GET /api/workflow/candidates`→200；`openapi.json` 路径数 ≥131。
- **备注**：不阻塞代码 task（实现期用临时 :890x 实例）；上线前必做。

## Phase 1 — 小修快赢（彼此独立，可并行）

### T1 · limitup_sti 导出 BEIJING_TZ  `[R2]`
- **文件**：`backend/limitup_sti/__init__.py`
- **依赖**：无
- **改动**：从 `limitup_sti.service` re-export `_BEIJING_TZ` 为公开 `BEIJING_TZ`，加入 `__all__`。
- **验收**：`python -c "import limitup_sti as s; print(s.BEIJING_TZ)"` 不报错；`GET /api/market/sti/latest`→200。
- **备选**：`routers/sti.py` 改 `from limitup_sti.service import _BEIJING_TZ as BEIJING_TZ`（不选，re-export 更干净）。

### T2 · 修复 limitup/metrics 的 .candidates  `[R3]`
- **文件**：`backend/routers/limitup/metrics.py`
- **依赖**：无（需先读 `ScreenerResult`/`GeneScore` 定义）
- **改动**：
  1. 核对字段（已知 `qualified`/`high_gene`/`gene_scores`）与 `GeneScore` 是否有 `avg_fbt`、是否 dataclass（`.get` 对 dataclass 无效）。
  2. `:50/57/58` 的 `.candidates` → `.qualified`。
  3. 若 dataclass，`c.get("gene_score",0)`/`c.get("avg_fbt",0)` → `getattr(...)`；无 `avg_fbt` 则胜率分项置 0。
- **验收**：`GET /api/limitup/metrics`→200，返回含 `gene_distribution`/`avg_gene_score`/`backtest_win_rate`。

### T3 · scheduled-tasks /types 路由顺序  `[R4]`
- **文件**：`backend/routers/scheduled_tasks.py`
- **依赖**：无
- **改动**：`@router.get("/api/scheduled-tasks/types")` 上移到 `/{task_id}` 之前。不改路径名（保前端契约）。
- **验收**：`GET /api/scheduled-tasks/types`→200+列表；`GET /api/scheduled-tasks/1` 仍 200。

### T4 · recommendation 无数据返回 200+null  `[R7]`
- **文件**：`backend/routers/recommendation.py`
- **依赖**：无
- **改动**：`recommendation_stock` 找不到时 `return {"data": None}`+200，而非 404。
- **验收**：`GET /api/recommendation/600519`→200 `{"data": null}`。

## Phase 2 — 数据层空返回守卫（彼此独立，可并行）

### T5 · astock.disclosure 空返回守卫  `[R6]`
- **文件**：`backend/astock.py`（`disclosure`）
- **依赖**：无
- **改动**：akshare 非 list/空时返回 `[]`；`string indices must be integers` 处加类型守卫。
- **验收**：`GET /api/disclosure?code=600519`→200/501，不再 502。

### T6 · astock.kline 空返回守卫  `[R6]`
- **文件**：`backend/astock.py`（`kline`）
- **依赖**：无
- **改动**：mootdx 空元组时返回 `{"data": []}` 或抛 `DependencyMissing`→501；`not enough values to unpack` 处加空守卫。
- **验收**：`GET /api/kline?code=600519`→200/501，不再 502。

### T7 · astock.finance 空返回守卫  `[R6]`
- **文件**：`backend/astock.py`（`finance`）
- **依赖**：无
- **改动**：同 T6。
- **验收**：`GET /api/finance?code=600519`→200/501，不再 502。

## Phase 3 — kline-history 建表（有依赖）

### T8 · 核对 kline_sync 写入 schema（调研）  `[R5]`
- **文件**：读 `backend/kline_sync.py`
- **依赖**：无
- **改动**：产出 `kline` 表实际 INSERT 列清单与类型。
- **验收**：文档化列清单（以实际为准，如 `code,date,open,high,low,close,volume,amount,name`）。

### T9 · kline_history 建表初始化 + 缺表守卫  `[R5]`
- **文件**：`backend/routers/kline_history.py`（+ 必要时 `backend/kline_sync.py` 加 `init_db()`）
- **依赖**：T8
- **改动**：`_get_kline_db()` 后 `CREATE TABLE IF NOT EXISTS kline(...)`（列以 T8 为准）；catch "no such table" 返回 `{"data": [], "syncing": false}`；触发一次 `init_db()`。
- **验收**：`GET /api/kline-history/stats`、`/api/kline-history/600519`→200。

## Phase 4 — risk 事件循环阻塞（CRITICAL）

### T10 · 调研 risk_models 阻塞调用链（调研）  `[R1]`
- **文件**：读 `backend/risk_models.py`（`update_one_day_risk_realtime` 及 `_get_dragon_tiger_risk`/`_get_seat_info`/`_calculate_*`）
- **依赖**：无
- **改动**：列出 async 函数内部同步阻塞网络 I/O 调用点（astock em_get/requests）。
- **验收**：清单写入 task 备注 / S003 §5 补充。

### T11 · risk_models 阻塞 I/O 包 asyncio.to_thread  `[R1]`
- **文件**：`backend/risk_models.py`
- **依赖**：T10
- **改动**：保留同步内核，阻塞调用改 `await asyncio.to_thread(...)`；复用既有 `em_get` 限流/熔断，不放大 QPS。
- **验收**：`asyncio.run(update_one_day_risk_realtime('600519'))` 不阻塞事件循环（并发另一任务可推进）。

### T12 · routers/risk.py 并发+上限+缓存  `[R1]`
- **文件**：`backend/routers/risk.py`
- **依赖**：T11
- **改动**：dashboard `gather`+`Semaphore(8)`+`return_exceptions=True`+前 20 只+`cache_response(ttl=120)`；oneday/list 前 50 只；stock/{code} 单次 `to_thread`；seats 静态无改。
- **验收 A1**：`GET /api/risk/dashboard`≤30s→200；并发期间 `weather/pardon`、`workflow/status` 均 ≤2s→200。

### T13 · risk 异步单测  `[R1]`
- **文件**：`backend/tests/test_risk_async.py`（新建）
- **依赖**：T12
- **改动**：mock `update_one_day_risk_realtime`，验证并发、上限、缓存、不阻塞。
- **验收**：`pytest -m "not live" tests/test_risk_async.py` 全过。

## Phase 5 — 回归验收

### T14 · 全量回归
- **文件**：无
- **依赖**：T1–T13 全部完成
- **改动**：重跑 `backend/smoke_test_apis.py`（当前代码实例）；`pytest -m "not live"` 全量。
- **验收**：smoke 失败端点=0（数据源不可用降级 200/501 不计失败）；pytest 全过；S003 §6 A1–A9 ✓。

## 依赖图

```
T0(运维,独立)
T1 ─┐
T2 ─┤
T3 ─┼─→ T14
T4 ─┤
T5 ─┤
T6 ─┤
T7 ─┘
T8 → T9 ──────────────────────→ T14
T10 → T11 → T12 → T13 ─────────→ T14
```

## 规模估算
- 调研：T8、T10（读代码，无改动）
- 一文件小改：T1、T3、T4、T5、T6、T7、T9
- 中等：T2（核对数据形状）、T11、T12
- 测试：T13、T14
- 运维：T0
