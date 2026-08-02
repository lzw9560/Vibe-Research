# Spec: S022 — 熔断器 health 读路径修复（尊重 recovery_timeout）

> 状态：草案
> 作者：Claude  日期：2026-08-02
> 关联：`reports/system-check-2026-08-02.md`（体检报告 🔴 circuit_breaker_open）、`../../backend/routers/health.py`、`../../backend/circuit_breaker.py`、CLAUDE.md §3（熔断器）

## 1. 问题 / 目标
体检报告（2026-08-02）🔴：`GET /api/health` 返 `ok=false`，`checks.circuit_breaker.ok=false / detail=circuit_breaker_open`，致 Playwright `smoke.spec.ts` `expect(body.ok).toBe(true)` 失败。根因：`_check_circuit_breaker` 直接读 `breaker.state.value` 且从不调 `allow_request()`，而 OPEN→HALF_OPEN 的自动恢复只在 `allow_request()` 内触发——故一旦测试触发 5 次东财失败使 breaker OPEN，之后 60s 内无新 eastmoney 请求时，health 永久报 OPEN，Playwright 红。目标：health 读路径尊重 `recovery_timeout`，陈旧 OPEN（>60s 无请求）自愈为 HALF_OPEN；真实持续失败仍报 OPEN（信号保留）。

## 2. 背景
- `circuit_breaker.py`：`CircuitBreaker` 状态机 CLOSED/OPEN/HALF_OPEN；`failure_threshold=5`、`recovery_timeout=60s`。`allow_request()`（:40-51）是唯一在 OPEN 超 60s 时转 HALF_OPEN 的路径，但它有副作用（消耗 `half_open_calls` 试探名额、改 `self.state`）。
- `health.py:39-52` `_check_circuit_breaker()` 读 `breaker.state.value`（:45），返 `ok = state != "open"`；`health_check()`（:162）`overall_ok = all(...)`，故 OPEN→整体 ok=false。
- 熔断器状态纯内存（`_breakers` dict，重启即清，无持久化）——重启可临时清，但设计缺陷仍在，CI 会反复挂。

## 3. 需求清单
- [ ] R1：`CircuitBreaker` 增只读探测方法 `peek_state()`，返回"给定当前时间应处的状态"——OPEN 且 `time.time() - last_failure_time >= recovery_timeout` 时返 `HALF_OPEN`，否则返原 `self.state`；**不改 `self.state`、不消耗 `half_open_calls`**（无副作用）。
- [ ] R2：`_check_circuit_breaker()` 用 `breaker.peek_state().value` 取代 `breaker.state.value`，使陈旧 OPEN 自愈为 HALF_OPEN → health ok=true。
- [ ] R3：真实持续失败（OPEN 且未超 60s）仍报 OPEN → ok=false（信号保留，不屏蔽）。
- [ ] R4：`allow_request()` 行为不变（真实请求路径不受影响）。

## 4. 受影响文件
| 文件 | 改动 |
|---|---|
| `backend/circuit_breaker.py` | 加 `peek_state()` 方法（只读，无副作用） |
| `backend/routers/health.py` | `_check_circuit_breaker` 用 `peek_state().value` 取代 `state.value` |
| `backend/tests/test_circuit_breaker.py` | 新增：peek_state 单测 + health 陈旧 OPEN 自愈测（TDD） |

## 5. 设计方案
加 `peek_state()` 而非让 health 调 `allow_request()`——后者有副作用（消耗 half_open 名额、改 state），health 周期调用会干扰真实探测。peek 只读、幂等、尊重超时，正好给 health 用。OPEN→HALF_OPEN 的"真实"转换仍由 `allow_request()` 在真实请求时触发（peek 不抢）。备选（否决）：①重启后端清内存态——治标，CI 反复挂；②放宽 Playwright 健康断言——屏蔽真实下游降级信号，对投研看板危险。

## 6. 验收标准
- [ ] A1：`peek_state()` OPEN+未超 60s → OPEN；OPEN+超 60s → HALF_OPEN；peek 后 `self.state` 不变（无副作用）。
- [ ] A2：`_check_circuit_breaker()` 对陈旧 OPEN breaker（last_failure_time 早于 60s 前）返 `ok=true`（体检 🔴 复现场景修复）。
- [ ] A3：`_check_circuit_breaker()` 对新鲜 OPEN breaker（<60s）返 `ok=false`（真实信号保留）。
- [ ] A4：`pytest -m "not live"` 全绿（含新测，无回归）。
- [ ] A5：Playwright `smoke.spec.ts` health 断言转绿（后端起后，陈旧 breaker 自愈，无需手动重启）。

## 7. 合规与工程底线自查
- [x] 研判/推荐/买卖时机——本 spec 不涉及（纯后端 health 修复）。
- [x] 判断可复现——不涉及财务数据验算（`financial_rigor.py` 不适用）。
- [x] 涨停四池/连板股榜——不涉及。
- [x] 用户私有数据——不涉及（breaker 状态纯内存，无 key/持仓）。
- [x] 新增东财端点走 `em_get()`——不涉及（不新增端点，仅修 health 读路径）。

## 8. 测试计划
- 单测 `test_circuit_breaker.py`：peek_state 三态 + 无副作用（TDD RED→GREEN）。
- 集成：`_check_circuit_breaker` 陈旧/新鲜 OPEN 两种返值。
- 回归：`pytest -m "not live"` 全量。
- 手动/Playwright：起后端 → `/api/health` ok=true（即便 breaker 曾 OPEN）→ `smoke.spec.ts` 绿。

## 9. 风险与回滚
- 风险：peek 返 HALF_OPEN 时 `self.state` 仍 OPEN，两处观测短暂不一致——可接受（peek 是"应处状态"，真实转换由 allow_request 负责）。
- 回滚：删 `peek_state()`、health 改回 `state.value`（即回到体检前状态）。
