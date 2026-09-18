# S210 tasks · event drift fix checklist

> TDD：test 先写（RED）→ 实现（GREEN）→ 重跑验证

## T1 数据层：market o2c gap
- [ ] T1.1 test: `compute_market_o2c_gap_by_date()` mock index bars → 算 o2c gap 对（open[D+1]-close[D]）/close[D]
- [ ] T1.2 test: 缺 open/close → 跳过（不臆造）
- [ ] T1.3 实现: `compute_market_o2c_gap_by_date()` 复用 `_fetch_index_bars_baostock`，返 `{date: [gap]}`

## T2 run() 加 universe_by_day + per regime filter
- [ ] T2.1 test: `run(returns, dates, regime_map, universe_by_day)` per regime wire_verdict 传 filtered universe（同 regime days）
- [ ] T2.2 test: universe_by_day=None → drift None（回退原行为，向后兼容）
- [ ] T2.3 实现: `regime_stratified_consecutive_relay_lift.py` run() 加 universe_by_day 参数 + per regime filter + 传 wire_verdict

## T3 caller 算 + 传 universe_by_day
- [ ] T3.1 test: caller 算 universe_by_day_global 传 run()（mock compute_market_o2c_gap_by_date）
- [ ] T3.2 实现: `s203_consecutive_relay_harness.py` main() 算 universe_by_day_global 传 run()

## T4 verifier drift 接线（已有逻辑，验接线）
- [ ] T4.1 test: universe_by_day 传 → drift_adjusted 非 None（vs 不传 drift None）
- [ ] T4.2 test: is_drift_inflated（event_mean>0 but drift_adjusted≤0）→ 降级 non-robust
- [ ] T4.3 无实现（verifier.py 已有 drift 逻辑 line 368-378）——接线验证

## T5 重跑 + 验收
- [ ] T5.1 重跑 consecutive_relay bull：drift_adjusted < event_mean（控 drift），verdict 可能 flip
- [ ] T5.2 consecutive_relay bull 标 provisional → 真 verdict（robust / drift-inflated non-robust）
- [ ] T5.3 全 test 回归 0 break
- [ ] T5.4 memory 更新（consecutive_relay drift fix verdict）

## 复用范围（后续可选）
- [ ] T6.1 其他 regime_stratified harness（first_board_limitup / leader_drop / reverse_package / S205 5 战法）同 pattern 加 universe_by_day
- [ ] T6.2 非 regime-stratified harness（T6 s209 等）event verdict 传全局 universe_by_day
