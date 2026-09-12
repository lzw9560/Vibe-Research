# Spec: S190 — Scheduler 框架评估定论

> 状态：草案
> 作者：Claude（agent）  日期：2026-09-12
> 关联：RB-1（scheduler-research 定论未记）、RB-2（healthchecks.io）、RB-4（retry 接线）、RB-5（depends_on 门控）

## 1. 问题 / 目标

当前定时任务用自实现 `CronScheduler`（`cron_runner.py:22`，while + 60s ticker + cron_match，跑在 FastAPI 主事件循环）。用户之前提"优化异步任务，定时任务，调研更稳定轻量技术框架，服务解耦"——调研过但定论没落 memory 也没落 spec（RB-1）。

本 spec 目标：**给出换框架 vs 保持自实现的定论**，并落地补强项。一句话定论：**保持自实现 + 补强**，不换框架。

## 2. 背景

### 2.1 现状代码核实

| 模块 | 行数 | 职责 | 核实结论 |
|---|---|---|---|
| `cron_runner.py` | 148 | CronScheduler：60s ticker + cron_match + fire-and-forget spawn + stale run reaper | 核心逻辑清晰，已过 S150 R1/R2 timeout+reaper 修复 |
| `cron.py` | 75 | 纯函数 cron 5 段表达式匹配（支持 `*`/`*/n`/`a-b`/`a-b/n`/逗号 OR） | 自实现，无外部依赖 |
| `db.py` | 355 | SQLite 持久化：ScheduledTaskManager + WAL + busy_timeout + stale reaper + per-task_type timeout | 已有 WAL 模式 + 30s busy_timeout + stale reap（>800s） |
| `executors/__init__.py` | 364+ | TaskExecutor：dispatch dict 35 task_type → bound method，execute_async 走独占 ThreadPoolExecutor(max_workers=2) | 已有 _resolve_run_status 三态映射（success/degraded/failed）+ per-task timeout |
| `models.py` | 37 | ScheduledTask + TaskRun dataclass | 无 depends_on 字段 |
| `retry.py` | 20 | tenacity network_retry 装饰器（3 次 + 指数 backoff 2-60s + 只 retry Timeout/Connection/OSError） | **零调用方**（grep 确认：只有 retry.py 自身定义和 docstring 示例） |
| `seed.py` | 479 | 26+ 默认任务 seed（幂等 + cron 迁移） | 无 healthcheck_ping seed（S188 executor 已建但未 seed） |

### 2.2 痛点核实（代码核证据）

| 痛点 | 证据 | 严重度 |
|---|---|---|
| **单进程 ticker——进程死全 cron 停** | `cron_runner.py:73-79` `_ticker()` 挂 FastAPI 主事件循环 `create_task`；无外部心跳（S188 healthcheck_ping executor 存在但 seed.py 未 seed 该任务） | HIGH——但这是**部署层面**问题非框架问题（换 APScheduler 也一样死，因为 APScheduler 也是 in-process） |
| **无任务级重试** | `retry.py` network_retry 装饰器零调用方（grep `from scheduler.retry` 仅 retry.py 自身）；35 个 executor 无一用 retry | MEDIUM——tenacity 已装(8.5.0)，接线成本 ~5 行/executor |
| **无 depends_on 依赖门控** | grep `depends_on\|dependency` scheduler/ 零结果；当前靠 cron 时间错开（candidate 17:25 晚 limitup 15:30）——时间序脆但够用 | MEDIUM——盘后链目前 6 任务靠 cron 时序串行，无硬依赖门控 |
| **fire-and-forget 无 max concurrency** | `cron_runner.py:84` `_running_task_ids` set 去重，但 `asyncio.create_task` 无全局并发上限；TaskExecutor 有 `ThreadPoolExecutor(max_workers=2)` 限同步 executor，但异步 executor 无限 | LOW——盘中 seal_collect 每分钟 + microstructure 每 10min，实际并发 <5，未观察到问题 |
| **无 misfire 补跑** | 进程重启期间错过的 cron 不补跑（无 `misfire_grace_time` 等价物）；`start()` 只重建 `_running_task_ids` 从 DB running 行 | LOW——盘后任务用 cron 时序串行，漏跑次日数据 T+1 补算即可（forward_test_t1_settle 设计就是补 T-1 收益） |
| **SQLite 单文件并发** | WAL + busy_timeout=30s 已缓解；`_thread_pool` max_workers=2 限写并发 | LOW——单机个人项目写并发极低 |

