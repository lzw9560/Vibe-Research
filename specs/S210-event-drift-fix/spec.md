# S210 · event drift fix——让 R11 drift fix 真接线（§44 event verdict 控市场 drift）

> 状态：**spec 草稿**（2026-09-16）
> 关联：S159 §44 v2 应用规约 / verify w5d3urvxz（consecutive_relay bull robust_edge refuted）/ S204 R11 T5b（event_drift.py 已设计但未接线）

## 1. 问题

§44 event edge 的 null 是 base_rate=0（单样本 mean>0）——牛市 drift 假阳性：所有股票隔夜正收益，event mean>0 但非真 edge（是市场整体高开）。

**verify w5d3urvxz 戳破**：consecutive_relay bull robust_edge（+1.38%→修 filter 后 +0.98%）——HIGH 2「drift 未控」：
- verifier.py:368 `drift = adjust_event_drift(returns, universe_by_day) if universe_by_day else None`
- harness 没传 universe_by_day → drift=None → H0=0（非 market_drift）
- R11 drift fix（event_drift.py）已设计但 bypassed
- bull 占 75%（68/91 天）——牛市 drift confound 最强处恰是唯一 powered regime

**影响**：不只 consecutive_relay——**所有 event edge_type verdict**（126 中 event 类）都 drift 未控，可能假 robust_edge。

## 2. 目标

让 R11 drift fix 真接线：event verdict 传 universe_by_day（市场隔夜 gap by date）→ verifier 算 `drift_adjusted = event_mean - universe_mean` → `is_drift_inflated`（event_mean>0 但 drift_adjusted≤0）时降级 non-robust。

**R11 已 grill 过**（wjiq1hkmz CRITICAL + 用户同意，方案①：event edge 也算 universe_by_day）。本 spec 是接线（数据 + 传参），非新方法论——SDD + TDD，不再 grill。

## 3. 需求

### 3.1 数据：市场隔夜 gap by date
- 算 market o2c gap = (index_open[D+1] - index_close[D]) / index_close[D] per trading day
- 数据源：baostock index bars（sh.000001 上证，open+close）——复用 `_fetch_index_bars_baostock`（gap_regime_stratified.py）
- index_ma20_regime.json 只 close 没 open——不能直接用，需 fetch bars 或扩展 cache 存 open
- 返 `{date: [index_o2c_gap]}`（单值 per date，list 包装兼容 event_drift 签名）

### 3.2 caller 传 universe_by_day
- caller（s203_consecutive_relay_harness.py 等 regime_stratified caller）算 universe_by_day_global 传 `run()`
- universe_by_day_global = {date: [index_o2c_gap]}（全局，all trading days）

### 3.3 run() 加 universe_by_day 参数 + per regime filter
- `regime_stratified_*_lift.py` 的 `run(returns, dates, regime_map, universe_by_day=None)`
- per regime wire_verdict 传 universe_by_day filtered 同 regime days：
  `universe_by_day_regime = {d: universe_by_day[d] for d in regime_dates if regime_map.get(d)==tag}`
- 这样 drift_adjusted = event_mean(bull) - universe_mean(bull days market gap)——控 regime-specific drift

### 3.4 wire_verdict / verifier 已有 drift 逻辑（接线即可）
- wire_verdict 已有 universe_by_day 参数（line 67）——caller 传即透传 verifier
- verifier.py:368 已算 drift + 373 base_rate + 378 net_mean=drift_adjusted
- is_drift_inflated 时降级 non-robust（防牛市假阳性 robust_edge）

### 3.5 复用范围
- regime_stratified harness 全家（consecutive_relay / first_board_limitup / leader_drop_reversal / reverse_package / S205 5 战法）同 pattern 加 universe_by_day
- 非 regime-stratified harness（T6 s209_t10_executor_harness.py 等）event verdict 也该传 universe_by_day（但 universe 该全局 all days，非 per regime）

## 4. 受影响文件

| 文件 | 改动 |
|------|------|
| `tools/gap_regime_stratified.py` 或新 helper | 算 market o2c gap by date（复用 `_fetch_index_bars_baostock`） |
| `tools/regime_stratified_consecutive_relay_lift.py` | `run()` 加 universe_by_day 参数 + per regime filter + 传 wire_verdict |
| `tools/regime_stratified_*_lift.py`（其他 8 个） | 同 pattern（可选，先 consecutive_relay 验证） |
| `tools/s203_consecutive_relay_harness.py` | caller 算 universe_by_day_global 传 run() |
| `tools/_s44_wire.py` | 无改（已有 universe_by_day 透传） |
| `s44_verifier/verifier.py` | 无改（已有 drift 逻辑） |
| `tests/test_regime_stratified_consecutive_relay_lift.py` | 加 universe_by_day 传参 test |
| `tests/test_s203_consecutive_relay_harness.py` | 加 universe_by_day 算+传 test |

## 5. 验收标准

- [ ] market o2c gap by date 算出（baostock index bars，非臆造）
- [ ] consecutive_relay caller 传 universe_by_day 给 run()
- [ ] run() per regime filter universe 同 regime days + 传 wire_verdict
- [ ] verifier drift_adjusted 非 None（universe 传入时）
- [ ] is_drift_inflated 时降级 non-robust（event_mean>0 但 drift_adjusted≤0）
- [ ] consecutive_relay bull 重跑：drift_adjusted < event_mean（控 drift），verdict 可能 flip（如果 drift-inflated）
- [ ] test：universe_by_day 传 vs 不传 verdict 差异；is_drift_inflated 降级
- [ ] 全 test 回归 0 break

## 6. 合规自查（弱合规——工程底线）

- **不臆造**：market gap 从 baostock index bars 算（真实数据），非心算 ✓
- **私有数据隔离**：index bars 公开数据，存 .vibe-research（VR_DATA_DIR）✓
- **防封**：baostock 走 `_fetch_index_bars_baostock`（限流，非裸 requests）✓
- §44 bearing：R11 drift fix 已 grill（wjiq1hkmz），本 spec 接线非新方法论，不再 grill ✓

## 7. 风险

- **per regime universe filter 设计选择**：filter 同 regime days（控 regime-specific drift）vs 全局。选 filter——更精确控牛市 drift（verify 戳破点）。若 grill 认为全局更稳可改。
- **index o2c vs event o2c 口径**：event gap = (stock_open[D+1] - stock_close[D]) / stock_close[D]。market gap 同口径（index_open[D+1] - index_close[D]）。对齐 ✓
- **baostock index bars fetch**：可能慢/网络。复用 `_fetch_index_bars_baostock`（已 cache 逻辑）。
- **is_drift_inflated 降级**：可能 over-aggressive（小 universe mean 也降级）。event_drift.py 已设计 is_drift_inflated=event_mean>0 AND drift_adjusted≤0——只降级真漂移假阳性，保守 ✓
