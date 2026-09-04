# Spec: S153 — 量化模型验证（platform_breakout + low_absorption 预注册交互假设）

> 状态：草案 v2（T1.2 审查 workflow 12 agent adversarial verify 修 4 CRITICAL+2 HIGH，待实现）
> 作者：Claude  日期：2026-09-04（v2 2026-09-05 审查修）
> 关联：S150（采集修复）、S145（§44 path）、S144（§44 测量地基）、[量化模型验证路线.md](../量化模型验证路线.md)

## 1. 问题 / 目标

§44 三层 verdict 证否"T-1 选股信号"（path_lift 0.978<1 劣于随机），但 12 战法 workflow 综合（49 agent）指出：platform_breakout/dragon_head/first_plate 排前因"§44 无效判定不直接覆盖它们"（未测≠有 edge）。专家共识：因子叠加/语境要走**量化模型验证**（交互+regime+walk-forward+置换+Bonferroni+预注册），不是 debate。

**目标**：对 platform_breakout + low_absorption 两个日线可得的战法，预注册 3-5 交互假设冻结后，用 walk-forward + day-cluster 置换 + Bonferroni 验证其交互项有无样本外 edge（path_lift>1 + 显著）。**不卡 intraday**（baostock 日线 167 日够，盘中只 4 天）。

## 2. 背景

- §44 已测单因子全<2x（gene rho≈0 / breakout 1.36 / momentum 1.83 / vol_surge 1.90 / 换手 0.9979 / 炸板封单 0.9897），8 因子组合 4.686x 是 day-cluster 池化假象（1.723x）
- **filter≠edge 是经验观察非数学定理**（T1.2 审查纠正：独立因子 lift 可乘积>2x 如 1.36×1.5=2.04）——不数学判死 H1-H4 交互，但仍需预注册验证
- platform_breakout：`consolidation_amplitude` 紧度因子 pattern_scan.py:341 已算但 match 未用（零成本接线）；§44 breakout 1.36x 可能混假突破拉低
- low_absorption：C3 缩量（vol_brk<1.0）mirror of platform C2 放量（>2）
- 验证管道复用：`first_board_layer_lift.day_paired_lift`（非池化）+ `kline_returns.simulate_holding`（path）+ `s145_sensitivity` fetch-once 模式
- 目标=持有收益 path（DEFAULT_PATH_PARAMS -3/+8/3，**显式不用** strategy 注册的 -5/+12/7）

## 3. 需求清单（R1-R10）

