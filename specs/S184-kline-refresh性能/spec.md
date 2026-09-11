# Spec: S184 — kline_refresh 性能优化（全量 timeout → 限制 universe + 增量）

> 状态：草案
> 作者：Claude（agent）  日期：2026-09-11
> 关联：S175 bars_provider A 股 baostock fallback（commit 0ac0779，已缓解 cache miss）/ S090 kline_refresh（原 spec，全量 baostock 拉）/ S183 胜率曲线（breakout unbuyable 根因之一）/ memory `etf-daily-source-single-point`（ETF 当日源单点同款数据裂缝）

## 1. 问题 / 目标

kline_refresh 全量 5540 股 baostock 拉 timeout（1200s，09-10 failed）→ `baostock_kline_cache.json` 不写当日 bar → breakout T1OpenFill `no_entry_bar` → 全 unbuyable → S183 曲线空。

一句话：kline_refresh 从"全量 5540 股拉"改为"限制 universe ~200 活跃股 + 增量当日 bar"，让 cron 16:30 在 timeout 内写当日 cache。

## 2. 背景

- **现状（S183 重启验证核实）**：`backend/tools/refresh_kline_cache.py` main()：`load_industry_map()` 全 A ~5540 股（`baostock_industry.json` 24h cache 已就绪，不卡）+ 循环 `fetch_daily_bars` 每股 1-2s = 90-180min >> 1200s timeout。09-10 run failed timeout，cache 只到 09-09（164MB 5226 key，缺 09-10/09-11）。
- **已缓解（不重复修）**：`bars_provider._baostock_a_share_hist`（commit 0ac0779）A 股 cache miss → baostock 实时拉候选股 ~50-100，breakout 不依赖全量 cache。但 kline_refresh cron 仍 timeout 不写当日 cache，影响 funnel/scanner（读全量 cache）。
- **baostock 特性**：单 session（`bs.login()` 全局），不支持真正并行；query 每股 1-2s（login overhead + 网络）；不封 IP（vs 东财 push2delay）。
- **数据消费方**：`KlineCacheBarsProvider.__call__` A 股读 cache（miss 走 baostock fallback）；funnel/scanner 读全量 cache（first_board_filter/limitup_precompute 等要全 A）。限制 universe 影响这些消费方。

## 3. 需求清单

- [ ] R1：kline_refresh universe 从全 A 5540 限制为"活跃股子集"——涨停股池（zt_pool ~50-100）+ 持仓（floor/breakout/trend 持仓）+ watchlist + 候选池，~200 股。可配置 `KLINE_REFRESH_UNIVERSE`（"active" 子集 / "full" 全量回退）
- [ ] R2：增量拉——只拉 cache 缺的当日 bar（`start=cache 最后 bar 后 +1` / `end=今日`），非全量重拉。每股 query 仍 1-2s 但只拉 1 bar（非全量历史）
- [ ] R3：timeout 拉长 + cron 提前——cron 16:30（原）保持，timeout 1200s→1800s（200 股 × 1-2s + buffer）。active 子集 ~200 股 × 2s = 6min << 1800s
- [ ] R4：cache 语义变更文档化——`baostock_kline_cache.json` 从"全 A"改为"活跃股子集"（当日涨停 + 持仓 + watchlist）。funnel/scanner 全 A 需求改走 baostock 实时 fallback（`_baostock_a_share_hist`）或单独全量回填任务（`backfill` 周末跑）
- [ ] R5：监控 + 降级——kline_refresh failed 时 `bars_provider` baostock fallback 兜底（已有，确认接线）。加 `kline_refresh_status` 字段（last_success_date / last_n_codes / last_duration）供前端诚实呈现 cache 时效

## 4. 受影响文件

| 文件 | 改动 |
|---|---|
| `backend/tools/refresh_kline_cache.py` | main() 加 `universe="active"` 参数（默认）+ 增量拉逻辑（start=cache last+1）+ 活跃股子集构建（zt_pool + 持仓 + watchlist） |
| `backend/scheduler/executors/data_ops.py` | kline_refresh executor 传 `universe` payload + timeout 1800s（executor 层） |
| `backend/scheduler/seed.py` | kline_refresh cron 注释改（universe active + timeout 1800s） |
| `backend/engine/bars_provider.py` | cache miss baostock fallback 已有（0ac0779），确认 `_load_cache` 损坏降级 + fallback 接线（无新改） |
| `backend/routers/health.py` 或 journal.py | 加 `kline_refresh_status` 诚实呈现（cache 时效 + last_success） |
| `backend/tests/test_s090_kline_refresh.py` | 加 active universe + 增量拉单测 |

## 5. 设计方案

### 5.1 限制 universe + 增量（选此，方案 2+1 结合）

**universe 构建**（R1）：
- 涨停股池：`ths_limit_up_pool` / `em_zt_topic_pool` 当日 ~50-100 股
- 持仓：`trade_journal` arm=floor/breakout/trend 的 stock_code ~10-20
- watchlist：`watchlist` 表 ~20-50
- 候选池：`candidate_funnel` 当日 candidates ~20-50
- 合并去重 ~100-200 股，`KLINE_REFRESH_UNIVERSE=active`（默认）

