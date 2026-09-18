# Spec: S117 — premarket S101 f_date off-by-one 功能性修复

> 状态：已实现(2026-08-30，vr_paths helper + 3 S101 f_date + 2 测试，全量 2442 passed 无 S117 回归；改动在工作树未提交)
> 作者：lzw9560  日期：2026-08-30
> 级别：small（功能性 bug，3 行 f_date 日期逻辑 + vr_paths helper + 测试，非性质撒谎）
> 分支：develop
> 关联：S115 scan（premarket-funnel-cache-fdate-offbyone #13，honest_already 诚实但致 S101 整式空转，scan 建议提 medium 级立即修）/ `registry.md` S115 状态节

## 1. 问题 / 目标

S101 三个时点通知（9:25 竞价 / 9:35 开盘 / 16:35 T+1 复盘）全用 `f_date = payload.get("date") or last_trading_date_str()`，但 `last_trading_date_str()` 在 d 为交易日时返 d 本身（vr_paths:117）。任务在 T 日（交易日）跑 → f_date=T 日，但 final_candidates 存在 F 日（上一交易日，first_board_filter 在 F 日盘后落盘）→ `_load_final_cards(T日)` 找不到 → no_candidates → S101 三时点通知**整式空转**（永远 no_candidates 跳过，从不发通知）。

注释明确写"F 日（上一交易日）funnel_cache final_candidates"——意图是 F 日，代码却取 T 日，off-by-one。

**目标**：3 处 f_date 改 `prev_trading_date_str()`（F 日=严格前一交易日），candidates 找到 → S101 通知恢复。非性质撒谎（数据诚实，是功能性日期 bug）。

## 2. 背景

`last_trading_date(d)` 返 d 当日或之前最近交易日（d 为交易日→返 d 本身，vr_paths:117）；`prev_trading_date(d)` 返 d 之前（不含 d）最近交易日（先 d-1 再回退，vr_paths:125-133，S088 grill Q1 修过同款"前一交易日取到当日"bug）。S101 seed `payload={}`（scheduled_tasks:2383）无 date → 默认 `last_trading_date_str()`。storm_predictor `_prev_trading_day` 已用 prev_trading_date 范式（同款 bug 已修过）。

## 3. 需求清单

- [x] R1 `vr_paths.py` 加 `prev_trading_date_str(d=None)` helper（返 prev_trading_date(d).isoformat()，对称 last_trading_date_str）
- [x] R2 `scheduled_tasks.py` 3 处 f_date 改 `prev_trading_date_str()`：:1039 `_execute_premarket_auction_notify` / :1060 `_execute_premarket_open_notify` / :1087 `_execute_premarket_t1_review`；对应 import `last_trading_date_str`→`prev_trading_date_str`（t1_review 保留 next_trading_date）
- [x] R3 测试：T 日（交易日）跑 t1_review 空 payload → f_date=F 日（prev trading day）→ _load_final_cards 被调以 F 日（非 T 日）→ candidates 找到非 no_candidates

## 4. 受影响文件

| 文件 | 改动 |
|---|---|
| `backend/vr_paths.py` | R1 加 prev_trading_date_str |
| `backend/scheduled_tasks.py` | R2 3 处 f_date + import |
| `backend/tests/test_availability.py` | R3 off-by-one 测试 |
| `specs/S117-premarket-offbyone/spec.md` | 本 spec |

## 5. 设计方案

`prev_trading_date_str` 对称 `last_trading_date_str`（vr_paths 既有范式）。3 处 f_date 从 `last_trading_date_str()`（T 日）改 `prev_trading_date_str()`（F 日），对齐注释意图 + storm_predictor `_prev_trading_day` 范式。payload.get("date") 保留（手动指定日仍生效，覆盖默认）。

## 6. 验收标准

- [x] A1 t1_review T 日跑空 payload → f_date=F 日（prev trading day）→ _load_final_cards(F 日) → candidates 找到（非 no_candidates 跳过）
- [x] A2 3 处 f_date 全改 prev_trading_date_str；payload.get("date") 手动覆盖仍生效
- [x] A3 test_availability 扩 off-by-one 测试全绿；全量 pytest 不回归（对齐 2440 passed 基线）

## 7. 合规与工程底线自查

- [x] 不臆造（candidates 诚实读取，仅修日期指向）
- [x] 私有数据隔离（无新增落盘）
- [x] §44 口径（t1_review §44 诚实口径 n<30/lift<2x 不变，仅修日期 bug 让通知真发）

## 8. 测试计划

`pytest tests/test_availability.py`（扩 off-by-one：T 日跑→f_date=F 日）+ 全量 `pytest -m "not live" --deselect test_s032_refresh_loop --deselect test_fetch_global_intel_wm_import_fails`。

## 9. 风险与回滚

f_date 改 prev_trading_date_str 后，T 日跑读 F 日 candidates（对齐注释意图 + first_board_filter 落盘日）。若 F 日 first_board_filter 未跑（无 candidates），仍 no_candidates 跳过（诚实，非 bug）。回滚 last_trading_date_str 恢复 S101 空转（那是 bug）。影响面=S101 三时点通知恢复，回滚恢复空转不致崩。
