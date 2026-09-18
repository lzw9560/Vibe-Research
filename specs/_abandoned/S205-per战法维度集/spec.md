# Spec: S205 — per-战法维度集（5 战法扩展，龙头之外）

> 状态：**abandoned**（2026-09-19，milestone-2026-09-18-pivot freeze 决议：冻结新 spec/基建 + 做减法）。per-战法维度集 5 战法扩展在 freeze 前未实现；freeze 后不推进，移至 `specs/_abandoned/`（reversible git mv）。
> 原草案（2026-09-16）基于 `specs/_shared/dragon-score-dimension-registry.md` §4.2 预设计 + 6 lens grill（本文 §5）。待 plan.md/tasks.md。
> 关联：[[../S203-龙头战法数字化改造/spec.md]]（龙头 3 sub + Dragon Score 5 维）、[[../S204-多日跟踪架构与§44v2修正/spec.md]]（§44 harness + verifier 修正）、[[_shared/dragon-score-dimension-registry.md]]（维度 registry 预设计）。
> 上游：`wc4q5d73o`（5 战法研究 workflow，545k tokens，出 per-战法维度集映射）。

## 1. 问题 / 目标

S203 Dragon Score 5 维（板块/封单/量能/情绪/技术）是**龙头打板专用**，覆盖率仅 50-60%。龙头 edge 来自封单+板块共振；**非龙头 5 战法** edge 来源不同：

| 战法 | edge 来源（与龙头不同） |
|---|---|
| 一字竞价 | 竞价信号（量比/竞价额/订单失衡/9:20 不可撤单封单稳定性）——龙头无 |
| 弱转强 | 预期差反包（竞价高开+竞价量）——龙头无 |
| N字反击 | 量能节奏（首板倍量→缩量→再放量三段）+ 回调结构——龙头无 |
| 低吸龙头 | 回调节奏（距上次涨停/回调幅度/第一次回调）+ 龙头确认——龙头无 |
| 形态反包 | 反包确认强度（close 突破上影中点+吞没+放量）——龙头无 |

**edge 来源不同 → 不可共用龙头 5 维**。若实现时每战法硬编码 → ad-hoc 分叉、DRY 违反、维护爆炸。

**目标**：声明式 registry——5 战法各 DECLARE 维度集+权重+edge_type+sweep 参数，框架从声明算 composite + 跑 sweep。参数差异是 declared data 非 hardcoded logic。

## 2. 背景

- S203 Dragon Score 5 维已建（`06f898a`，dimension_registry.py + dragon_score.py composite 0-100）。
- `specs/_shared/dragon-score-dimension-registry.md` §3.1 共享 5 维 + §3.2 per-战法特有 7 维 + §4.2 S205 5 战法配置草案（本 spec formalize）。
- `backend/strategies/first_board/scoring.py` 14 score_dim 函数（dim1_sector~dim9_event + seal_time/sector_link/market_cap/seal_ratio/turnover）——候选筛选层 production-validated，Dragon Score 不替代不调（不同抽象层，§8 HIGH 已记）。
- §44 v2 闭环已落地（T4 `ca9ed25` sizing + T8 `012fef3` enforce + recorder fix `17e4708`）。forward_test breakout arm 151 天 ≥60（§44 verdict 能跑）。
- G5 S203 ×4 regime-stratified harness 全建齐（`e664353`，verdict 待数据）。

## 3. 需求清单

