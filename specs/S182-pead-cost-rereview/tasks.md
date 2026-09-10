# Tasks: S182 — PEAD per-trade real cost 重审

> 可执行 checklist。每条带依赖序 + 验收点。TDD 先写测试。

## P0: 测试先行（RED）

- [x] T1 新建 `backend/tests/test_midline_event_harness.py`
  - 依赖: 无（TDD 红灯先写）
  - 验收点: 5 个测试函数能跑（全部 FAIL，因为 build_return_series 还没改）
  - [x] T1.1 test_build_return_series_flat_cost: 构造 2 个事件 + kline_cache，cost=0.0070，验证 ret = exit/entry - 1.0 - 0.007，costs=[0.70, 0.70]
  - [x] T1.2 test_build_return_series_per_trade_cost: 同事件，cost=None，验证 ret = exit/entry - 1.0 - _cost_pct(entry,100,date)/100，costs=[_cost_pct(...)] 非全 0.70
  - [x] T1.3 test_unit_mismatch_guard: entry_open=5.0（低价股），cost=None，验证 ret > -1.0（不出现 -2.70 荒谬值——若忘 /100 会 ret=gross-2.75）
  - [x] T1.4 test_run_event_verdict_cost_none_passes_avg: mock wire_verdict，验证 round_trip_cost = avg(costs)/100 而非 flat 0.0070
  - [x] T1.5 test_backward_compat_flat: cost=0.0070，验证 round_trip_cost=0.0070（行为不变）

## P1: build_return_series 改（GREEN）

- [x] T2 `backend/tools/midline_event_harness.py` build_return_series 签名 + 逻辑改
  - 依赖: T1（测试先跑红）
  - [x] T2.1 顶部加 `from engine.accounting import _cost_pct`
  - [x] T2.2 签名: `cost_pct: float = 0.0070` → `cost_pct: float | None = None`，返回类型 3→4 tuple
  - [x] T2.3 循环内: `if cost_pct is None: cost_pp = _cost_pct(entry_open, 100.0, entry_date); cost_dec = cost_pp / 100.0` else flat
  - [x] T2.4 line 112: `ret = exit_close / entry_open - 1.0 - cost_dec`（cost_dec 替 cost_pct）
  - [x] T2.5 `costs.append(cost_pp)`（percentage points）
  - [x] T2.6 return 加 costs（4-tuple）
  - 验收点: T1.1-T1.3 跑绿

## P2: run_event_verdict 改

- [x] T3 `backend/tools/midline_event_harness.py` run_event_verdict 签名 + 逻辑改
  - 依赖: T2（build_return_series 已改）
  - [x] T3.1 签名: `cost: float = 0.0070` → `cost: float | None = 0.0070`
  - [x] T3.2 解包 4-tuple: `returns, dates, guards, costs = build_return_series(...)`
  - [x] T3.3 `if cost is None: avg_cost_ratio = sum(costs)/len(costs)/100.0 if costs else 0.0` else `avg_cost_ratio = cost`
  - [x] T3.4 wire_verdict 调用: `round_trip_cost=avg_cost_ratio`（替 `round_trip_cost=cost`）
  - 验收点: T1.4-T1.5 跑绿；S170 flat cost 仍跑通

## P3: PEAD run 改

- [x] T4 `backend/tools/midline_pead_run.py` COST 改
  - 依赖: T3（run_event_verdict 已支持 None）
  - [x] T4.1 line 34: `COST = 0.0070` → `COST = None  # per-trade real cost (accounting._cost_pct)`
  - 验收点: import 不报错，run_event_verdict 收到 cost=None

## P4: 跑 15 verdict 重审

- [x] T5 跑 midline_pead_run 重审
  - 依赖: T4
  - [x] T5.1 `cd /Users/lizhiwei/project/code/stock/Vibe-Research/backend && .venv/bin/python -m tools.midline_pead_run`
  - [x] T5.2 15 verdict 落盘 Recorder + lineage（grep 输出 [verdict] × 15）
  - [x] T5.3 对比 S169 flat 版本: 记录哪些 verdict status 翻转（falsified/thin/underpowered 变化）
  - [x] T5.4 记录 avg cost（应 > 0.70%，低价股占比高则更高）
  - 验收点: 15 verdict 全落盘，输出含 per-trade avg cost 数值

## P5: 全量回归

- [x] T6 全量测试不挂
  - 依赖: T5
  - [x] T6.1 `pytest -m "not live" --deselect backend/tests/test_newsradar.py::test_fetch_global_intel_wm_import_fails --deselect backend/tests/test_s032_refresh_loop.py`
  - [x] T6.2 确认 S170 midline_st_removal_run 不改代码仍 import 通（flat 向后兼容）
  - 验收点: 全量绿

## P6: 归档

- [x] T7 spec 标状态 + commit
  - 依赖: T6
  - [x] T7.1 spec.md 顶部状态改「已实现(2026-09-10)」
  - [x] T7.2 commit: `feat(S182): PEAD per-trade real cost 重审——build_return_series 改 4-tuple + cost=None per-trade`
  - 验收点: commit 引用 S182 编号