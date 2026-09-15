# Dragon Score 维度 Registry 预设计（S203 + S205 共享）

> 状态：**设计草案**（2026-09-14）。提前设计思考——per-战法参数差异用**声明式 registry** 结构化，避免实现时 ad-hoc 分叉。
> 关联：[[../S203-龙头战法数字化改造/spec.md]]（龙头 5 维）、S205（5 战法 per-战法维度集，下轮）。
> 来源：w50pptu5i（龙头 6 专家）+ wc4q5d73o（5 战法研究，545k tokens）+ memory [[weight-as-ml-feature-is-inert]]（composite 非 ML 特征）。

## 1. 设计目标

**核心问题**：Dragon Score 的 5 维（板块/封单/量能/情绪/技术）是**龙头打板专用**，覆盖率仅 50-60%。龙头 edge 来自封单+板块共振；非龙头 edge 来自量能节奏/回调结构/预期差/竞价信号。**edge 来源不同 → 不可共用同一维度集**。

若实现时每战法硬编码自己的维度+权重+sweep 范围 → ad-hoc 分叉、维护爆炸、DRY 违反。

**设计**：声明式 registry——每战法 DECLARE 自己的维度集+权重+edge_type+sweep 参数，框架从声明计算 composite + 跑 sweep。参数差异是 declared data 非 hardcoded logic。

## 2. Dimension 数据结构

```python
@dataclass(frozen=True)
class Dimension:
    name: str
    data_source: str           # module:function 或 table:column（已核实存在）
    normalization: str         # 归一化到 [0,1] 的方法
    sweep_range: list[float]    # sensitivity sweep 值（S204 R13 sweep harness 用）
    overfit_risk: str           # high/medium/low
    applicable_战法: tuple[str]  # 哪些战法用此维度（None=ALL）
    notes: str                  # 口径说明（如封单"竞价口径 vs 全天口径"）
```

## 3. DIMENSION_REGISTRY（共享 + per-战法特有）

### 3.1 共享核心 5 维（S203 龙头，部分适用其他战法）

| 维度 | data_source（已核实） | 归一化 | sweep_range | overfit | 适用战法 |
|---|---|---|---|---|---|
| 板块强度 | sector_cycle.py:165 zt_count_today + sector_divergence.py:314 | zt_count_today/全市场涨停均值封顶1.0 | [2,3,5,10](top-N 门槛) | 中 | 龙头/接力/一字竞价/弱转强/N字(部分)/低吸(改口径) |
| 封单强度 | GeneScore models.py:50 seal_to_float_ratio + intraday_features.py seal_slope | seal_to_float_ratio/0.005 封顶1.0+seal_slope 正则 | [0.003,0.005,0.007,0.010] | 高 | 龙头/接力/一字竞价(改竞价口径) — **非打板策略不适用**（低吸/N字/形态反包须替换）|
| 量能确认 | pattern_scan.py:37 volume_breakout_ratio + relay_vol_ratio(新增) + 换手率(涨停池 raw) | relay_vol_ratio/2.0 封顶1.0+换手率合理性扣分 | [1.0,1.5,2.0,2.5,3.0] | 高 | 龙头/接力/N字/形态反包 — **一字竞价不适用**（缩量是强信号非放量确认，逻辑冲突）|
| 情绪周期 | limitup_sti/models.py:63 STI score(5-phase+7维) + market.py:166 连板梯队 | STI score/100 | (regime conditioner 非 sweep，但须验证三态预测力) | 极高 | ALL（但 STI 退潮/高潮实测 0 天，MVP 用连续 score 不硬分三态，标探索性）|
| 技术形态 | MA5/MA10(baostock 可算) + K线形态吞没/上影(OHLCV) + shadow_length_pct(pattern_scan) + ma5_slope | MA 排列+形态命中数/3 | [实体涨幅 X%: 2/3/4/5] + [N日高点 lookback: 10/20/30] | 中 | ALL（形态反包升至 25%权重）|

### 3.2 per-战法特有维度（S205 新增，龙头不需要）

| 维度 | data_source | 适用战法 | overfit | 说明 |
|---|---|---|---|---|
| **竞价信号** (auction_signal) | 量比/竞价额占流通市值比/订单失衡度OI/9:20 不可撤单后封单稳定性 | 一字竞价/弱转强 | 高 | baostock 无，须 Tushare stk_auction 或 hithink（付费，用户决策）|
| **回调结构** (pullback_structure) | 回调深度比/天数/不破首板起涨点/突破前高确认 | N字/低吸龙头 | 中 | pattern_scan.py 有 compute_consolidation（横盘）但无回调检测，须新增 |
| **量能节奏** (volume_rhythm) | 首板倍量→缩量→再放量三段连续性评分 | N字 | 高 | pattern_scan compute_volume_breakout 是单点量比，不覆盖三段节奏，须新增 |
| **预期差反包** (expectation_gap_reversal) | 竞价高开幅度+竞价量（弱转强）/ close 突破上影中点+吞没程度+放量倍数（形态反包）| 弱转强/形态反包 | 高 | 反包确认强度综合 |
| **龙头确认** (leader_identity) | sector_rank≤3/lbc≥2/high_gene/板块领涨 | 低吸龙头 | 中 | 当前低吸卡名含龙头但入场条件完全未验标的，须加 |
| **回调节奏** (pullback_rhythm) | 距上次涨停3-5日/回调幅度20-30%/是否第一次回调 | 低吸龙头 | 中 | 须新增 |
| **反包确认强度** (reversal_confirm) | close[T+1] 距 Day T high 突破幅度/吞没程度/放量倍数综合 | 形态反包/弱转强 | 中 | 须新增 |