- [ ] **R1 一字竞价维度集**：竞价信号(0.30) + 封单强度竞价口径(0.25) + 情绪周期(0.20) + 技术形态(0.25)。edge_type=event（待验）。sweep: 竞价高开[2/3/5/7%] + 封单[0.3/0.5/0.7/1.0%]。⚠️ 竞价信号 data_source 须 Tushare `stk_auction` 或 hithink（付费，用户决策）——baostock 无，**BLOCKER 标待用户决策**。
- [ ] **R2 弱转强维度集**：预期差反包(0.25) + 量能确认(0.20) + 情绪周期(0.25) + 技术形态(0.20) + 板块强度(0.10)。edge_type=overnight_gap（待验）。sweep: 竞价量[1.0/1.5/2.0/2.5/3.0x] + 换手[5/10/15/20%]。
- [ ] **R3 N字反击维度集**：量能节奏(0.30) + 回调结构(0.25) + 技术形态(0.25) + 情绪周期(0.10) + 板块强度(0.10)。edge_type=selection（待验）。sweep: 三段量比 + 回调深度[10/20/30%] + 回调天[1/2/3]。
- [ ] **R4 低吸龙头维度集**：技术形态(0.30) + 龙头确认(0.20) + 回调节奏(0.20) + 量能反转(0.15) + 情绪周期(0.10) + 板块改口径(0.05)。edge_type=path（待验）。sweep: MA 回踩[5/10/20日] + 回调幅度[10/20/30%]。
- [ ] **R5 形态反包维度集**：技术形态(0.25) + 量能确认(0.20) + 反包确认强度(0.25) + 情绪周期(0.15) + 板块强度(0.15)。edge_type=event（待验）。sweep: 上影[3/4/5/6%] + 放量[1.0/1.5/2.0/2.5x]。
- [ ] **R6 DRY 复用**：维度 data_source 复用 DIMENSION_REGISTRY（seal_to_float_ratio/zt_count_today/lbc/sector_rank/volume_breakout_ratio/STI score/MA+形态），非新建。新增维度（pullback_structure/volume_rhythm/reversal_confirm/leader_identity/pullback_rhythm/auction_signal/expectation_gap_reversal）须在 registry §3.2 声明 data_source。
- [ ] **R7 §44 验证窗口**：5 战法 edge_type 全标"待验"（不预设）——须 window sanity 定位 edge 在哪个窗口（selection/event/overnight_gap/path），非写死。§44v2 rule①。
- [ ] **R8 weight 先验固定**：weights 是先验固定（非回测拟合），sweep 后不调权重（调=过拟合，§44v2 rule③）。R3 enforce 做长期校准（S204 T8 已落地）。

## 4. 受影响文件

| 文件 | 改动 |
|---|---|
| `specs/_shared/dragon-score-dimension-registry.md` | §4.2 草案 → formalize 5 战法 战法ScoreConfig（本 spec §5 grill 修正后） |
| `backend/strategies/dimension_registry.py` | 加 5 战法 STRATEGY_CONFIGS（声明式）+ 新增维度 data_source 声明 |
| `backend/strategies/dragon_score.py` | composite 接 5 战法 config（已建 composite 0-100，扩展 per-战法 config 查询） |
| `backend/strategies/`（新建 5 战法 match） | 一字竞价/弱转强/N字/低吸龙头/形态反包 match 逻辑（读维度 data_source 算 composite） |
| `backend/tools/regime_stratified_<战法>_lift.py`（×5） | §44 harness per-战法（DRY 复用 G5 ×4 范式 `e664353`） |
| `backend/tests/test_s205_*.py` | 5 战法维度集 + composite TDD |

## 5. 设计方案 + 6 lens grill

### 5.1 5 战法维度集（grill 修正后）

**一字竞价**：
```
战法ScoreConfig(
    战法="一字竞价",
    dimensions=("auction_signal","seal_strength_auction","emotion_cycle","tech_pattern"),
    weights={"auction_signal":0.30,"seal_strength_auction":0.25,"emotion_cycle":0.20,"tech_pattern":0.25},
    edge_type="待验(event 候选)",
    sweep_params={"auction_open_pct":[2,3,5,7],"seal_to_float_ratio":[0.003,0.005,0.007,0.010]},
    cost_model="vibe_0.15")
```
data_source: auction_signal（**Tushare stk_auction / hithink，付费，BLOCKER**）/ seal_to_float_ratio（涨停池 raw）/ STI score / MA+形态。

**弱转强**：
```
战法ScoreConfig(
    战法="弱转强",
    dimensions=("expectation_gap_reversal","volume_confirm","emotion_cycle","tech_pattern","sector_strength"),
    weights={"expectation_gap_reversal":0.25,"volume_confirm":0.20,"emotion_cycle":0.25,"tech_pattern":0.20,"sector_strength":0.10},
    edge_type="待验(overnight_gap 候选)",
    sweep_params={"auction_vol_ratio":[1.0,1.5,2.0,2.5,3.0],"turnover_pct":[5,10,15,20]},
    cost_model="vibe_0.15")
```
data_source: expectation_gap_reversal（竞价高开+竞价量，**须新建 compute**）/ volume_breakout_ratio + 换手 / STI / MA+形态 / zt_count_today。

