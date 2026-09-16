# S211 plan · consecutive_relay arm 接线

## 方案

**新 overnight gap path**（非 simulate_holding -4/+8/3）：
- entry: D 日 close（一字板 filter）
- exit: D+1 open（1 天强制平）
- return = (open[D+1]-close[D])/close[D]
- 复用 s203_consecutive_relay_harness.compute_obs 口径（inline 或 extract helper）

**pick 来源**：zt_history lbc>=2 + is_final=1（当日 17:15 后终盘）——生产用当日 snapshot，paper backtest 用历史。

**regime-stratified cap**：
- DIMENSION_LIFT_REGISTRY 加 consecutive_relay entry: `{regime_caps: {bull:1.0, bear:0.5, range:0.5}}`
- lift_for_arm(arm, regime=None)——consecutive_relay regime 指定返该 regime cap，None 返保守 ×0.5
- final_size(arm, arm_size, regime=None) 透传

## 模块拆分

1. journal_recorder._process_consecutive_relay（overnight gap path + regime 计算）
2. journal_recorder.settle_pending_consecutive_relay（D+1 open 平仓）
3. journal_recorder.DEFAULT_ARMS 加 consecutive_relay + _arm_size regime 参数
4. evaluation.DIMENSION_LIFT_REGISTRY + lift_for_arm regime 参数
5. paper_portfolio.final_size regime 参数

## 依赖序

evaluation registry/lift → paper_portfolio final_size → journal_recorder _arm_size → _process/settle

## 数据流

zt_history lbc>=2 pick → _process_consecutive_relay（算 regime + overnight gap return）→ settle_pending（D+1 open 平）→ _arm_size("consecutive_relay", regime) → final_size（regime cap bite）→ journal ledger