## 4. 战法ScoreConfig（per-战法声明）

```python
@dataclass(frozen=True)
class 战法ScoreConfig:
    战法: str
    dimensions: tuple[str]          # 用哪些维度（从 REGISTRY 选）
    weights: dict[str,float]       # dim→权重，sum=1.0（先验固定，非回测拟合）
    edge_type: str                 # selection/event/path/overnight_gap（须 window sanity 验证，非预设）
    sweep_params: dict[str,list]   # param→range（sensitivity sweep，从 DIMENSION.sweep_range 或自定义）
    cost_model: str                # Vibe _cost_pct 0.15（统一，决策#cost）
```

### 4.1 S203 龙头 3 sub 配置

```python
龙头 = 战法ScoreConfig(
    战法="龙头",  # 首板 dragon_head
    dimensions=("板块强度","封单强度","量能确认","情绪周期","技术形态"),
    weights={"板块强度":0.25,"封单强度":0.25,"量能确认":0.20,"情绪周期":0.15,"技术形态":0.15},
    edge_type="selection",  # 须 window sanity 验证（决策#7 两者都做）
    sweep_params={"seal_to_float_ratio":[0.003,0.005,0.007,0.010],
                  "relay_vol_ratio":[1.0,1.5,2.0,2.5,3.0],
                  "sector_top_n":[1,3,5,10]},
    cost_model="vibe_0.15")
# 接力二三板：同 dimensions，sweep 加 lbc 门槛 [2,3,4]
# 反包 leader_drop_reversal：edge_type=event，dimensions 换（封单→反包确认强度，板块→技术形态25%）
```

### 4.2 S205 5 战法配置（下轮，研究 workflow 给的 per-战法映射）

| 战法 | dimensions | weights 草案 | edge_type（须验） | sweep_params |
|---|---|---|---|---|
| 一字竞价 | 竞价信号+封单(竞价口径)+情绪周期+技术形态 | 竞价0.30/封单0.25/情绪0.20/技术0.25 | event（待验） | 竞价高开[2/3/5/7%]+封单[0.3-1.0%] |
| 弱转强 | 预期差反包+量能确认+情绪周期(↑25%)+技术形态+板块 | 预期差0.25/量能0.20/情绪0.25/技术0.20/板块0.10 | overnight_gap（待验） | 竞价量[1.0-3.0x]+换手[5/10/15/20%] |
| N字反击 | 量能节奏+回调结构+技术形态+情绪周期+板块(部分) | 量能节奏0.30/回调0.25/技术0.25/情绪0.10/板块0.10 | selection（待验） | 三段量比+回调深度[10/20/30%]+回调天[1/2/3] |
| 低吸龙头 | 技术形态(核心)+龙头确认+回调节奏+量能(反转)+情绪+板块(改口径) | 技术0.30/龙头0.20/节奏0.20/量能0.15/情绪0.10/板块0.05 | path（待验） | MA 回踩[5/10/20日]+回调幅度[10/20/30%] |
| 形态反包 | 技术形态(↑25%)+量能确认+反包确认强度+情绪(部分)+板块(↓15%) | 技术0.25/量能0.20/反包0.25/情绪0.15/板块0.15 | event（待验） | 上影[3/4/5/6%]+放量[1.0-2.5x] |

> ⚠️ edge_type 全部标"待验"——决策#7 window-sanity 两者都做，须先跑 window sanity 定位 edge 在哪个窗口再匹配 edge_type，**不能预设**（§44v2 rule①，防 v1 错窗口灾难）。
> ⚠️ weights 是草案先验（非回测拟合），但 25/30 等是 round numbers，标 overfit 风险——sweep 后若调权重=过拟合（R10 overfit_risk）。

## 5. Sensitivity Sweep 参数空间（S204 R13 harness 用）

```python
SWEEP_PARAMS = {
    # 封单
    "seal_to_float_ratio": [0.003, 0.005, 0.007, 0.010],
    # 量能
    "relay_vol_ratio": [1.0, 1.5, 2.0, 2.5, 3.0],
    "volume_breakout_ratio": [1.0, 1.2, 1.5, 2.0, 2.5],
    # 板块
    "sector_top_n": [1, 3, 5, 10],
    "sector_zt_count_min": [2, 3, 5],
    # 大跌（反包）
    "leader_drop_pct": [0.05, 0.07, 0.10],
    # 竞价
    "auction_open_pct": [0.02, 0.03, 0.05, 0.07],
    "auction_volume_ratio": [1.0, 1.5, 2.0, 2.5, 3.0],
    # 回调
    "pullback_depth_pct": [0.10, 0.20, 0.30],
    "pullback_days": [1, 2, 3, 5],
    # 形态
    "shadow_length_pct": [0.03, 0.04, 0.05, 0.06],
    "entity_pct": [0.02, 0.03, 0.04, 0.05],
    "ma_lookback": [10, 20, 30],
}
```

