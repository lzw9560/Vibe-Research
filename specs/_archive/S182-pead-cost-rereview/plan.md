# Plan: S182 — PEAD per-trade real cost 重审

> 技术方案（怎么做）。spec.md §5 已给核心设计，本文件补实现层细节。

## 模块拆分

三处改动，按依赖序：

1. **midline_event_harness.py**（共享 harness，先改）
   - 新增 import: `from engine.accounting import _cost_pct`
   - `build_return_series` 签名: `cost_pct: float | None = 0.0070` → 返 4-tuple `(returns, dates, guards, costs)`
   - `run_event_verdict` 签名: `cost: float | None = 0.0070` → 内部算 `avg_cost_ratio` 传 wire_verdict
2. **midline_pead_run.py**（PEAD run，后改）
   - `COST = 0.0070` → `COST = None`（触发 per-trade）
3. **新增 test_midline_event_harness.py**（TDD 先写，红→绿）

## 依赖序

```
test 先写（RED）→ build_return_series 改（GREEN）→ run_event_verdict 改 → midline_pead_run COST=None → 跑 15 verdict → 对比
```

build_return_series 是底层，先改；run_event_verdict 依赖它；PEAD run 依赖 run_event_verdict。

## 数据流

```
forecast_reports.json (4972 events, cached)
  → arms split (all / good_news / bad_news)
  → build_return_series(events, kline_cache, calendar, horizon, cost_pct=None)
      per event:
        entry_date = _calendar_next(calendar, pub_date)      # line 74，已有
        entry_open = bars[entry_idx]["open"]                  # line 88，已有
        cost_pp = _cost_pct(entry_open, 100.0, entry_date)   # 新：percentage points
        cost_dec = cost_pp / 100.0                            # 新：→ decimal
        ret = exit_close / entry_open - 1.0 - cost_dec        # line 112 改：cost_dec 非 cost_pct
        costs.append(cost_pp)                                 # 新
      → (returns, dates, guards, costs)                      # 4-tuple
  → run_event_verdict
      avg_cost_ratio = mean(costs) / 100.0                   # 新：decimal for wire_verdict
      → wire_verdict(round_trip_cost=avg_cost_ratio, ...)
        → verify(): returns 已 net（cost 已扣），round_trip_cost → effective_floor 门槛
        → Recorder.save + lineage.record
      → 15 verdicts 落盘
```

**关键不变量**: returns 始终 net（cost 已扣）。wire_verdict round_trip_cost 不二次扣成本——只设 materiality floor `max(0.003, cost*0.5)`（verifier.py:374）。与 gap run 完全同构。

## 备选方案（为何不选）

### 备选 A: 用 gap_net_return 替代 _cost_pct 直接调
`gap_net_return(entry_open, exit_close, entry_date, 100)` 返回 `(net_ratio, cost_pp, gross_ratio)`，net_ratio 已是 decimal net。
- 优点: 复用 battle-tested 路径，gap run 同源，单位转换封装在内部
- 不选原因: `gap_net_return` 会重复算 `gross = exit/entry - 1`（build_return_series line 112 已有此式），冗余虽小但破坏 build_return_series 自身的 return 计算结构（从"我算 ret"变成"gap_net_return 算 ret"）。且 task 明确指定 `_cost_pct(entry_open, 100, entry_date)`。
- 结论: _cost_pct 直接调更最小，只需管 cost 计算 + /100 转换

### 备选 B: costs list 存 decimal 而非 percentage points
- 优点: 不用 /100
- 不选原因: gap run `costs.append(cost_pct)` 存 percentage points（gap_net_return 返回值），跨 harness 不一致。存 percentage points 与 gap run 对齐，wire_verdict 处统一 /100

### 备选 C: 也改 S170 摘帽
- 不选原因: scope=PEAD（S182）。S170 改 COST=None 一行即复用，但独立验证 + verdict 对比是单独工作。标 sibling follow-up，不在本 spec 做

## flat 分支向后兼容验证

S170 传 `cost=0.0070`（float 非 None）:
- build_return_series: `cost_pct=0.0070`（float）→ flat 分支 → `cost_dec=0.0070`, `cost_pp=0.70`
- costs = [0.70] * n_valid
- run_event_verdict: `avg_cost_ratio = cost = 0.0070`（float 分支直接用 cost）
- wire_verdict round_trip_cost=0.0070 → 与改前完全一致
- S170 代码不改，行为不变 ✓

## underpowered 说明

PEAD 4972 事件总量够，但 good_news/bad_news arm 分层后:
- events 可能够（good_news 子集数百+）
- days_robust 可能 <60（预告集中在特定日期段）
- verify R6 gate（days_robust<60 → "underpowered" 不外推）已内建
- cost 改不影响 n/days（只影响 returns 值 + floor 门槛）
- underpowered verdict 是诚实标注非 bug——cost 改让它更可能 thin/falsified，但 status 不因 cost 翻为 robust（floor 上升反方向）