# S248 · depends_on 门控宽限重试

**状态**：实现中
**日期**：2026-11-12
**分级**：medium（scheduler 核心逻辑改动 + TDD）

## 问题

depends_on 门控是"单发精确分钟"设计——下游任务在其 cron 分钟仅有一次匹配 tick（`cron_match` 只匹配精确分钟 `dt.minute==25`），上游此刻仍 running 则当日永久跳过无重试无补跑无告警。

**实证（2026-11-11）**：kline_refresh 11-11 跑 70 分钟（17:15:16→18:25:59，平日 3 分钟），candidate_funnel_precompute 17:25 tick 时 kline_refresh 仍 running → `dependency_satisfied` 返 False → 跳过 → 链断（candidate_funnel_precompute → trade_journal_daily → daily_full_pull 全 skip，当日 0 run）。任何 depends_on 链只要上游运行时间 > cron 偏移即复现。

## 需求

`_should_run` 改造：cron_match 通过但 depends_on 未满足时加入 `_pending_retry`（窗口 = max_dep_timeout + 300s 自适应上游 timeout），后续 tick dep 满足时补 fire（覆盖上游 overrun）。窗口过期放弃。

## 受影响

- `backend/scheduler/cron_runner.py`（_should_run 改造 + `_pending_retry` 字段 + helper）
- `backend/tests/test_cron_dep_retry.py`（新建，TDD）

## 验收

- [ ] dep running 时下游 cron 命中不 fire + 加入 _pending_retry
- [ ] dep 满足后下游在窗口内补 fire（即使 cron 不再匹配）
- [ ] 窗口过期后下游不 fire + 清 _pending_retry
- [ ] 无 depends_on 任务不受影响（现有 test_cron_should_run 绿）
- [ ] dep 满足时正常 fire（不进 _pending_retry）
- [ ] _run_task 完成后清 _pending_retry（防已 fire 残留）
- [ ] pytest -k "scheduler or cron or depends" 全绿

## 合规自查

工程底线：不臆造（基于 11-11 scheduled_task_runs 实证根因）/ 私有数据隔离（不碰）/ 防封（不碰）。
