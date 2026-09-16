# S211 tasks · consecutive_relay arm 接线 checklist

> TDD：test 先（RED）→ 实现（GREEN）→ 验收

## T1 evaluation: regime-stratified cap
- [ ] T1.1 test: DIMENSION_LIFT_REGISTRY 有 consecutive_relay entry（regime_caps）
- [ ] T1.2 test: lift_for_arm("consecutive_relay", regime="bull") 返 1.0
- [ ] T1.3 test: lift_for_arm("consecutive_relay", regime="bear") 返 0.5
- [ ] T1.4 test: lift_for_arm("consecutive_relay", regime=None) 返 0.5（保守）
- [ ] T1.5 实现: DIMENSION_LIFT_REGISTRY + lift_for_arm regime 参数

## T2 paper_portfolio: final_size regime
- [ ] T2.1 test: final_size("consecutive_relay", base, regime="bull") 用 ×1.0
- [ ] T2.2 test: final_size regime=None 用保守 ×0.5
- [ ] T2.3 实现: final_size 加 regime 参数（透传 lift_for_arm）

## T3 journal_recorder: _process + settle
- [ ] T3.1 test: _process_consecutive_relay overnight gap return 对（D 收→D+1 开）
- [ ] T3.2 test: D 日一字板 filter（不买）
- [ ] T3.3 test: settle_pending_consecutive_relay D+1 open 平仓
- [ ] T3.4 test: _arm_size("consecutive_relay", regime="bull") bite ×1.0
- [ ] T3.5 实现: _process_consecutive_relay + settle_pending + DEFAULT_ARMS + _arm_size regime

## T4 验收
- [ ] T4.1 DEFAULT_ARMS 含 consecutive_relay
- [ ] T4.2 全 test 回归 0 break
- [ ] T4.3 memory 更新（consecutive_relay arm 接线 + verdict→sizing 闭环）