**N字反击**：
```
战法ScoreConfig(
    战法="N字反击",
    dimensions=("volume_rhythm","pullback_structure","tech_pattern","emotion_cycle","sector_strength"),
    weights={"volume_rhythm":0.30,"pullback_structure":0.25,"tech_pattern":0.25,"emotion_cycle":0.10,"sector_strength":0.10},
    edge_type="待验(selection 候选)",
    sweep_params={"three_stage_vol_ratio":[...],"pullback_depth":[10,20,30],"pullback_days":[1,2,3]},
    cost_model="vibe_0.15")
```
data_source: volume_rhythm（首板倍量→缩量→再放量，**须新建 compute_volume_rhythm**）/ pullback_structure（**须新建 compute_pullback**）/ MA+形态 / STI / zt_count_today。

**低吸龙头**：
```
战法ScoreConfig(
    战法="低吸龙头",
    dimensions=("tech_pattern","leader_identity","pullback_rhythm","volume_reversal","emotion_cycle","sector_strength_alt"),
    weights={"tech_pattern":0.30,"leader_identity":0.20,"pullback_rhythm":0.20,"volume_reversal":0.15,"emotion_cycle":0.10,"sector_strength_alt":0.05},
    edge_type="待验(path 候选)",
    sweep_params={"ma_pullback":[5,10,20],"pullback_amplitude":[10,20,30]},
    cost_model="vibe_0.15")
```
data_source: MA+形态 / leader_identity（sector_rank≤3/lbc≥2/high_gene，**须新建 compute_leader_identity**）/ pullback_rhythm（**须新建**）/ 量能反转 / STI / sector 改口径。

**形态反包**：
```
战法ScoreConfig(
    战法="形态反包",
    dimensions=("tech_pattern","volume_confirm","reversal_confirm","emotion_cycle","sector_strength"),
    weights={"tech_pattern":0.25,"volume_confirm":0.20,"reversal_confirm":0.25,"emotion_cycle":0.15,"sector_strength":0.15},
    edge_type="待验(event 候选)",
    sweep_params={"upper_shadow_pct":[3,4,5,6],"volume_mult":[1.0,1.5,2.0,2.5]},
    cost_model="vibe_0.15")
```
data_source: MA+形态（吞没/上影，pattern_scan compute_engulf + shadow_length_pct）/ volume_breakout_ratio / reversal_confirm（**须新建 compute_reversal_confirm**：close 突破上影中点+吞没+放量综合）/ STI / zt_count_today。

### 5.2 6 lens grill（每战法维度集）

| lens | 一字竞价 | 弱转强 | N字 | 低吸龙头 | 形态反包 |
|---|---|---|---|---|---|
| 过拟合 | 中（4 维+4 sweep 值，须 sweep pass gate） | 中（5 维+5 sweep） | 中（5 维+3 sweep） | 中（6 维+2 sweep） | 中（5 维+4 sweep） |
| 样本 | underpowered（竞价信号 BLOCKER 无数据） | breakout 151 天 ≥60 OK | 待验（N字 picks days 未核） | 待验 | 待验 |
| 执行 | A 股 T+1+一字板买不到（is_unbuyable） | 同 | 同 | 同 | 同 |
| look-ahead | 竞价信号 T 日 9:20 后（pit guard T 日盘中） | 预期差 T 日竞价（pit guard） | 量能节奏 T-1 收盘 OK | 回调 T-1 OK | 反包 T 日 close（pit guard） |
| regime | MA20 3-way（G5 harness 范式） | 同 | 同 | 同 | 同 |
| data-snooping | edge_type 待验（不预设）+ sweep K 含次数 + weight 先验固定 | 同 | 同 | 同 | 同 |

