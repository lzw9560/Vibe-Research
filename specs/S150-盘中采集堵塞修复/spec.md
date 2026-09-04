# Spec: S150 — 盘中采集 stale-run 堵塞修复

> 状态：待实现
> 作者：Claude  日期：2026-09-04
> 关联：S070（intraday 采集管道）、S145（§44 path）、记忆 scheduler-stuck-runs-block-cron

## 1. 问题 / 目标

seal_intraday 采集 task（task 5）因 stale 'running' run 挂死堵 dedup，导致盘中数据只 4 交易日（08-13/14/17+09-04），离 §44 验证 30 天窗口差 26 天，盘中 edge 验证（S153 量化模型阶段2）无法启动。

**根因（fork 调查，只读未改）**：
- B 代码级（主因）：`_execute_seal_intraday_collect`（scheduled_tasks.py:840）无 `asyncio.wait_for` 超时，em_get（em_zt_topic_pool）网络挂顿 → collect_once 永挂 → run status='running' 无 finished_at → 进 `_running_task_ids`（line 2163）→ ticker dedup（line 2218 `task.id not in _running_task_ids`=False）→ task 5 永不触发。重启时 line 2180 从 count_running 重建 `_running_task_ids` 把 stale run 重新加回 → **重启也救不了**（和记忆 scheduler-stuck-runs-block-cron 完全一致）。全表无 stuck-run reaper，挂死 run 永不自愈。
- A 环境（已澄清）：服务常开，非 dev 不连续问题。8-17→09-04 的 18 天空白系反复 stale 堵的历史累积（run 记录被 scheduled_tasks.py:214 DELETE 清理，但 seal_intraday_snapshots 只 4 天是事实）。

**目标**：collect_once 超时不永挂 + run reaper 自愈 stale run + 项目级 task 5 注册确认（服务常开即跑，不需 launchd）。

## 2. 需求清单

- [ ] R1 `_execute_seal_intraday_collect` 包 `asyncio.wait_for(..., timeout=120)`（对齐 `_precompute_async` line 652 范式），超时标 failed 不永挂。timeout 不破坏 em_get 内部节流（em_get 的 sleep/熔断在 collect_once 内部，wait_for 只兜外层挂顿）。
- [ ] R2 run reaper：ticker 每轮查 status='running' 且 started_at 超 N 分钟（默认 10min）的 run → 标 failed + `_running_task_ids.discard(task_id)`（根因 B 真修，防下次 em_get 挂又堵死）。
- [ ] R3 确认项目级 seal intraday task（task 5）注册正常（TaskExecutor._executors 有 seal 方法 + cron 触发频率 + 服务常开即跑，不需 launchd plist）。
- [ ] R4 测试：模拟 collect_once 挂死 → 120s timeout 标 failed；模拟 stale run → reaper 清；task 5 不被永堵。

## 3. 受影响文件

| 文件 | 改动 |
|---|---|
| `backend/scheduled_tasks.py` | R1：`_execute_seal_intraday_collect`（~line 840）包 `asyncio.wait_for(timeout=120)`；R2：ticker 加 run reaper（查 running 超 N 分钟 → failed + `_running_task_ids.discard`）；R3：确认 task 5 注册 |
| `backend/tests/test_s150_intraday_collect_timeout.py`（新） | R4：collect 挂死 timeout + reaper 清 stale + task 5 不永堵 |

## 4. 验收标准

- [ ] A1 collect_once 挂死 → 120s timeout 标 failed（不永挂，run 有 finished_at）
- [ ] A2 stale running run 超 10min → reaper 标 failed + discard（task 5 可再触发）
- [ ] A3 重启 :8900 后 `_running_task_ids` 不含 stale（reaper + timeout 双保险，不依赖手动清 SQL）
- [ ] A4 task 5 交易时段正常写 seal_intraday_snapshots（次日盘后验证多一天 distinct date）
- [ ] A5 pytest 全绿（deselect newsradar_global_intel/s032/s040 flaky）

