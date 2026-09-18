# S212 · S205 4 战法 caller——跑历史 picks 算 returns 传 regime-stratified harness

> 状态：**spec 草稿**（2026-09-16）
> 关联：S205 per-战法维度集（match+harness 已有）/ S203 consecutive_relay caller 模板 / S210 drift fix

## 1. 问题

S205 5 战法 match（s205_match.py）+ regime-stratified harness（regime_stratified_{ruozhuanqiang,nzi_fanji,dixi_longtou,xingtai_fanbao}_lift.py）已有。但 **caller 没写**——没人跑历史 picks 算 returns 传 harness，4 战法 verdict 出不来。

consecutive_relay caller（s203_consecutive_relay_harness.py）是 lbc≥2 filter（简单）。S205 战法是**形态 match**（需 s205_match.match_xxx + indicators per pick），caller 更复杂。

## 2. 目标

统一 caller `tools/s205_strategy_harness.py`（参数化战法名），跑历史 picks 算 returns 传 regime-stratified harness。4 战法（除 auction_signal BLOCKER）出 verdict。

## 3. 需求

### 3.1 picks 来源
- zt_history lbc>=1 涨停池 picks（date, code）
- per pick 调 s205_match.match_xxx(code, date, bars, msc) 算 score
- threshold 过则命中（s205_match _score threshold）

### 3.2 indicators + msc
- pattern_scan_s205.compute_*(code, date, bars) 算 indicators
- s205_match._msc_*(msc) 算 msc scores
- msc 来源：market structure code（需查 msc 怎么 get——s205_match 注释提 msc dict）

### 3.3 compute_obs returns（套 consecutive_relay 口径）
- decimal gap_ret = (open[D+1]-close[D])/close[D]
- D 日一字板 filter（_is_unbuyable_next_bar(bars[d_idx])）
- cost _cost_pct/100 转 decimal
- regime-stratified（compute_regime_labels）+ drift fix（compute_market_o2c_gap_by_date 传 universe_by_day）

### 3.4 参数化战法
- caller main(战法名) 跑指定战法
- 复用 regime_stratified_{战法}_lift.run()
- 输出 verdict per regime

## 4. 受影响文件

| 文件 | 改动 |
|------|------|
| `tools/s205_strategy_harness.py` | 新 caller（参数化战法，套 consecutive_relay 模板 + s205_match） |
| `tests/test_s205_strategy_harness.py` | 新 test（compute_obs + match threshold + regime） |

## 5. 验收

- [ ] caller 参数化 4 战法（ruozhuanqiang/nzi_fanji/dixi_longtou/xingtai_fanbao）
- [ ] picks 从 zt_history + s205_match threshold 命中
- [ ] compute_obs decimal 口径 + D 日一字板 filter + cost
- [ ] regime-stratified + drift fix（universe_by_day 传）
- [ ] 4 战法 verdict 出（robust/underpowered/falsified）
- [ ] test：match threshold + compute_obs + regime
- [ ] 全 test 回归 0 break

## 6. 合规自查

- 不臆造：picks from zt_history + returns from baostock bars ✓
- 私有数据隔离：无新数据 ✓
- 防封：baostock cache + zt_history（无网络）✓
- §44 bearing：caller 套模板，非新方法论——SDD + TDD，不 grill ✓

## 7. 风险

- **msc 来源**：s205_match 注释提 msc dict（market structure code），但 caller 怎么 get msc 需查。可能需新 helper or msc from pattern_scan。
- **indicators 复杂**：compute_* 需 bars + 可能 msc。per pick 算 indicators 慢（4 战法 × ~2000 picks）。
- **match threshold**：s205_match _score threshold 需定（命中率影响 n）。
- **auction_signal BLOCKER**：yizi_jingjia 无免费竞价源，跳过（4 战法不含 auction）。