### Overfit 检测规则（sweep harness 输出）

```
对每战法每 sweep_param:
  对 range 内每个值 v: 跑 §44 wire_verdict → 记 verdict(status, lift, n)
  IF edge(status=robust_edge, lift>=2.0) ONLY at 单一 v 且邻近值无 edge → 标 overfit（data-snooped）
  IF edge 在多个邻近 v 都成立 → edge 稳健（非 overfit）
  IF 无 v 出 edge → 该维度无 selection edge（不进融合，§44v2 不外推）
```

> 决策#2 三参数都扫（龙头）；S205 各战法按其 sweep_params 扫。
> ⚠️ sweep 本身是多重检验（每参数4-5值×多维×多战法）——Bonferroni K 须含 sweep 次数（决策#9 拆≤8 + #10 去重等价）。K 冻结 pre-registration（§44v2 rule③）。

## 6. Composite 计算（非 ML，对齐 [[weight-as-ml-feature-is-inert]]）

```python
def dragon_score(战法_config, code, trade_date, indicators):
    score = 0.0
    for dim_name, weight in 战法_config.weights.items():
        dim = DIMENSION_REGISTRY[dim_name]
        raw = read_indicator(indicators, dim.data_source, code, trade_date)
        normalized = normalize(raw, dim.normalization)  # → [0,1]
        score += normalized * weight
    return score * 100  # → 0-100

# 分数本身是选股排序依据，不是喂模型的特征。
# 若分数喂回 gene_score 或 scoring.py 参与排序 → 检查是否间接进 ML（验证器 HIGH，须 guard）
```

## 7. edge_type 声明 + window sanity 验证流程（决策#7）

```
1. 战法_config.edge_type 是 INITIAL 假设（非定论）
2. 跑前: compute 3 windows (overnight_gap / D+1_intraday / path) for survivors vs universe
3. 定位: 哪个窗口 lift 最高 + mean>0 = edge 在哪
4. IF 胜出窗口 != edge_type 匹配窗口 → 调 edge_type 匹配胜出窗口（harness 层）
5. wire_verdict(edge_type=调整后值, ...)
6. verifier R5 查 ALL 窗口（双保险，决策#7）——任一有优势进重方法论，全无才 exploratory
```

> 防 §44v1 错窗口灾难。edge_type 是**验证后**的结论，不是预设。

## 8. 参数差异分叉——已 declared，实现不分叉

| 分叉类型 | 声明式处理 | 实现时 |
|---|---|---|
| 维度集不同（龙头用封单，低吸不用）| 战法_config.dimensions 声明 | framework 按 config 取维度，无 if-else |
| 权重不同（形态反包技术25% vs 龙头15%）| 战法_config.weights 声明 | framework 按权重加权 |
| edge_type 不同（4 种）| 战法_config.edge_type 声明（+window sanity 验证）| wire_verdict 按声明走 |
| sweep 范围不同（封单 vs 量能 vs 板块）| DIMENSION.sweep_range + 战法_config.sweep_params 声明 | sweep harness 按声明迭代 |
| cost 不同 | 战法_config.cost_model 声明（统一 vibe_0.15）| _cost_pct 按声明 |

→ 实现时**零 ad-hoc 分叉**：加新战法 = 加一个 战法ScoreConfig entry，不动 framework。

## 9. 受影响文件（实现时）

| 文件 | 改动 |
|---|---|
| `backend/strategies/dimension_registry.py`（新建）| Dimension + DIMENSION_REGISTRY + 战法ScoreConfig + 战法_CONFIGS |
| `backend/strategies/dragon_score.py`（新建）| dragon_score() composite 计算（非 ML）|
| `backend/tools/sensitivity_sweep.py`（新建，S204 R13）| sweep harness（按 SWEEP_PARAMS 迭代 + overfit 检测）|
| `backend/strategies/cards/*.yaml`（每战法）| reference 战法ScoreConfig（或 config 在 registry）|

## 10. 待定（下轮 S205 分叉，提前列）

- 竞价数据源（Tushare/hithink/跳过）——付费用户决策
- 形态反包跨日 bug（先修 vs 重写）
- N字检测（新建 n_shape_detector vs 组装 pattern_scan）
- 低吸 C3 缩量（重定义重测 vs 放弃）
- §44 顺序（先修 S204 blocker vs 并行）

这些是 S205 的分叉，本轮 pre-design 不锁，但 registry 结构已支持任一选择（维度声明式，加维度不改 framework）。