**grill verdict**：5 战法全 **REVISE**：
1. **过拟合**：5 战法维度 4-6 个 + sweep 3-5 值——须 sweep pass gate（edge ≥2/4 邻近值，S204 R13 sweep harness 待 G6）
2. **样本**：一字竞价 BLOCKER（竞价信号无数据源）→ 标 BLOCKER 不实现；其余 4 战法 picks days 待核（forward_test breakout 151 天，但 N字/低吸/形态反包 picks 可能 <60）
3. **新增维度**：7 个新维度（auction_signal/expectation_gap_reversal/volume_rhythm/pullback_structure/leader_identity/pullback_rhythm/reversal_confirm）须建 compute 函数——data_source 须在 registry §3.2 声明（不臆造）
4. **edge_type 待验**：5 战法全标"待验"——须 §44 window sanity 定位窗口（非预设，§44v2 rule①）
5. **weight 先验固定**：weights 是先验（registry 给的），sweep 后不调（调=过拟合，§44v2 rule③）

**APPROVE 条件**：sweep pass gate + 新增维度 compute 建好 + §44 verdict（≥60 天 + picks ≥200）+ edge_type window sanity 验证。

## 6. 验收标准

- [ ] A1：5 战法 STRATEGY_CONFIGS 声明（dimensions + weights sum=1.0 + edge_type 待验 + sweep_params）
- [ ] A2：7 新增维度 data_source 在 registry §3.2 声明（不臆造，须现有或可复算）
- [ ] A3：dragon_score composite 接 5 战法 config（0-100，非 ML 特征）
- [ ] A4：5 战法 match 逻辑读维度 data_source 算 composite（DRY 复用 DIMENSION_REGISTRY）
- [ ] A5：§44 harness per-战法（DRY 复用 G5 ×4 范式，verdict 待数据）
- [ ] A6：edge_type 全标"待验"（不预设，§44v2 rule①）
- [ ] A7：weight 先验固定（sweep 后不调，§44v2 rule③）
- [ ] A8：pytest -m "not live" 全绿（含新 test 文件）

## 7. 合规与工程底线自查（逐条确认）

- [x] 研判/推荐属系统能力（CLAUDE.md §1.1）；Dragon Score 是 composite 评分非买卖时机，用户可见输出挂轻量风险提醒
- [x] 判断可复现：维度 data_source 须现有或可复算（registry §3.2 声明），禁臆造/心算；涉及数据跑 `~/tools/financial_rigor.py` 验算
- [x] 涨停四池/连板股榜个股属公开榜单（设计选择，可呈现 code/name）
- [x] 用户私有数据（持仓/研报/key）未进 git、未上传
- [x] 新增东财端点走 `em_get()` 限流（本 spec 不新增 em 端点，维度复用现有涨停池 raw + baostock + STI）
- [x] **工程底线**：不臆造数据（7 新维度 data_source 须声明现有或可复算）/ 私有数据隔离 / em_get 防封——全过

## 8. 测试计划

- pytest -m "not live" 全绿（含 test_s205_dimension_registry + test_s205_dragon_score_5战法 + test_s205_match_5战法）
- §44 harness per-战法跑 verdict（待 forward_test ≥60 天 + picks ≥200，当前待数据）
- 涉及数据输出（composite score）跑 `~/tools/financial_rigor.py` 验算（若 score 用于推荐）

## 9. 风险与回滚

- **风险**：7 新增维度 compute 须建（workload 大）；竞价信号 BLOCKER（一字竞价无法实现，标待用户决策）；5 战法 picks days 未核（可能 <60 underpowered）。
- **回滚**：spec 草案——实现前若 grill 发现维度集不可行，回退到 registry 4.2 草案 + S203 龙头 5 维。声明式 registry 设计——维度集是 declared data，改 config 不改框架逻辑（低回滚成本）。

## 10. open questions（待用户决策）

1. **竞价信号数据源**（一字竞价 BLOCKER）：Tushare `stk_auction`（付费）vs hithink（付费）vs 无（一字竞价不实现）——用户决策
2. **7 新增维度 compute 优先级**：pullback_structure/volume_rhythm/reversal_confirm/leader_identity/pullback_rhythm/expectation_gap_reversal/auction_signal——哪些先建？
3. **5 战法 edge_type**：须 §44 window sanity 验证（不预设）——跑 harness 后定
4. **weight 先验 vs 校准**：先验固定（registry 给），sweep 后不调（§44v2 rule③）；R3 enforce（S204 T8）做长期校准
5. **5 战法 picks days**：breakout 151 天 ≥60 OK，但 N字/低吸/形态反包 picks days 未核——须跑 harness 确认