## 3. 需求清单

- [x] R1 给出换框架 vs 保持自实现的定论（§5 方案对比 + 结论）
- [x] R2 记录定论到 spec（本文件）+ 更新 `_research_backlog.md` RB-1 状态
- [ ] R3 补 healthcheck_ping seed 任务（RB-2 落地——executor 已存在，只差 seed + cron）
- [ ] R4 retry.py 接线到 flaky executor（RB-4——kline_refresh/ofi_collect/turso_sync 3 个网络依赖型 executor）
- [ ] R5 depends_on 字段 + 依赖门控逻辑（RB-5——ScheduledTask 加 depends_on: Optional[str]，_tick 检查依赖任务 last_run_status）

## 4. 受影响文件

| 文件 | 改动 |
|---|---|
| `specs/S190-scheduler框架评估/spec.md` | 本文件（定论 + 草案） |
| `specs/_research_backlog.md` | RB-1 状态更新为"已落 spec S190，定论：保持自实现+补强" |
| `backend/scheduler/seed.py` | R3 加 healthcheck_ping seed 任务（cron `0 * * * *`，每小时 ping） |
| `backend/scheduler/retry.py` | R4 无改动（装饰器已就绪） |
| `backend/scheduler/executors/data_ops.py` | R4 kline_refresh + monthly_vacuum 函数加 `@network_retry` |
| `backend/scheduler/executors/intraday.py` | R4 ofi_collect 函数加 `@network_retry` |
| `backend/scheduler/executors/limitup.py` | R4 turso_sync 如走 limitup 模块则同上（实际 turso_sync 在 `data/turso_sync.py`，R4 接线在那里） |
| `backend/scheduler/models.py` | R5 ScheduledTask 加 `depends_on: Optional[str] = None`（依赖任务 name） |
| `backend/scheduler/db.py` | R5 `scheduled_tasks` 表加 `depends_on TEXT DEFAULT NULL` 列（ALTER TABLE 迁移）+ `_tick` 依赖检查 SQL |
| `backend/scheduler/cron_runner.py` | R5 `_tick` 加依赖门控：`depends_on` 非空时查依赖任务 `last_run_status`，非 success/degraded 则跳过 + log |
| `backend/scheduler/seed.py` | R5 给盘后链任务加 depends_on（candidate_funnel_precompute depends_on=limitup_precompute 等） |

## 5. 设计方案

### 5.1 框架对比（核证据）

| 维度 | APScheduler | arq | dramatiq | celery | **自实现+补强** |
|---|---|---|---|---|---|
| 进程模型 | in-process（同 FastAPI） | 独立 worker 进程 + Redis | 独立 worker 进程 + Redis/RabbitMQ | 独立 worker 进程 + Redis/RabbitMQ | in-process（同 FastAPI） |
| 进程死防护 | 无（同自实现） | 有（worker 独立） | 有 | 有 | 无（靠 healthcheck.io 告警 + 手动重启） |
| 新依赖 | apscheduler（纯 Python） | redis + arq | redis/rabbitmq + dramatiq | redis/rabbitmq + celery + flower | **零新依赖** |
| 基础设施 | 无 | **需 Redis** | **需 Redis/RabbitMQ** | **需 Redis/RabbitMQ** | 无 |
| 接入成本 | 替换 CronScheduler ~148 行 + 适配 35 task_type + 迁移 SQLite 持久化 | 新建 worker 进程 + 改 executor 为 arq task + Redis 部署 | 同 arq 量级 | 最高 | ~100-200 行增量改动 |
| misfire 处理 | 有（coalesce/misfire_grace_time） | 无（需自建） | 无 | 有（celery beat） | **自建 ~20 行**（log 错过任务 + 可选补跑） |
| 任务级 retry | 无（需自建或配 tenacity） | 有 | 有 | 有 | **接线已有 tenacity**（~5 行/executor） |
| 依赖门控 | 无 | 无 | 无 | chain/group | **自建 ~50 行**（depends_on 字段 + _tick 门控） |
| KISS/YAGNI 对齐 | 替换已有可用代码，边际收益低 | 引入 Redis 基础设施，个人 Mac 过重 | 同 arq | 明确过重 | **最对齐** |

