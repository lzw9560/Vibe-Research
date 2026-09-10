# Spec: S182 — PEAD 中线 event edge per-trade real cost 重审

> 状态：已实现（2026-09-10）
> 作者：lzw9560  日期：2026-09-10
> 关联：S169（PEAD event edge 首跑 flat cost）、gap 60d/120d/regime 三重复验（扣 real cost net 负）、accounting._cost_pct（5元最低佣金+印花税+滑点）

## 1. 问题 / 目标

S169 PEAD 中线 event edge（pead_event_study + midline_pead_run）用 flat COST=0.0070（0.70% decimal）跑 15 verdict。gap 之前同样用 flat cost，改 per-trade real cost（accounting._cost_pct，含 5元最低佣金）后扣 net 负。PEAD 要做同样的事：改 per-trade real cost 重审 15 verdict 是否也扣成本 net 负。

一句话：PEAD 和 gap 用同一套成本模型才算公平——flat 0.70% 低估了低价股成本（5元股真实往返 2.75%，4 倍偏差），重审看 PEAD edge 是否扛得住真实成本。

## 2. 背景

### 现状（fresh 核实）

- `midline_event_harness.build_return_series`（line 34-124）: `cost_pct: float = 0.0070`（decimal），line 112 `ret = exit_close / entry_open - 1.0 - cost_pct`。return 是 decimal 制，cost 也是 decimal。
- `accounting._cost_pct(entry_price, size=100, entry_date)`（line 71-83）返回 **percentage points**（0.75 = 0.75%），含 0.70% 滑点 + 印花税（2023-08-28 前 0.10%/后 0.05%）+ 5元最低佣金（per side ×2 / notional ×100）。
- `midline_pead_run.py` line 34: `COST = 0.0070`，传 `run_event_verdict(cost=COST)`。
- `run_event_verdict`（line 127-159）: 传 `cost` 给 `build_return_series(cost_pct=cost)` + `wire_verdict(round_trip_cost=cost)`。

### 单位不匹配（CRITICAL 设计风险）

`_cost_pct` 返回 percentage points（如 2.75），`build_return_series` 在 decimal 空间操作（如 0.05）。直接把 `_cost_pct` 减进去会让 `ret = 0.05 - 2.75 = -2.70`（-270%，荒谬）。**必须 `/100.0` 转 decimal**。gap run 的 `gap_net_return` 已正确处理（accounting.py line 211: `net = gross - cost / 100.0`）。

### 实测成本偏差（_cost_pct 验算）

| 价格 | size | flat cost | real cost (post-halv) | 偏差 |
|---|---|---|---|---|
| 5 元 | 100 | 0.70% | 2.75% | 4x |
| 20 元 | 100 | 0.70% | 1.25% | 1.8x |
| 50 元 | 100 | 0.70% | 0.95% | 1.4x |
| 5 元 (pre-2023-08-28) | 100 | 0.70% | 2.80% | 4x |

5元最低佣金对低价股冲击最大——PEAD 预告事件含小盘股，flat cost 严重低估。

### wire_verdict round_trip_cost 用途（fresh 核实，非 double-subtraction）

`round_trip_cost` **不从 returns 中二次扣成本**。verifier.py line 374: `effective_floor = max(_EVENT_MATERIALITY_FLOOR=0.003, round_trip_cost * 0.5)`——只用于 materiality floor 门槛（day-mean net return 须超半成本才算 robust）。returns 已 net（build_return_series 已扣成本），round_trip_cost 只设 floor。gap run 同模式: returns 已 net + round_trip_cost=avg_cost_ratio 供 floor。

### 参考实现（gap run per-trade cost pattern）

- `s44_gap_run_60d.py` line 198-207: `gap_net_return(close, open_next, entry_date, TRADE_SIZE=100)` → returns net + costs list（percentage points）
- line 400-436: `cost_ratios = costs_arr / 100.0` → `avg_cost_ratio` → `wire_verdict(round_trip_cost=avg_cost_ratio)`
- `gap_regime_stratified.py` line 168-172, 472: 同 pattern

## 3. 需求清单

- [ ] R1 `build_return_series` 改返 4-tuple `(returns, dates, guards, costs)`，`cost_pct: float | None = 0.0070`：None 时 per-trade `_cost_pct(entry_open, 100, entry_date)`，float 时 flat（向后兼容 S170）
- [ ] R2 `run_event_verdict` 改 `cost: float | None = 0.0070`：cost=None 触发 per-trade + `avg(costs)/100.0` 传 wire_verdict round_trip_cost
- [ ] R3 `midline_pead_run.py` COST=None（per-trade real cost）
- [ ] R4 跑 midline_pead_run 重审 15 verdict（3 arms × 5 horizons），对比 S169 flat cost 版本看 PEAD 是否扣 real cost net 负

## 4. 受影响文件

| 文件 | 改动 |
|---|---|
| `backend/tools/midline_event_harness.py` | build_return_series 签名 3→4 tuple + cost_pct=None 分支 + import _cost_pct；run_event_verdict cost=None 分支 + avg cost → wire_verdict round_trip_cost |
| `backend/tools/midline_pead_run.py` | `COST = 0.0070` → `COST = None` |
| `backend/tools/midline_st_removal_run.py` | **不改**（flat cost 向后兼容，但同 bug——标 sibling follow-up S183） |
| `backend/tests/test_midline_event_harness.py` | 新增（TDD） |

## 5. 设计方案

### build_return_series 改动