## 5. 合规与工程底线自查

- [x] 不臆造：timeout/reaper 是工程修复，不造数据；stale run 标 failed 如实（不伪造 success）
- [x] 私有数据隔离：scheduled_task_runs 是项目 DB（backend/data/market_data.db），非用户私有
- [x] em_get 防封：wait_for 只兜外层挂顿，不破坏 em_get 内部节流/熔断（collect_once 内部仍走 em_get 限流）；timeout 标 failed 不重试轰炸端点

## 6. 测试计划

- 单元：collect_once 挂死（mock em_get 慢）→ timeout 触发标 failed；stale run reaper 清；task 5 不被永堵
- 集成：重启重建 `_running_task_ids` 不含 stale（reaper + timeout 双保险）
- 离线：`pytest -m "not live" --deselect tests/test_newsradar_global_intel.py --deselect tests/test_s032_refresh_loop.py --deselect "tests/test_s040_backfill.py::test_run_backtest_async_passes_kline_cache"`

## 7. 风险与回滚

**审查 workflow（12 agent adversarial verify）发现 + 修（2026-09-04）**：
- **HIGH1（线程泄漏+IP封禁+API冻结）**：`asyncio.to_thread` 线程在 `wait_for` 超时后不可取消（Python ThreadPoolExecutor 不支持中断运行中线程）→ 孤儿线程并发 em_get（rate limiter TOCTOU gap，锁在 sleep 前释放+时间戳 finally 才更新）→ 两线程跳过限流直发东财 → **IP 封禁**（违 §1.2 防封底线）；累积泄漏填满默认池（max_workers=8，71 调用方共享含 API 路由）→ **系统性 API 冻结**。**已修**：调度器独占 `ThreadPoolExecutor(max_workers=2, thread_name_prefix="scheduler")` + `run_in_executor` 替代 `asyncio.to_thread`，隔离泄漏（调度器线程全挂也不冻 API 路由）。
- **HIGH2（kline_refresh 误杀回归）**：默认 300s < kline_refresh 全A~5540股 baostock 稳态 554s → R1 半途标 failed → baostock_kline_cache 当日新 bar 只 append 一部分 → 次日 premarket breakout 数据源缺当日 bar。**S150 直接引入的回归**。**已修**：`_TASK_TIMEOUTS["kline_refresh"]=1200` + `_REAPER_STALE_SECONDS=1300`（>1200 防 reaper 误杀）。
- **HIGH3（sync handler 孤儿线程重复写库 + _DB_LOCK 死锁）**：**未根治**——独占 executor 隔离了 API 冻结（HIGH1），但孤儿线程仍跑完写库：`INSERT OR REPLACE` 表（seal_derived_features/intraday_features）用陈旧派生覆盖新数据；`bomb_alert_history`（plain INSERT）重复告警行；若 R1 在线程持 `_DB_LOCK` 瞬间超时（DB 写 hang）→ `_DB_LOCK` 被泄漏死线程永久持有 → 后续 collect_once 永久阻塞 `acquire()` → 盘中采集瘫痪。**标注风险，长期根治**：`collect_once` 改 `subprocess.run(timeout=120)`（子进程可 kill，根治孤儿+死锁）或改 async（httpx.AsyncClient，`wait_for` 可 cancel 协程）。
- **证伪（非 bug）**：时区——started_at 与 cutoff 均 naive `datetime.now().isoformat()`，格式一致比较正确（solo 审 + adversarial 一致）。
- **R2 reaper 对线程泄漏零作用**：R1 已把 run 标 failed，reaper `WHERE status='running'` 查不到——"R1+R2 双保险"对 sync handler 线程泄漏场景不成立，reaper 只兜 R1 timeout 从未触发的进程暴死。

**原风险（保留）**：timeout 误杀正常 collect（盘中应<60s，120s 兜底）→ 可调 config；reaper 误杀长 task（1300s > max 1200）→ 可调；回滚：timeout/reaper/独占池加 config flag（默认开）可关。