- [ ] R1 `compute_consolidation`（pattern_scan.py:297）改返 4-tuple (days, amplitude, max_high, min_low)；**max_high 须从 line 336 完整 consolidation_days 窗口捕获**（T1.2 CRITICAL2：line 318 是最后 min_days 子窗口的 max_high，非完整窗口，捕获错则 H2 平台顶错→survivor set 不可靠）。唯一生产调用方 scan_patterns:382
- [ ] R2 `PatternScan`（pattern_scan.py:36）加 `consolidation_max_high: float|None=None` 字段（frozen dataclass 默认 None 向后兼容）
- [ ] R3 `scan_patterns`（:382）适配 4-tuple 解包 + 存 consolidation_max_high
- [ ] R4 `PlatformBreakoutStrategy.match`（gene_based.py:268）加 C3 读 `pattern.consolidation_amplitude<=6.0`（预注册冻结值）；fired 改三条件全命中；C3 数据缺失→data_unavailable；condition_specs 加第3项
- [ ] R5 `LowAbsorptionStrategy.match`（gene_based.py:173）加 C3 读 `pattern.volume_breakout_ratio<1.0`（缩量，mirror of platform C2 放量>2）；condition_specs 加第3项
- [ ] R6 `kline_returns.py` 新增 `simulate_holding_with_confirm(bars, signal_date, cons_max_high, stop, tp, max_hold)` 包装：找 D+1 idx（signal_date=D+1，D 日选股后次日）→ **guard `idx+2>=len(bars)` 返 None**（T1.2 HIGH：绕过 simulate_holding:99 guard 致 IndexError）+ **`cons_max_high is None` 返 None**（compute_consolidation early return 致 TypeError）→ **确认 `bars[idx].high > cons_max_high`（D+1 收盘 high，收盘方知无 look-ahead）** → 调 `simulate_holding(bars, signal_date=D+1)` 入场 D+2 open（**T1.2 CRITICAL1 修：H2 重定义——D+1 收盘确认→D+2 入场，改持仓周期 D+2→D+3，无 look-ahead**）；不改原 simulate_holding
- [ ] R7 新建 `tools/platform_breakout_lift.py` 验证 harness：镜像 s145_sensitivity fetch-once + first_board_layer_lift.day_paired_lift；逐(D,D+1)切 `bars[:idx+1]`→scan_patterns→match→C3/tightness 子集→D+1 收盘确认（`bars[D+1].high>cons_max_high`）→simulate_holding(signal_date=D+1, DEFAULT_PATH_PARAMS -3/+8/3)→day_paired_lift+**permutation（新建，非"已有"）**+**rolling walk-forward（非单 60/40 split）**+Bonferroni（K=6-8，含 H3 子比较+regime subset）
- [ ] R8 新建 `tools/low_absorption_c3_lift.py`（同结构，替换战法为 C1(ma5_prox<=3)+C2(ma_bullish)+C3(vol_brk<1)；regime=MA20 斜率>0；params DEFAULT_PATH_PARAMS 不用 -5/+10/5）
- [ ] R9 预注册冻结：**spec 先 git commit 锁 commit hash**（T1.2 CRITICAL4：spec untracked 则预注册未生效，baostock cache+§44 结果已对作者已知，6.0 可能被 data peeking 污染）→ §5 阈值/params/regime/metric/对比组 commit hash 锁定后再跑 walk-forward test 段；禁事后调参（防 p-hacking），事后调参须标 post-hoc 降级探索性；**train 段不优化阈值**（T1.2 CRITICAL：train"定阈值"vs R9"跑数据前写死"矛盾——train 只用预冻结 6.0，不 grid-search）
- [ ] R10 测试：test_s086_strategy_impl 加 C3 hit/miss/data_unavailable（platform+low_absorption 各3组）+ simulate_holding_with_confirm guard（idx+2/None/真突破/假突破）；test_pattern_scan 适配 4-tuple + **max_high 从 line 336 完整窗口**（非 line 318）

## 4. 受影响文件

| 文件 | 改动 |
|---|---|
| backend/strategies/pattern_scan.py | R1-R3：compute_consolidation 4-tuple（max_high line 336 完整窗口）+ PatternScan 字段 + scan_patterns 解包 |
| backend/strategies/impl/gene_based.py | R4-R5：PlatformBreakout/LowAbsorption match 加 C3 |
| backend/strategies/kline_returns.py | R6：simulate_holding_with_confirm（signal_date=D+1 + guard + D+2 入场）|
| backend/tools/platform_breakout_lift.py（新） | R7：验证 harness（含新建 day_cluster_permutation + rolling walk-forward）|
| backend/tools/low_absorption_c3_lift.py（新） | R8：验证 harness |
| backend/tests/test_s086_strategy_impl.py + test_pattern_scan.py | R10：C3 测试 + 4-tuple + max_high line 336 + guard |

## 5. 设计方案

**预注册假设（H1-H4，事前冻结）**：
- **H1** platform_breakout 紧度（consolidation_amplitude<=6.0）path-winrate lift > raw（无紧度过滤）
- **H2 D+1 收盘确认**（T1.2 CRITICAL1 修，无 look-ahead）：D+1 收盘 `bars[D+1].high > consolidation_max_high` 确认突破（收盘方知）→ `signal_date=D+1` → simulate_holding 入场 D+2 open → path-winrate lift > raw（无确认）。**入场 D+2 open，持仓周期 D+2→D+3**（改原 D+1→D+2）。实盘可行：D 日盘后选股 → D+1 盘后收盘确认 → D+2 开盘买。
- **H3** 紧度+确认双过滤 lift > raw 且优于单独（H3 vs H1, H3 vs H2 子比较计入 Bonferroni）
- **H4** low_absorption C3 缩量（vol_brk<1.0）三条件交互（ma5_prox<=3 + ma_bullish + vol_brk<1）lift > raw

