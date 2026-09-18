# Spec: S116 — storm-daemon last-write-wins availability 修复

> 状态：已实现(2026-08-30，代码 R1-R3 + 3 测试 + 3 review fix，全量 2440 passed 无 S116 回归；改动在工作树未提交)
> 作者：lzw9560  日期：2026-08-30
> 级别：small（1 诚实但 defect 项 availability 修复，storm_daemon + storm_predictor 消费，跨 2 文件+测试）
> 分支：develop
> 关联：S115（completeness-gaps 三修 732a05b，storm cluster #7）/ `registry.md` S115 状态节 storm-daemon-snapshot-no-provenance（诚实但 defect）/ S115 scan verify（"worth fixing independent of lying"）

## 1. 问题 / 目标

S115 scan #7 `storm-daemon-snapshot-no-provenance-last-write-wins`：verify 判 actually_honest（storm_predictor 检测空 + fallback_current 诚实标，非撒谎），但**明确称"underlying defect IS worth fixing independent of the lying verdict"**——last-write-wins 遮蔽 + 无 provenance 标记是真实可用性缺陷。

**毒窗口**：`fetch_snapshot` 失败/空→`snap["global_indices"]=[]`+仅 debug log，仍 append+write（无 fetch_ok/is_degraded 标记）；`get_t1_global_snapshot` 盲返 `snaps[-1]`——若 T-1 最后一次跑（23:55 抖动返空/进程死前 14:00 美股盘前）是降级/陈旧快照，静默遮蔽同日更早（21:00）的好夜间快照；storm_predictor 因 indices 空被迫 fallback_current，丢失本可得的 T-1 夜间数据。

**目标**：fetch_snapshot 加 provenance（fetch_ok/is_degraded）落盘；get_t1_global_snapshot 过滤 empty/degraded 快照取最近非空夜间好快照（非盲 snaps[-1]）。storm_predictor 据 provenance 标 degraded（可选）。返诚实不变（非撒谎修复，是可用性）。

ethos：坚实数据地基——可用性（不丢本可得的数据）也是地基一部分。

## 2. 背景

verify（wf_fe0ad61d）对 #7 的裁决："The crack's factual claims are ALL verified correct at the code level — the last-write-wins masking defect is real. fetch_snapshot on failure sets global_indices=[] (storm_daemon.py:42), logs only at debug (:43), persists the snapshot with no provenance marker (:71-73), and get_t1_global_snapshot bl[indly] returns snaps[-1]... The factual masking claim is correct and the underlying defect IS worth fixing (independent of the lying verdict)." 范式最近亲：S111 R2 `get_with_fallback_meta` 的 provenance（from_cache/is_stale）+ S109 空不缓存。

## 3. 需求清单

- [x] R1 `storm_daemon.fetch_snapshot`（:40-43,71-73）加 provenance 标记：`snap["fetch_ok"]`/`snap["is_degraded"]`（失败/空→fetch_ok=False/is_degraded=True），落盘保留
- [x] R2 `storm_daemon.get_t1_global_snapshot`（:95）过滤 empty/degraded 快照：跳过 `global_indices==[]` 或 `fetch_ok==False` 的，取最近非空夜间好快照（非盲 snaps[-1]）；全坏→返最近一个 + 标记 degraded（或返 None 让 storm_predictor fallback_current 诚实）
- [x] R3 `storm_predictor._collect_global_factor`（:81-83）读 snapshot provenance：degraded 快照→data_status='degraded'（非 ok），对齐 fallback_current 范式
- [x] R4 测试：bad snapshot（empty/degraded）不遮蔽 good（取到好快照）；全坏→fallback_current/missing 诚实标

## 4. 受影响文件

| 文件 | 改动 |
|---|---|
| `backend/strategies/storm_daemon.py` | R1 fetch_snapshot provenance + R2 get_t1_global_snapshot 过滤 |
| `backend/strategies/storm_predictor.py` | R3 读 provenance 标 degraded |
| `backend/tests/test_availability.py` | R4 扩 storm snapshot 测试 |
| `specs/S116-storm-daemon-availability/spec.md` | 本 spec |

## 5. 设计方案

fetch_snapshot 加 `fetch_ok`/`is_degraded` 到 snap dict 落盘（加性，storm_predictor 旧逻辑不读则 inert）。get_t1_global_snapshot 从盲 snaps[-1] 改过滤：`[s for s in snaps if s.get("global_indices") and s.get("fetch_ok", True)]`，取最近好快照；全坏→返最近坏 + storm_predictor 标 degraded（或返 None→fallback_current）。storm_predictor 读 snap.get("is_degraded")→data_status='degraded'。范式：S111 R2 provenance + S109 空不缓存。

## 6. 验收标准

- [x] A1 bad snapshot（empty/degraded）不遮蔽 good——get_t1_global_snapshot 取到最近好快照（非盲 snaps[-1] 的坏快照）
- [x] A2 全坏→storm_predictor 标 degraded/fallback_current（诚实，非 ok 假装）
- [x] A3 fetch_ok provenance 落盘 + storm_predictor 可读
- [x] A4 test_availability 扩 storm snapshot 测试全绿；全量 pytest 不回归（对齐 2437 passed 基线）

## 7. 合规与工程底线自查

- [x] 不臆造（bad→fallback_current/missing 诚实，不编造数据）
- [x] 私有数据隔离（无新增落盘，snapshot 是既有 .vibe-research 文件加字段）
- [x] em_get 防封（本 spec 不动 em_get 端点）
- [x] §44 口径（不出 winrate/r/verdict，仅可用性修复）

## 8. 测试计划

`pytest tests/test_availability.py`（扩 storm snapshot：bad 不遮蔽 good + 全坏→degraded）+ 全量 `pytest -m "not live" --deselect test_s032_refresh_loop --deselect test_fetch_global_intel_wm_import_fails`。

## 9. 风险与回滚

provenance 标记加性（旧 storm_predictor 不读则 inert，不破坏）。过滤逻辑若致返更早快照（非 snaps[-1]），是诚实（取好快照非盲 last）；回盲 snaps[-1] 恢复（但那是遮蔽 bug）。影响面=风暴预测 T-1 数据可用性，回滚恢复遮蔽不致崩。