**增量拉**（R2）：`start_date = cache[code] 最后 bar.date + 1` / `end_date = 今日`。每股只拉 1-2 bar（当日 + 补缺），非全量历史。baostock query 每股仍 1-2s（login overhead），但 200 股 × 2s = 6min。

**选此理由**：200 股 × 2s = 6min << 1200s timeout。解决 timeout。baostock 不封 IP。复用现有 `_baostock_a_share_hist` 模式（fetch_daily_bars）。

### 5.2 备选为何不选

- **方案 1 纯增量（全量 5540 + 只拉当日 bar）**：5540 × 1-2s = 90-180min 仍 timeout（每股 query login overhead 不因 bar 数减少）。不解决性能。
- **方案 3 并行（线程池 + 多 baostock session）**：baostock `bs.login()` 全局单 session，不支持真正并行（多 session 可能限流/封）。复杂 + 风险。不选。
- **方案 4 timeout 拉长（1800s + 全量）**：全量 5540 × 2s = 180min >> 1800s。治标不解决。不选。
- **akshare 东财**：IP 封（memory `em_get 防封`）。不选。
- **tencent qt.gtimg 日 K**：待验证支持 + 字段格式。探索性，非本 spec。

### 5.3 cache 语义变更影响（R4）

`baostock_kline_cache.json` 从"全 A 5226 key"变为"活跃股子集 ~200 key"。
- **breakout/floor/trend**：读 cache（active 子集）+ cache miss 走 baostock fallback（0ac0779）——不受影响（候选股在 active 子集或 fallback）。
- **funnel/scanner（全 A 需求）**：first_board_filter/limitup_precompute 等要全 A bars——改走 baostock 实时 fallback（每股 1-2s，~50 股候选可接受），或周末 `backfill` 全量回填任务（非 cron）。
- **文档**：cache 文件注释 + 前端诚实呈现"cache 为活跃股子集，全 A 走实时 baostock"。

### 5.4 监控 + 降级（R5）

- `kline_refresh_status` 表或字段：`last_success_date / last_n_codes / last_duration / last_error`
- 前端 health/cockpit 呈现"cache 时效：last_success 09-10 16:52（active 200 股，5min）"
- failed 时 `bars_provider` baostock fallback 兜底（确认接线，已有）

## 6. 验收标准

- [ ] A1：kline_refresh `universe=active` 拉活跃股子集 ~200 股 + 增量当日 bar，duration < 600s（10min）<< 1200s timeout
- [ ] A2：`baostock_kline_cache.json` 含当日 bar（2026-09-11 16:30 后写 09-11 bar）
- [ ] A3：kline_refresh cron 16:30 跑不 timeout（scheduled_task_runs status=success）
- [ ] A4：funnel/scanner 全 A 需求走 baostock 实时 fallback（cache miss 不崩，降级返空 + fallback）
- [ ] A5：`kline_refresh_status` 前端诚实呈现 cache 时效（last_success / n_codes / duration）
- [ ] A6：test_s090 加 active universe + 增量拉单测 + 全量回归无破坏（`universe=full` 回退兼容）

## 7. 合规与工程底线自查

- [x] 不臆造：baostock fetch_daily_bars 实测能拉（600108 8 bars 含 09-10），性能数据基于实测（每股 1-2s × 200 = 6min）
- [x] 私有数据：baostock_kline_cache.json 在 `.vibe-research/`（VR_DATA_DIR），不进 git
- [x] 不涉 em_get：baostock 不封 IP（vs 东财 push2delay）
- [x] 工程底线：cache miss 走重算/实时 fallback（S088 范式，不读结果 cache）；诚实呈现 cache 时效（R5 监控）
- [x] DRY：复用 `_baostock_a_share_hist` 模式（fetch_daily_bars），不新建 baostock 拉取函数

## 8. 测试计划

- **active universe + 增量拉单测**（test_s090 扩）：mock load_active_universe 返 ~50 股 + mock fetch_daily_bars，验证 main(universe="active") 拉当日 bar + duration < timeout + cache 写当日
- **全量回退兼容**（test_s090）：`universe=full` 仍能跑（全 A 5540，但 timeout 标记，不阻塞）
- **cache miss fallback 集成**（test_bars_provider）：active 子集 cache miss → baostock fallback（已有 0ac0779，确认不破）
- **kline_refresh_status** 单测：failed 时 status 字段诚实标 error + last_success
- **集成**：cron 16:30 跑 → cache 写当日 bar → breakout T1OpenFill 有次日 bar → buyable（手动冒烟）

## 9. 后续可选（非本 spec）

- 周末 `backfill` 全量回填任务（全 A 5540 股历史 bar，非 cron，手动/周更）
- tencent qt.gtimg 日 K 多源 fallback（待验证字段格式 + A 股支持）
- baostock session 池并行（如果 baostock 支持多 session，探索性）