**目标变量**：path-winrate（signal_date=D+1, 入场 D+2 open, D+3 close 卖 or SL/TP/max_hold 触发，DEFAULT_PATH_PARAMS -3/+8/3；显式不用 strategy_params_for 的 -5/+12/7）

**regime**：H1-H3 bull（上证 sh.000001 close>MA20，逐信号日 gate，新建 helper）；H4 强势/震荡（MA20 斜率>0）。**H1-3 与 H4 regime 定义不一致须 spec 明确**（T1.2 疑点5）——H1-3 用 close>MA20（价格水平），H4 用 MA20 斜率>0（趋势方向），两者衡量不同，spec 标注分别冻结。

**验证 harness**：
- `day_paired_lift`（非池化，复用 first_board_layer_lift 防 4.686x→1.723x 池化假象）
- **`day_cluster_permutation` 新建**（T1.2 CRITICAL3：codebase 不存在）——**within-day survivor resampling** 建 null lift 分布（surv⊆raw 同 ret，逐日内随机选同大小子集当 survivor 重算 day_paired_lift，n_perm=2000 seed=42），observed lift 须在 null 分布 P95 以上。**null 模型选 within-day survivor resampling 非 date-shuffle**（R7-R8 设计 workflow 调查：filter-edge 锐检验是"随机同大小子集是否优于 observed survivor"，date-shuffle 与 day_paired_lift 去池化重复）。pre-register 冻结此 null 模型。
- **rolling walk-forward**（T1.2 CRITICAL3：非单 60/40 split）——按时间滚动 train/test（如 train 100 日→test 20 日→前移 20 日→再 train 100→test 20...），避 look-ahead + 提高功效（非单 18 日 test）。train 段**不优化阈值**（用预冻结 6.0），只算 observed+permutation null；test 段验。
- **Bonferroni K=6-8**（T1.2 HIGH：K=4 低估）——H1-H4 主比较 4 + H3 子比较 2（H3 vs H1, H3 vs H2）+ regime subset re-run 2 = K=8，α_adj=0.05/8=0.00625
- `bars[:idx+1]` 切片 gotcha（防 consolidation 按最后一根 bar 算错）
- **预注册 commit hash 锁定**（CRITICAL4）：spec git commit 后 hash 写入 R9，跑数据前锁定

**solo 审 6 疑点（T1.2 审查确认 5 真 1 伪）**：
1. H2 look-ahead（**最严重，CRITICAL1，已修：D+1 收盘确认→D+2 入场**）
2. H1 阈值 6.0 探索性（真，预注册冻结标探索）
3. Bonferroni K 不一致（真，已修 K=6-8）
4. walk-forward 样本量+预注册矛盾（真，已修 rolling + train 不优化）
5. regime MA20 先验+H1-3/H4 不一致（真，已标注分别冻结）
6. non_limitup_funnel:33 未用（**伪，爆炸半径安全**，grep count=0）

## 6. 验收标准

- [ ] A1 compute_consolidation 返 4-tuple，**max_high 从 line 336 完整窗口**（非 line 318），scan_patterns 解包无报错
- [ ] A2 PatternScan.consolidation_max_high 在 consolidation_days>=1 时有值
- [ ] A3 PlatformBreakoutStrategy.match C3(amplitude<=6.0) 命中 fired=True，未命中/缺数降级
- [ ] A4 simulate_holding_with_confirm：`idx+2>=len(bars)` 返 None（guard）+ `cons_max_high is None` 返 None + **D+1 收盘 `bars[idx].high>cons_max_high` 确认**（无 look-ahead）→ 调 simulate_holding(signal_date=D+1) 入场 D+2 open；假突破（D+1 high<=max_high）返 None
- [ ] A5 LowAbsorptionStrategy.match C3(vol_brk<1.0) 命中 fired=True
- [ ] A6 验证脚本跑通——day_paired_lift + **day_cluster_permutation（新建）** + **rolling walk-forward** + Bonferroni K=6-8 输出完整（observed_lift/p_value/alpha_adj=0.00625/verdict/is_significant）
- [ ] A7 预注册冻结——**spec git commit hash 写入 R9**，跑 test 段前不调参，train 不优化阈值
- [ ] A8 pytest -m "not live" 全绿（deselect newsradar/s032/s040 flaky）
- [ ] A9 诚实标注——无论显著与否如实报告 lift+p+verdict，不事后调参凑显著
- [ ] A10 bars[:idx+1] 切片 gotcha 在 harness 正确实现

