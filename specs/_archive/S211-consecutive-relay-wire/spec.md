# S211 · consecutive_relay arm 接线进 journal_recorder（overnight gap path）

> 状态：**spec 草稿**（2026-09-16，方向调整：原 wire sizing → arm 接线）
> 关联：S203 consecutive_relay harness / S209 T4 final_size 4-layer / S210 drift fix

## 1. 问题

consecutive_relay bull robust_edge 三重验证后站住（+1.055% drift-adjusted，真 edge）。但 **consecutive_relay arm 不在生产**——journal_recorder DEFAULT_ARMS=["floor","breakout","trend"] + post_first_board，无 consecutive_relay（line 48,170）。

verdict 是研究结论，无生产 sizing 闭环。要部署需先接 arm。

## 2. 目标

接 consecutive_relay arm 进 journal_recorder：
- 新 _process_consecutive_relay（overnight gap path：D 收买入 → D+1 开卖出，1 天）
- DEFAULT_ARMS 加 consecutive_relay（探索性 paper，同 post_first_board）
- arm 走 final_size 4-layer（T4）让 §44 cap bite sizing

## 3. 需求

### 3.1 overnight gap path（非 -4/+8/3）
- entry: D 日 close（一字板 filter，_is_unbuyable_next_bar(bars[d_idx])）
- exit: D+1 open（隔夜 gap 捕获）
- return = (open[D+1] - close[D]) / close[D]
- cost: _cost_pct（per-trade，5元门）
- 复用 s203_consecutive_relay_harness.compute_obs 口径（decimal）

### 3.2 _process_consecutive_relay
- pick 来源：zt_history lbc>=2 + is_final=1（当日涨停池）或 run_daily_forward_test 历史
- per pick 算 regime（compute_regime_labels[pick_date]）——为 §44 cap per regime 铺路
- settle_pending_consecutive_relay（D+1 open 平仓）
- arm_size = _arm_size("consecutive_relay", regime=pick_regime)（T4 final_size 4-layer）

### 3.3 DEFAULT_ARMS + 配置
- DEFAULT_ARMS 加 "consecutive_relay"（探索性 paper，lbc>=2 bull regime 有 edge）
- path params：overnight gap（无 stop/take/max_hold——1 天 D+1 开强制平）
- §44 cap：bull ×1.0（robust）/ bear+range ×0.5（underpowered）——regime-stratified

### 3.4 verdict→sizing 闭环
- DIMENSION_LIFT_REGISTRY 加 consecutive_relay（regime-stratified caps）
- lift_for_arm("consecutive_relay", regime) 返该 regime cap
- final_size("consecutive_relay", base, regime) 用 regime cap

## 4. 受影响文件

| 文件 | 改动 |
|------|------|
| `strategies/journal_recorder.py` | _process_consecutive_relay + settle_pending + DEFAULT_ARMS + _arm_size regime 参数 |
| `engine/paper_portfolio.py` | final_size 加 regime 参数（consecutive_relay regime-stratified） |
| `candidate_funnel/evaluation.py` | DIMENSION_LIFT_REGISTRY 加 consecutive_relay + lift_for_arm regime 参数 |
| `strategies/journal_recorder.py` | _process_consecutive_relay pick 来源 + regime 计算 |

## 5. 验收

- [ ] _process_consecutive_relay 实现（overnight gap path）
- [ ] DEFAULT_ARMS 含 consecutive_relay
- [ ] settle_pending_consecutive_relay（D+1 open 平仓）
- [ ] arm 走 final_size 4-layer（§44 cap bite）
- [ ] regime-stratified cap（bull ×1.0, bear/range ×0.5）
- [ ] test：_process_consecutive_relay 算 return 对 + regime cap bite
- [ ] 全 test 回归 0 break

## 6. 合规自查

- 不臆造：pick from zt_history/forward_test，return from baostock bars ✓
- 私有数据隔离：无新数据 ✓
- 防封：无网络（baostock cache + zt_history）✓
- §44 bearing：arm 接线 + regime cap 是 T4 闭环，非新方法论——SDD + TDD，不 grill ✓

## 7. 风险

- **overnight gap path 是新 path**（非 simulate_holding -4/+8/3）。1 天持有，无 stop/take——D+1 开强制平。需新 path helper 或 inline。
- **pick 来源**：生产 consecutive_relay pick 该从哪——zt_history 当日（需 17:15 后 is_final）或 forward_test？设计选择。
- **regime 计算**：per pick 算 regime 需 compute_regime_labels（cache load）。性能——session load 一次。
- **探索性 paper**：consecutive_relay arm 探索性（bull robust 但 bear/range underpowered），标 PAPER 同 post_first_board。