### 5.2 结论：保持自实现 + 补强

**理由链**：

1. **进程死问题不是框架问题**——APScheduler 也是 in-process，进程死了一样全停。真正解决进程死的是"独立 worker 进程"（arq/dramatiq/celery），但它们都需要 Redis/RabbitMQ。个人 Mac 单机引入 Redis 做定时任务调度是杀鸡用牛刀。解法是 **healthchecks.io 外部心跳告警 + 手动重启**（RB-2，S188 executor 已存在，只差 seed）。

2. **当前自实现已有关键能力**——cron 匹配（75 行纯函数）、SQLite 持久化（WAL+busy_timeout）、stale run reaper（>800s 清理）、per-task_type timeout（120-1200s）、三态状态映射（success/degraded/failed）、通知系统（飞书多点通知）、独占线程池隔离。这些是 APScheduler 也需要自己适配的。

3. **APScheduler 唯一增量价值是 misfire 处理**（coalesce + misfire_grace_time），但这在当前场景不痛——盘后任务漏跑次日 T+1 补算（forward_test_t1_settle 设计就是补 T-1），不是关键缺口。

4. **真正的痛点是 3 个缺失特性**，都能在自实现框架内补：
   - RB-2 healthcheck 外部心跳（executor 已建，~10 行 seed）
   - RB-4 retry 接线（tenacity 已装，~15 行装饰器接线）
   - RB-5 depends_on 依赖门控（~50-100 行字段+SQL+_tick 门控）

5. **north-star 对齐**：项目 north-star 是"经得起长期验证的投研项目"。调度器是基础设施——应该无聊、可靠、完全理解。自实现 148 行核心逻辑全可读可审计；引入框架意味着多一层不控的依赖。

### 5.3 不选 APScheduler 的关键理由

APScheduler 是候选中最合理的（in-process、纯 Python、无 Redis），但：

- 当前 `cron.py` 75 行 cron 匹配已覆盖项目所需（`*`/`*/n`/`a-b`/`a-b/n`/逗号 OR），APScheduler 用标准 cron 库但行为一致
- 当前 `db.py` SQLite 持久化 + WAL + stale reaper 已超出 APScheduler `SQLAlchemyJobStore` 的能力
- 当前 `executors/__init__.py` 35 task_type dispatch + 三态状态映射 + 通知系统需要适配层，不是零成本替换
- 替换 148 行已审计代码为 APScheduler 适配代码（~100 行），净收益仅 misfire 处理——可自建 20 行

**如果将来需要**：进程级隔离（worker 独立运行、API 只 enqueue），那时再评估 arq。当前无此需求（YAGNI）。

### 5.4 补强方案（R3-R5）

**R3 healthcheck_ping seed（~10 行）**：
```python
# seed.py 加：
if "healthcheck_ping" not in existing:
    _manager.create_task(ScheduledTask(
        name="healthcheck_ping",
        description="S188 RB-2 外部心跳（healthchecks.io，进程死则 ping 停→邮件告警）",
        task_type="healthcheck_ping",
        cron_expr="0 * * * *",  # 每小时整点
        payload={},
        enabled=True,
    ))
```

**R4 retry 接线（~15 行）**：
```python
# data_ops.py kline_refresh：
from scheduler.retry import network_retry

@network_retry  # 3 次 + 指数 backoff，只 retry Timeout/Connection/OSError
def kline_refresh(payload): ...

# intraday.py ofi_collect：
@network_retry
def ofi_collect(payload): ...
```

