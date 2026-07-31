# 技术方案 · S004 候选池漏斗性能优化

> 对应 spec：`spec.md`（草案）
> 性质：文件/函数级技术方案，受 `CLAUDE.md` §0 SDD 约束。
> 作者：Claude ｜日期：2026-07-29

## 0. 调研结论（R1：各 source 耗时与瓶颈）

读 `candidate_funnel/sources/*.py` + `funnel.py`：

| source | 调用 | 每只耗时 | 规模 | 小计 | 备注 |
|---|---|---|---|---|---|
| `gene.fetch_genes` | ThreadPool(max_workers=1)，实质顺序 | 视实现 | 全市场涨停股 | 中 | 取基因得分 |
| `board_ladder.fetch_board_ladder` | 单次 | — | 1 | 小 | 连板梯队 |
| `activity.fetch_activity(r1_kept)` | **分批 50**，`astock.tencent_quote(batch)` | 批量，不走 em_get | r1_kept/50 批 | 小 | 已高效 |
| `fund_flow.fetch_fund_flow(r1_kept)` | **逐只** `astock.stock_fund_flow_120d(c)` + `astock.dragon_tiger_board(c)` | ~2s/只（em_get×2） | r1_kept ≈ 100 | **~200s** | **>60s 主因** |
| `auction.fetch_auction` | 单次（date） | — | 1 | 小 | 竞价 |
| `catalyst.fetch_catalyst(r2_kept)` | **逐只** `astock.announcements(c)` + `astock.concept_blocks(c)` | ~2s/只 | r2_kept | 中 | R3 收敛后量减 |

**关键约束**：`astock.em_get` 有全局串行锁（QPS≤2）。`fund_flow` 逐只调用都走 em_get → **逐只并行无收益**（锁串行化），且并发请求放大封 IP 风险。故性能杠杆排序：

1. **缓存 + 预计算**（主杠杆）：把 ~200s 的冷算挪到盘后离线，请求侧恒命中 ≤1s。
2. **top-N 限界**：r1_kept 从 ~100 降到 ≤80，预计算墙钟↓20% 且封顶。
3. **独立 source 并行**：仅对互不依赖且**非 em_get 串行**的 source（gene/board/auction）有真收益；fund_flow 逐只并行**不做**。

## 1. 复用清单（不重造）

| 需求 | 复用现有能力 |
|---|---|
| 漏斗级 TTL 缓存 | 仿 `routers/risk.py` 的 `_DASHBOARD_CACHE` 模式（本地 dict + time） |
| 路由级缓存 | `app.cache_response(ttl)` |
| 限流/熔断 | `astock.em_get`、`circuit_breaker.get_breaker("eastmoney")` |
| 并发 | `concurrent.futures.ThreadPoolExecutor`（同步 source） |
| 定时任务 | `scheduled_tasks.TaskExecutor._executors`（6 种既有，加第 7 种） |
| 配置 | `config.AssistantDefaultConfig`（加 `CANDIDATE_FUNNEL_MAX_R2`） |

## 2. 设计方案

### 2.1 R3 限界（`funnel.py` + `config.py`）
- `run_funnel` R1 后、R2 前：`r1_kept = top_n_by_gene_score(r1_kept, genes, MAX_R2)`。
- `MAX_R2` 默认 80，`AssistantDefaultConfig.CANDIDATE_FUNNEL_MAX_R2` + env `VR_CANDIDATE_FUNNEL_MAX_R2`。
- top-N 取 `genes[c]["gene_score"]` 既有排序，**不引入新排序口径**（合规）。

### 2.2 R4 缓存（`funnel.py` + `routers/candidates.py`）
- `funnel.py` 模块级 `_FUNNEL_CACHE: dict[str, tuple[float, FunnelResult]]`，TTL 300s。
- key = `f"{date}:{stage}:{hash(tuple(sorted(cfg.model_dump().items())))}"`。
- `run_funnel` 首查命中直返；末尾 `_FUNNEL_CACHE[key] = (now, result)`。
- `routers/candidates.py` 路由 `@cache_response(ttl=60)` → `ttl=300`。
- 大小限制：>1024 项时清半（仿 `app._RESPONSE_CACHE`）。

### 2.3 R2 并行（`funnel.py`）
- 独立组 A（R1 前）：`gene.fetch_genes` / `board_ladder.fetch_board_ladder` / `auction.fetch_auction` → `ThreadPoolExecutor(max_workers=4)` 并行。
- 依赖组 B（R1 后）：`activity.fetch_activity(r1_kept)` 与 `fund_flow.fetch_fund_flow(r1_kept)` 并行（均 em_get，锁串行但 Σ→max，仍有收益）。
- **不做**：fund_flow/catalyst 内部逐只并行（em_get 锁串行，无收益+封 IP 风险）。

### 2.4 R5 预计算（`scheduled_tasks.py`）
- `TaskExecutor._executors["candidate_funnel_precompute"]`：`funnel_mod.run_funnel("all", today, default_config)` 预热缓存；失败 catch、记 run 失败、不抛。
- `/api/scheduled-tasks/types` 追加 `candidate_funnel_precompute`。
- 推荐 cron `0 16 * * 1-5`（盘后 16:00），由用户建任务时定。

## 3. 取舍与备选

- **不选**：把 `run_funnel` 改 async 逐 source `to_thread`——改动面大，source 内部仍串行 em_get，收益不如缓存+预计算；且 S003 已在路由层 to_thread，重复。
- **不选**：fund_flow 逐只并发——em_get 全局锁使并发退化为串行，反而放大封 IP 风险。
- T3 若实测因 em_get 锁收益不足，降级为仅并行独立组 A，仍满足验收（缓存+预计算兜底）。