## 7. 合规与工程底线自查

- [x] 不臆造：path return 从 baostock 日K 算（simulate_holding），禁心算，验证脚本可重跑
- [x] 私有数据隔离：gene_scores.db/baostock cache 在 .vibe-research/ 不进 git
- [x] em_get 防封：本 spec 不调东财端点，纯 baostock 日K
- [x] §44 规范：重算范式（不读结果 cache）；day_paired_lift 非池化；Bonferroni K=6-8；预注册 commit hash 锁定；**H2 无 look-ahead**（D+1 收盘确认→D+2 入场）
- [x] 弱合规：验证输出研究性判断，挂轻量风险提醒

## 8. 测试计划

- 单元：compute_consolidation 4-tuple（max_high line 336）+ PatternScan 字段 + scan_patterns 解包 + match C3 + simulate_holding_with_confirm guard（idx+2/None/真突破/假突破/D+1 收盘确认/D+2 入场）
- 集成：验证 harness 跑通（day_paired_lift + day_cluster_permutation + rolling walk-forward + Bonferroni K=6-8）
- 离线：pytest -m "not live" --deselect tests/test_newsradar_global_intel.py --deselect tests/test_s032_refresh_loop.py --deselect "tests/test_s040_backfill.py::test_run_backtest_async_passes_kline_cache"

## 9. 风险与回滚

- **T1.2 审查 4 CRITICAL 已修**：H2 look-ahead（D+2 入场）/ max_high line 336 / permutation 新建 / spec git commit
- **T1.2 审查 2 HIGH 已修**：R6 guard / Bonferroni K=6-8
- 风险：H1-H4 样本外 lift 全<1（交互也无 edge）→ 战法弃，转盘中验证（阶段2）
- 风险：rolling walk-forward test 段功效（167 日滚动，每窗 test 20 日 ×N 窗）→ 比单 18 日好但仍有限，接受探索性结论或等数据
- 风险：H2 D+2 入场改持仓周期——path 收益口径变（D+2 open→D+3 close or SL/TP），与 §44 原 D+1 open→D+2 close 不同，标注口径差异
- 回滚：compute_consolidation 4-tuple 向后兼容；match C3 不破坏 C1/C2；simulate_holding_with_confirm 不改原 simulate_holding

## 10. T1.2 审查 workflow 发现记录（12 agent adversarial verify）

**4 CRITICAL**：
1. H2 D+1 确认 look-ahead bias（`bars[idx+1].high` 收盘方知用于过滤但 entry `bars[idx+1].open` 开盘）→ **修：H2 重定义 signal_date=D+1 收盘确认→D+2 入场**
2. R1 max_high 捕获歧义（line 318 子窗口 vs line 336 完整窗口）→ **修：R1 明确 line 336 完整窗口**
3. permutation/walk-forward 代码不存在（spec 引用"已有"是假的）→ **修：R7 新建 day_cluster_permutation + rolling walk-forward**
4. spec untracked 预注册未冻结 → **修：R9 spec git commit 锁 hash**

**2 HIGH**：
5. R6 缺 idx+2/None guard → **修：R6 加 guard**
6. Bonferroni K=4 低估（H3 子比较+regime subset）→ **修：K=6-8, α_adj=0.00625**

**纠正**：filter≠edge 非数学定理（独立 lift 可乘积>2x），是经验观察——不数学判死 H1-H4 交互，但仍需预注册验证。

**solo 审 6 疑点**：5 真 1 伪（见 §5）。
