# S210 plan · event drift fix 技术方案

## 方案选择

**选 A（采用）：复用 `_fetch_index_bars_baostock` fetch index bars 算 o2c gap**
- baostock sh.000001 bars（open+close），算 market_o2c_gap = (open[D+1]-close[D])/close[D] per date
- 不改 index_ma20_regime.json（只 close，扩展存 open 改 cache 格式风险大）
- `_fetch_index_bars_baostock` 已有 cache 逻辑（gap_regime_stratified.py）

**不选 B：扩展 index_ma20_regime.json 存 open**——改 cache 格式，影响 compute_regime_labels，爆炸半径大。

**不选 C：用 index cache c2c 近似**——c2c 含日内+隔夜，不匹配 event o2c 口径，drift 估不准。

## per regime universe filter（设计选择）

`run(returns, dates, regime_map, universe_by_day_global)`：
- per regime wire_verdict 传 `universe_by_day_regime = {d: universe_by_day_global[d] for d in regime_dates if regime_map.get(d)==tag}`
- drift_adjusted = event_mean(bull) - universe_mean(bull days market gap)——控 regime-specific drift

**不选全局 universe**：verify 戳破点是"牛市 drift 未控"——该控牛市 regime 的 market drift，全局被 bear/range 稀释。

## 模块拆分

1. **market_gap.py（新 helper 或加 gap_regime_stratified.py）**：`compute_market_o2c_gap_by_date() -> dict[date, [gap]]`，复用 `_fetch_index_bars_baostock`
2. **regime_stratified_consecutive_relay_lift.py**：`run()` 加 `universe_by_day` 参数 + per regime filter + 传 wire_verdict
3. **s203_consecutive_relay_harness.py**：caller 算 universe_by_day_global 传 run()
4. **wire_verdict / verifier**：无改（已有 drift 透传 + 逻辑）

## 依赖序

market_gap helper → run() 加参数 → caller 传 → 重跑 → test

## 数据流

baostock index bars → market_o2c_gap_by_date → caller universe_by_day_global → run() per regime filter → wire_verdict(universe_by_day) → verifier adjust_event_drift → drift_adjusted + is_drift_inflated → verdict（drift-inflated 降级）
