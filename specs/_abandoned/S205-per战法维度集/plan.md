# Plan: S205 — per-战法维度集技术方案

> 关联：[[spec.md]]、[[../_shared/dragon-score-dimension-registry.md]]、[[../S203-龙头战法数字化改造/plan.md]]。

## 1. 技术方案

**声明式 registry**（非硬编码）——5 战法各 DECLARE 维度集+权重+edge_type+sweep 参数，框架从声明算 composite + 跑 sweep。参数差异是 declared data 非 hardcoded logic。

- 维度集声明：`backend/strategies/dimension_registry.py` 加 5 战法 `STRATEGY_CONFIGS`（复用 S203 已建的 Dimension + 战法ScoreConfig dataclass）。
- composite 计算：`backend/strategies/dragon_score.py` 扩展——composite(config, code, date, indicators) 已建（S203 T2 `06f898a`），扩展 per-战法 config 查询（读 STRATEGY_CONFIGS[战法]）。
- 7 新增维度 compute：`backend/strategies/pattern_scan.py`（已建 compute_volume_breakout/compute_consolidation/compute_engulf/shadow_length_pct）扩展 + 新建 compute_pullback/compute_volume_rhythm/compute_reversal_confirm/compute_leader_identity/compute_pullback_rhythm/compute_expectation_gap_reversal/compute_auction_signal（BLOCKER 待数据源）。
- 5 战法 match：`backend/strategies/` 新建 5 战法 match（一字竞价/弱转强/N字/低吸龙头/形态反包）——读维度 data_source 算 composite + 命中门槛。
- §44 harness per-战法：`backend/tools/regime_stratified_<战法>_lift.py` ×5（DRY 复用 G5 ×4 范式 `e664353`，verdict 待数据）。

## 2. 模块拆分

| 模块 | 职责 | 依赖 |
|---|---|---|
| `strategies/dimension_registry.py` | 5 战法 STRATEGY_CONFIGS + 7 新维度 data_source 声明 | S203 Dimension/战法ScoreConfig |
| `strategies/dragon_score.py` | composite 0-100（per-战法 config 查询） | dimension_registry + indicators |
| `strategies/pattern_scan.py` | 7 新维度 compute 函数 | baostock bars + 涨停池 raw |
| `strategies/<战法>_match.py` ×5 | 5 战法 match 逻辑（读维度算 composite + 命中） | dragon_score + pattern_scan |
| `tools/regime_stratified_<战法>_lift.py` ×5 | §44 harness per-战法 | G5 ×4 范式 + wire_verdict |
| `tests/test_s205_*.py` | TDD（维度集 + composite + match + harness） | 全上 |

## 3. 依赖序

T1 registry config（声明 5 战法维度集）→ T2 7 新维度 compute（pattern_scan 扩展）→ T3 dragon_score composite 扩展（per-战法 config 查询）→ T4 5 战法 match（读维度算 composite）→ T5 §44 harness ×5（DRY 复用 G5）→ T6 sweep（S204 R13，待 G6）→ T7 verdict（待 forward_test ≥60 天 + picks ≥200）。

## 4. 取舍（备选为何不选）

- **声明式 registry vs 硬编码每战法**：选声明式——DRY + 可维护 + sweep 自动化；硬编码 ad-hoc 分叉、维护爆炸、DRY 违反（registry §1 已述）。
- **先验权重 vs 回测拟合**：选先验固定——防过拟合（§44v2 rule③，sweep 后不调权重）；回测拟合=过拟合（[[weight-as-ml-feature-is-inert]]）。
- **7 新维度 compute 现有 vs 新建**：DRY 复用 pattern_scan（compute_volume_breakout/compute_consolidation/compute_engulf/shadow_length_pct 已建）+ 新建 7 个（pullback/volume_rhythm/reversal_confirm/leader_identity/pullback_rhythm/expectation_gap_reversal/auction_signal）；不臆造 data_source。
- **5 战法 edge_type 预设 vs 待验**：选待验——§44v2 rule①（window sanity 定位窗口，非预设）；预设=data-snooping。
- **一字竞价 BLOCKER**：竞价信号 data_source（Tushare/hithink 付费）无——标 BLOCKER 不实现，待用户决策；其余 4 战法可推进（baostock + 涨停池 raw + STI 足够）。
