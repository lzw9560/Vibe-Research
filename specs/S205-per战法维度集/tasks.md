# Tasks: S205 — per-战法维度集（TDD checklist）

> 关联：[[spec.md]]、[[plan.md]]、[[../_shared/dragon-score-dimension-registry.md]]。
> 状态：草案（2026-09-16）。5 战法：一字竞价/弱转强/N字反击/低吸龙头/形态反包。

## T1 registry config（5 战法维度集声明，无依赖）

- [ ] **T1**: `strategies/dimension_registry.py` 加 5 战法 STRATEGY_CONFIGS（复用 S203 Dimension + 战法ScoreConfig）
  - 依赖：S203 T1（`06f898a` Dimension/战法ScoreConfig 已建）
  - 验收：1. test_5战法_config_dimensions_declared——5 战法各 dimensions 非空；2. test_weights_sum_one——每战法 weights sum=1.0；3. test_edge_type_marked_unverified——edge_type 含"待验"；4. test_sweep_params_nonempty——每战法 sweep_params 非空；5. test_7_new_dims_data_source_declared——auction_signal/expectation_gap_reversal/volume_rhythm/pullback_structure/leader_identity/pullback_rhythm/reversal_confirm 的 data_source 在 registry §3.2 声明（不臆造）。
  - test: `tests/test_s205_dimension_registry.py`

## T2 7 新维度 compute（依赖 T1）

- [ ] **T2a**: `strategies/pattern_scan.py` 加 compute_pullback（回调深度比/天数/不破首板起涨点）
- [ ] **T2b**: compute_volume_rhythm（首板倍量→缩量→再放量三段连续性评分）
- [ ] **T2c**: compute_reversal_confirm（close 突破上影中点+吞没程度+放量倍数综合）
- [ ] **T2d**: compute_leader_identity（sector_rank≤3/lbc≥2/high_gene/板块领涨综合）
- [ ] **T2e**: compute_pullback_rhythm（距上次涨停3-5日/回调幅度20-30%/第一次回调）
- [ ] **T2f**: compute_expectation_gap_reversal（竞价高开幅度+竞价量弱转强综合）
- [ ] **T2g**: compute_auction_signal（**BLOCKER**：Tushare stk_auction/hithink，待用户决策数据源；baostock 无）
  - 依赖：T1
  - 验收：1. test_compute_*_returns_float——每 compute 返 [0,1]；2. test_missing_data_returns_zero——缺数据 normalized=0 不报错；3. test_immutable——纯函数无副作用；4. test_auction_signal_blocked——compute_auction_signal 标 BLOCKER skipif 无数据源。
  - test: `tests/test_s205_pattern_scan_compute.py`

## T3 dragon_score composite 扩展（依赖 T1, T2）

- [ ] **T3**: `strategies/dragon_score.py` composite 接 5 战法 config（per-战法 config 查询）
  - 依赖：T1（config）+ T2（compute）
  - 验收：1. test_composite_5战法_range——5 战法 composite 返 [0,100]；2. test_composite_uses_config_dimensions——读 STRATEGY_CONFIGS[战法] dimensions；3. test_non_ml_guard——composite 不喂回 gene_score/scoring.py 排序；4. test_pure_function——同输入同输出。
  - test: `tests/test_s205_dragon_score_5战法.py`

## T4 5 战法 match（依赖 T3）

- [ ] **T4a**: `strategies/yizi_jingjia_match.py`（一字竞价，BLOCKER：auction_signal 无数据源，标 BLOCKER 不实现）
- [ ] **T4b**: `strategies/ruozhuanqiang_match.py`（弱转强）
- [ ] **T4c**: `strategies/nzi_fanji_match.py`（N字反击）
- [ ] **T4d**: `strategies/dixi_longtou_match.py`（低吸龙头）
- [ ] **T4e**: `strategies/xingtai_fanbao_match.py`（形态反包）
  - 依赖：T3（composite）+ 各维度 compute
  - 验收：1. test_match_returns_composite_or_none——命中返 composite，不命中 None；2. test_match_reads_dim_data_source——读维度 data_source（baostock+涨停池 raw+STI）；3. test_auction_signal_blocked——T4a 标 BLOCKER skipif；4. test_match_immutable。
  - test: `tests/test_s205_match_5战法.py`

## T5 §44 harness ×5（依赖 T4，DRY 复用 G5 ×4 范式）

- [ ] **T5**: `tools/regime_stratified_<战法>_lift.py` ×5（DRY 复用 G5 `e664353` 范式：gap_regime_stratified + wire_verdict）
  - 依赖：T4（match）+ G5 ×4 范式
  - 验收：1. test_harness_5战法_run——run() 接 returns/dates/regime_map → verdict dict；2. test_small_n_skip——小 n regime skip；3. test_edge_type_event_or_待验——edge_type 待验或 event；4. test_dry_reuse_wire_verdict——复用 _s44_wire.wire_verdict 非重写。
  - test: `tests/test_s205_regime_harness_5战法.py`

## T6 sweep（依赖 T5，待 S204 R13 sweep harness）

- [ ] **T6**: sensitivity sweep per-战法（读 SWEEP_PARAMS，overfit 检测 edge ≥2/4 邻近值）
  - 依赖：T5 + S204 R13（sweep harness 待 G6 建）
  - 验收：1. test_sweep_5战法——5 战法各 sweep 核心参数；2. test_overfit_single_value——edge 仅单 v → overfit_flag=True block；3. test_robust_multi_value——edge 多邻近 v → robust_flag=True。
  - test: `tests/test_s205_sweep.py`（或复用 S204 test_sensitivity_sweep.py）

## T7 verdict（依赖 T6，待数据）

- [ ] **T7**: 跑 5 战法 §44 harness verdict（待 forward_test ≥60 天 + picks ≥200）
  - 依赖：T6 + forward_test 积累（breakout 151 天 ≥60 OK；N字/低吸/形态反包 picks days 待核）
  - 验收：1. test_verdict_5战法——5 战法 verdict 出（robust_edge/exploratory/underpowered/falsified）；2. test_underpowered_if_days_lt60——days<60 标 underpowered 不外推；3. test_edge_type_window_sanity_verified——edge_type 经 window sanity 验证（非预设）。
  - test: 跑 harness（待数据）

## 全量验收（G7）

- [ ] **T8**: pytest -m "not live" 全绿 + §6 验收 gate 逐条核对
  - 验收：1. pytest 全绿；2. 5 战法维度集 weight sum=1.0；3. edge_type 全待验；4. 7 新维度 data_source 声明非臆造；5. composite 0-100 非 ML；6. §44 harness DRY 复用 wire_verdict。
