# S212 plan · S205 4 战法 caller

## 方案

**统一 caller 参数化战法**（非 4 个 caller）：
- `tools/s205_strategy_harness.py main(战法名)`
- 复用 consecutive_relay caller 模板（zt_history picks + compute_obs + regime harness）
- 加 s205_match.match_xxx threshold 命中

**picks 流程**：
1. zt_history lbc>=1 picks（date, code）
2. per pick 调 s205_match.match_xxx(code, date, bars, msc) 算 score
3. score threshold 过则命中（s205_match _score threshold 或 caller 定）
4. 命中 picks 算 returns（compute_obs decimal 口径）

**msc 来源**（待查）：s205_match 注释提 msc dict。可能需新 helper get_msc(code, date) or msc from pattern_scan。

**复用 S210 drift fix**：传 universe_by_day（compute_market_o2c_gap_by_date）给 regime harness。

## 模块拆分

1. caller tools/s205_strategy_harness.py（参数化战法 + picks + match + compute_obs + harness）
2. msc helper（如需）——查 s205_match _msc_* 怎么 get msc dict

## 依赖序

查 msc 来源 → caller picks + match → compute_obs → regime harness（+ drift fix）

## 数据流

zt_history picks → s205_match.match_xxx per pick → threshold 命中 → compute_obs（decimal gap + D 日一字板 filter + cost）→ regime-stratified harness.run（+ universe_by_day drift fix）→ verdict