```python
from engine.accounting import _cost_pct  # 新增 import

def build_return_series(
    events, kline_cache, calendar, horizon, cost_pct=None,  # float|None, 默认 None=per-trade
) -> tuple[list[float], list[str], dict, list[float]]:
    ...
    costs: list[float] = []  # 新增
    for ev in events:
        ...
        entry_date = _calendar_next(calendar, pub_date)  # line 74 已有
        entry_open = float(entry_bar.get("open", 0) or 0)  # line 88 已有
        ...
        if cost_pct is None:
            cost_pp = _cost_pct(entry_open, 100.0, entry_date)  # percentage points
            cost_dec = cost_pp / 100.0  # → decimal（单位转换，CRITICAL）
        else:
            cost_dec = cost_pct  # flat decimal（向后兼容）
            cost_pp = cost_pct * 100.0
        ret = exit_close / entry_open - 1.0 - cost_dec
        returns.append(ret)
        dates.append(pub_date)
        costs.append(cost_pp)  # 存 percentage points（与 gap run 一致）
    ...
    return returns, dates, guards, costs  # 4-tuple
```

### run_event_verdict 改动

```python
def run_event_verdict(*, ..., cost: float | None = 0.0070, ...):
    returns, dates, guards, costs = build_return_series(
        events, kline_cache, calendar, horizon, cost,
    )
    if cost is None:
        avg_cost_ratio = (sum(costs) / len(costs) / 100.0) if costs else 0.0
    else:
        avg_cost_ratio = cost  # flat decimal
    return wire_verdict(..., round_trip_cost=avg_cost_ratio, ...)
```

### 取舍

- **`_cost_pct` 直接调 vs `gap_net_return`**: 选 `_cost_pct` 直接——build_return_series 已算 return，只需 cost；gap_net_return 会重复算 gross。改动最小，与 task 指定一致。
- **costs 存 percentage points vs decimal**: 存 percentage points（与 gap run `costs.append(cost_pct)` 一致）；wire_verdict round_trip_cost 需 decimal → `/100.0`。
- **flat 分支也返 costs**: 是（`[cost_pct*100]*n`），保持 4-tuple 一致，run_event_verdict 逻辑统一。flat 分支 avg(costs)/100 = cost_pct，行为不变。

### 不改的

- S170 摘帽同 flat cost bug，但 S182 scope=PEAD。S170 只需改 `COST=None` 一行即复用——标 sibling follow-up，不在本 spec 做。
- verify() / wire_verdict 签名不动（round_trip_cost 已支持 decimal float）。

## 6. 验收标准

- [ ] A1 per-trade cost != flat: costs list 元素值非全部 0.70（低价股 ~2.75），avg cost > 0.70%
- [ ] A2 单位正确: ret 在合理范围（无 -270% 荒谬值），avg_cost_ratio 传 wire_verdict 为 decimal
- [ ] A3 15 verdict 落盘 Recorder + lineage，status 可读（对比 S169 flat 版本）
- [ ] A4 flat 分支（cost=float）行为不变: S170 不改代码仍跑通，round_trip_cost=0.0070
- [ ] A5 新增 build_return_series + run_event_verdict 单元测试（TDD，含 flat/per-trade 两条路径 + 单位验证）

## 7. 合规与工程底线自查

- [x] 研判/推荐: PEAD verdict 是研究输出（event edge 是否存在），非交易信号/买卖推荐 → 系统能力内
- [x] 判断可复现: _cost_pct 是 deterministic 函数（价格+size+日期 → 成本），重跑可复算；用已有 accounting 层，不臆造
- [x] 用户私有数据: forecast_reports.json + kline_cache 在 .vibe-research/（VR_DATA_DIR），不进 git
- [x] em_get: PEAD 用缓存数据（collect_forecast_reports 读 cache），无新增东财端点
- [x] 涨停四池/个股: 无个股呈现（verdict 是聚合统计）

## 8. 测试计划

新增 `backend/tests/test_midline_event_harness.py`（TDD 先写）:
- test_build_return_series_flat_cost: cost=0.0070，验证 ret = gross - 0.007，costs=[0.70]*n
- test_build_return_series_per_trade_cost: cost=None，验证 ret = gross - per_trade_cost/100，costs 非空且低价股 > 0.70
- test_unit_mismatch_guard: 5元股 per-trade ret 不出现 -270% 荒谬值（单位转换正确）
- test_run_event_verdict_cost_none_passes_avg: round_trip_cost = avg(costs)/100
- test_backward_compat_flat: cost=0.0070 行为不变（round_trip_cost=0.0070）

全量: `pytest -m "not live" --deselect backend/tests/test_newsradar.py::test_fetch_global_intel_wm_import_fails`
手动: `backend/.venv/bin/python -m tools.midline_pead_run` 跑 15 verdict 对比 S169

## 9. 风险与回滚

- **单位不匹配**（最高风险）: 忘 `/100.0` → ret 荒谬负值。验收 A1/A2 + 单测 test_unit_mismatch_guard 兜底。
- **签名破坏**: build_return_series 3→4 tuple。grep 确认唯一调用方是 run_event_verdict（同文件），无外部 breakage。run_event_verdict 调用方 S169/S170，S170 flat 向后兼容不改。
- **underpowered**: PEAD 分层 good_news/bad_news arm 可能 days_robust<60 → verify R6 gate 标 underpowered（不外推）。cost 改不影响 n/days，只影响 returns + floor。
- **floor 上升**: per-trade avg cost > flat 0.0070 → `effective_floor = max(0.003, avg_cost*0.5)` 上升 → 更难 robust。正确方向（真实成本高，门槛该高），非 bug。
- 回滚: `git revert` 单 commit，S169 回 flat cost 版本。