# Spec: S113 — 诚实缺陷项 availability 修复（S111 承重切片续 II）

> 状态：已实现(2026-08-30，代码 R1-R2 + 5 测试落地、全量 2432 passed 无 S113 回归；改动在工作树未提交)
> 作者：lzw9560  日期：2026-08-30
> 级别：small-medium（2 诚实缺陷项 availability 修复 + 1 文档化，跨 3 文件，非性质撒谎）
> 分支：develop
> 关联：S111/S112（撒谎裂缝全修 ed2a84c/9396b8d/076a6cf）/ `registry.md`（诚实缺陷项 3 条 修法已列）/ grill「坚实数据底座」第 5 层

## 1. 问题 / 目标

S111/S112 修了 14 条撒谎裂缝（全部诚实化）。剩 3 条**诚实但健壮性缺陷**项（返空/返{}诚实不撒谎，但崩/不可恢复）+ 1 deferred LOW。本切片修 availability：

- **chip-breaker 永久 OPEN 不可恢复**（手搓熔断器连续失败 3 次→永久 OPEN，进程生命周期内永久返{}失明）
- **premarket 裸读 cache 崩 500**（诚实崩非臆造，但违 S069 优雅降级契约；+ scheduled_tasks:1860 同型兄弟项）
- **source-key-leak 文档化**（`_with_source` 加 source 键到所有 fund flow API 响应，加性兼容，前端可后续消费——不结构性收窄，保留 useful provenance for R4/S112 cross-source 检测）

ethos：坚实数据地基，诚实 + 可用（不崩、可恢复）。

## 2. 背景

每条修法见 `registry.md` 诚实缺陷项节。**chip-cyq 自建走 em_get**（非平凡，重写 cyq 端点解析 push2his/api/qt/stock/cyq）= **S114** 独立研究切片，不在本 spec。

## 3. 需求清单

- [x] R1 `akshare_src.py` chip-breaker 自愈：对齐 `transport.py` 通用 circuit_breaker 加 recovery_timeout/half-open/record_success（连续失败 3 次→OPEN，N 秒后 half-open 试探，成功复位，失败回 OPEN），不再永久 OPEN
- [x] R2 `premarket_selection.py:96` + `scheduled_tasks.py:1860` 裸读守卫：加 `KLINE_CACHE.exists()`+try FileNotFoundError→返空候选/空+note（对齐 `first_board_filter:359-371`），不再崩 500
- [x] R3 source-key-leak 文档化：`registry.md`/spec 注明 fund flow API 响应带 source provenance（加性，前端可后续消费 degraded 徽章），不结构性收窄
- [x] R4 测试：chip-breaker 自愈（OPEN→timeout→half-open→成功复位）+ premarket 缺 cache 返空非 500

## 4. 受影响文件

| 文件 | 改动 |
|---|---|
| `backend/data/sources/akshare_src.py` | R1 chip-breaker 自愈 |
| `backend/strategies/premarket_selection.py` | R2 裸读守卫 |
| `backend/scheduled_tasks.py` | R2 :1860 同型裸读守卫 |
| `specs/S111-真实裂缝登记册/registry.md` | R3 source-key-leak 文档化注记 |
| `backend/tests/`（新或扩） | R4 测试 |

## 5. 设计方案

chip-breaker 对齐 `transport.py` 通用 breaker（recovery_timeout + half-open + record_success），不另起炉灶。premarket 对齐 `first_board_filter:359-371` `exists()`+try→`{}` 范式。source-key-leak 选**文档化非收窄**（provenance 对 R4/S112 cross-source 检测有用，前端 degraded 徽章待后续 YAGNI）。chip-cyq em_get 留 S114（非平凡，需研究东财 cyq 端点 + 走 em_get）。

## 6. 验收标准

- [x] A1 chip-breaker 连续失败 3 次→OPEN，N 秒后 half-open 试探，成功复位（不再永久 OPEN）
- [x] A2 premarket 缺 cache→返空候选非 500；scheduled_tasks:1860 同型守卫
- [x] A3 source-key-leak 文档化（registry 注记）
- [x] A4 chip-breaker 自愈 + premarket 守卫测试全绿；全量 pytest 不回归（对齐 2427 passed 基线）

## 7. 合规与工程底线自查

- [x] 不臆造（返空/返{}诚实不编值）
- [x] 私有数据隔离（无新增落盘）
- [x] em_get 防封（chip-cyq 走 em_get 留 S114，本 spec 不动 cyq）
- [x] §44 口径（不出 winrate/r/verdict）

## 8. 测试计划

`pytest` 新/扩测试（chip-breaker 自愈 + premarket 守卫）+ 全量 `pytest -m "not live" --deselect test_s032_refresh_loop --deselect test_fetch_global_intel_wm_import_fails`。

## 9. 风险与回滚

chip-breaker 自愈改动若致频繁 half-open 试探增加请求，调 recovery_timeout 即恢复。premarket 守卫加性。回滚恢复原（崩/永久 OPEN）行为不致新崩。

**实现后 review 观察（2 LOW，非 bug，无需改码，2026-08-30）**：
- scheduled_tasks:1860 守卫实为 c1a499e8（S101, 2026-08-28）既有，早于 S113——R2"同型裸读同崩"前提 stale，agent 查证后未加冗余守卫（不做"看起来正确但没用"的事），S113 只加钉死测试。
- CircuitBreaker 状态变更无 threading.Lock——既有缺陷与 transport.py 同款，影响低，后续并发成真再加锁。
- R3 source-key-leak 文档化（registry 注记 fund flow API 响应带 source provenance 加性，不结构性收窄）。
- chip-cyq em_get 留 S114（非平凡，需研究东财 cyq 端点 + 走 em_get）。