**R5 depends_on 门控（~80 行）**：
```python
# models.py：
@dataclass
class ScheduledTask:
    ...
    depends_on: Optional[str] = None  # 依赖任务的 name

# db.py 迁移：
ALTER TABLE scheduled_tasks ADD COLUMN depends_on TEXT DEFAULT NULL;

# cron_runner.py _tick 门控：
def _check_dependency(self, task: ScheduledTask) -> bool:
    if not task.depends_on:
        return True
    dep = _manager.get_task_by_name(task.depends_on)
    if dep is None:
        return True  # 依赖任务不存在，不阻塞
    if dep.last_run_status in ("success", "degraded"):
        return True
    return False  # 依赖未完成或失败，跳过

# seed.py 盘后链加 depends_on：
candidate_funnel_precompute → depends_on="limitup_precompute"
derived_precompute → depends_on="limitup_precompute"
first_board_t1_review → depends_on="first_board_filter"
# 等
```

## 6. 验收标准

- [ ] A1 RB-1 定论落 spec（本文件）——已完成
- [ ] A2 `_research_backlog.md` RB-1 状态更新为"已落 spec S190"
- [ ] A3 R3 healthcheck_ping seed 任务创建后 `pytest -m "not live"` 全绿
- [ ] A4 R4 retry 装饰器接线后，kline_refresh/ofi_collect 函数有 `@network_retry`，测试 mock 网络失败验证 3 次重试
- [ ] A5 R5 depends_on 字段 + 迁移 + _tick 门控后，盘后链任务有 depends_on，依赖未完成时 _tick 跳过 + log
- [ ] A6 涉及数据的：无新数据输出，不涉及 financial_rigor 验算

## 7. 合规与工程底线自查（逐条确认）

- [x] 研判/推荐/买卖时机：本 spec 是调度器基础设施评估，不涉及交易信号/买卖时机
- [x] 判断可复现：框架对比基于代码 grep 核实（行数/调用方/依赖），非臆造
- [x] 用户私有数据：不涉及私有数据（.vibe-research/ 路径未改）
- [x] 新增东财端点：不涉及 em_get 新端点
- [x] 弱合规（§1.1）：调度器是内部基础设施，不产生用户可见输出，无合规风险

## 8. 测试计划

- `pytest -m "not live" --deselect backend/tests/test_s032_workflow_state.py::test_s032_refresh_loop backend/tests/test_s040_backfill.py::test_s040_backfill backend/tests/test_newsradar.py::test_fetch_global_intel_wm_import_fails`（跳过已知 flaky 3 项）
- R3：healthcheck_ping seed 后 `GET /api/scheduler/tasks` 确认任务存在
- R4：mock `httpx.get` 返 ConnectionError，验证 kline_refresh 重试 3 次后 reraise
- R5：seed 盘后链 depends_on 后，mock limitup_precompute last_run_status="running"，验证 candidate_funnel_precompute 被 _tick 跳过

## 9. 风险与回滚

| 风险 | 影响 | 回滚 |
|---|---|---|
| R5 ALTER TABLE 加列 | scheduled_tasks 表加 depends_on 列，旧任务 NULL（不影响） | DROP COLUMN（SQLite 3.35+） |
| R4 retry 接线致 executor 变慢 | kline_refresh 原 1 次失败即返，改后最多 3+backoff≈60s+ | 移除 @network_retry 装饰器 |
| R3 healthcheck_ping 每小时出站请求 | 健康检查流量极小（1 ping/h），healthchecks.io 免费层 20 checks | disable 任务 |

## 10. 定论记录（给 RB-1 补 memory）

**定论**：保持自实现 CronScheduler + 补强（healthcheck seed / retry 接线 / depends_on 门控），不换框架。

**核心依据**：
1. 进程死问题不是框架问题（APScheduler 也 in-process 也死）——解法是 healthchecks.io 外部心跳，不是换框架
2. 引入 Redis/RabbitMQ（arq/dramatiq/celery）对个人 Mac 单机项目过重（YAGNI）
3. APScheduler 唯一增量价值（misfire 处理）在当前场景不痛——盘后任务漏跑次日 T+1 补算
4. 3 个真实痛点都能在自实现内补（~100-200 行），零新依赖
5. north-star 对齐：调度器应无聊可审计，148 行自实现全可读
