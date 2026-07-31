# 决策记录（Decision Log）

> 记录 Vibe-Research 项目中关键技术/架构决策。每条含：选择、理由、应用方式、被否决方案、日期、状态。
> 编号 DEC-NNN 递增。新增决策追加到文件末尾。

---

## DEC-001：S004 候选池漏斗性能优化技术路线

**选择：** 采用「漏斗级缓存 + 盘后预计算 + top-N 限界 + 独立 source 并行」组合方案优化 `run_funnel` 性能；**不**对 `fund_flow`/`catalyst` 做逐只并发。

**Why：** `astock.em_get` 有全局串行限流锁（QPS≤2）。`fund_flow` 逐只调用都走 em_get（每只 ~2s × ~100 只 ≈ 200s，为 >60s 主因）；逐只并行在锁约束下退化为串行，**无收益**且并发请求放大东财封 IP 风险。故性能杠杆排序为：缓存+预计算（主杠杆，把 ~200s 冷算挪到盘后离线，请求侧恒 ≤1s）> top-N 限界（r1_kept ~100→≤80，降预计算墙钟且封顶）> 独立 source 并行（仅对非 em_get 串行的 gene/board/auction 有真收益）。

**How to apply：**
- 按优先级实现 `specs/S004-candidates-funnel-performance/tasks.md`：B1 限界（`CANDIDATE_FUNNEL_MAX_R2` 默认 80）→ B2 缓存（`_FUNNEL_CACHE` TTL 300s + 路由 `@cache_response` 60→300）→ C1 并行（独立组 A 用 `ThreadPoolExecutor(4)`）→ D1 预计算（`TaskExecutor._executors["candidate_funnel_precompute"]`）→ E1/E2 验收。
- 复用各 source 既有 `em_get` 限流路径，**不裸调**东财（合规红线）。
- 回滚：恢复顺序 `run_funnel`、删预计算任务、TTL 回 60。

**被否决的方案：**
1. **fund_flow 逐只并发**：em_get 全局锁使并发退化为串行，反而放大封 IP 风险，收益为负。
2. **`run_funnel` 改 async 逐 source `to_thread`**：改动面大，source 内部仍串行 em_get，收益不如缓存+预计算；且 S003 已在路由层做 `asyncio.to_thread`，重复。

**日期：** 2026-07-29

**状态：** 已采纳（S004 spec 仍为草案，待用户审批后进入 TDD 实现）
