# Spec: S161 — §44v2 验证框架（wire backtest-overfit + 合并 verifier + Recorder）

> 状态：草案 v2（S160 component 1，priority 1，design-agnostic + edge-independent）
> 关联：S160 / S159 / s44-quant-validation-loop / s44-v1-wrong-window-retrospective / methodology-window-before-no-edge-conclusion / vendor/skill-backtest-overfit/SKILL.md
> 分级：medium（新 verifier 模块 + wire skill + 合并 harness + gap run + lift_to_multiplier 接线）—— issue 层单轮 review，免 feature 分支（design-agnostic 不碰生产选股）
> v2 修订：经 8-lens spec-grill（45 holes/37 real/8 refuted）修 PBO N=1 空壳 / Bonferroni K=20 over-correction / DSR lenient 静默 / gap=event-edge vs selection verdict category mismatch / Recorder 数据态不锁 / gap 数据链错描 / lift_to_multiplier 未接线 / n<60 vs R6 矛盾。

## 0. 问题

§44v2 方法论 sound（day_paired+permutation+Bonferroni+walk-forward）但散落 `backend/tools/` 脚本 + PBO/CSCV/DSR/Harvey/purged-kfold 全仓 0 实现（grill #6，grep 0 命中）+ gap 14 天 naive 池化无重方法论（grill #1，gap_window_lift.py 仅 statistics.mean+per-T quintile）。需要单一 design-agnostic verifier（测试任何候选 edge 的判定器，不依赖 gap）+ wire backtest-overfit skill + qlib Recorder 实验追踪。

**spec-grill 抓到的 §44v1-class 方法论 bug（v2 修）**：①PBO 需 N≥2 矩阵，gap run N=1 单策略 → 结构性 N/A，spec 却称"wire PBO"是空壳；②Bonferroni K=20（引 §44v1 因子数）vs R6 小 n→BH——§44v1 over-correction 重犯，42 天 α_adj=0.0025 近不可能显著；③DSR 漏 sr_variance → lenient 单估计静默降级（代码自警 lower bound）；④gap 是 event edge（薄+不可选），verdict 用 lift（selection）测它 = category mismatch + 外推风险；⑤Recorder frozen_commit 只锁代码不锁数据（前复权 kline + first_board_premium_baseline.json 可变）；⑥§3 n<60 vs R6 n<200 picks 或 days<60 矛盾，gap 2700 picks 不触发 §3 但 days=42<60 该 underpowered，可能误判证否；⑦lift_to_multiplier 从没被生产调用（只测试），生产读冻结 weight_multiplier（窗口偏差值仍生效），"REGISTRY 改标"是 lipstick。

## 1. 目标

建 §44v2 验证框架为 design-agnostic 模块——给定 return series + n_trials + 可选 trials_matrix → verdict（robust_edge / underpowered / falsified / not_validated / exploratory）。wire `vendor/skill-backtest-overfit`（DSR/PBO/CSCV/purged-kfold/haircut）+ 合并 `backend/tools/` 散落 day_paired_lift+permutation+Bonferroni+walk-forward + qlib Recorder 实验追踪（落盘 n_trials 喂 DSR）。López de Prado "alpha assembly line" 的验证 gate。

design-agnostic 成立：验证统计量对任意 return series 算法一致，不关心 entry 怎么生成（gap close→next-open vs selection open→exit 都喂得进）。**但 verdict 须区分 edge_type**——selection edge（因子选股力）与 event/population edge（gap 薄事件）是不同假设，不能混用 lift 阈值（§44v1 外推教训）。

## 2. 需求清单

- **R1 verifier 签名**：`verify(returns: pd.Series, n_trials: int, trials_matrix: pd.DataFrame|None = None, periods_per_year: int = 252, window_sanity: dict|None = None) -> Verdict`。纯函数，不可变。
  `Verdict` dataclass = {
  - `status`: Literal["robust_edge","underpowered","falsified","not_validated","exploratory"]  # v2 加 not_validated（[1,2)-lift+sufficient n/days，如 platform_breakout/low_absorption）
  - `edge_type`: Literal["selection","event","population"]  # v2 加——区分 selection vs event edge，治外推
  - `tradeable`: bool  # v2 加——机器可读"不可交易"（接 S162 gap 不可交易），区别"无 edge"
  - `selection_lift`: float|None  # v2 rename lift→selection_lift（显式标 selection 度量）
  - `event_metrics`: {mean_return, net_mean, win_rate, t_stat_day_clustered, n_event, base_rate}|None  # v2 加——event edge 用 t-test/二项非 lift
  - `event_status`: Literal["event_robust","event_thin_positive","event_falsified","event_not_tested"]|None  # v2 加——event 子结论独立于 selection status
  - `ci_low`, `ci_high`: float|None  # S161 新增，S151 REGISTRY 无（mock null + "待 v2 verifier 跑出"灰底）
  - `p_bonferroni`, `p_bh`: float|None  # v2 加 p_bh（小 n 用 BH 非 Bonferroni）
  - `dsr`: float|None, `dsr_method`: Literal["cross_trial_variance","lenient_single_estimate","N/A"]  # v2 加 dsr_method——透明标 lenient 降级
  - `pbo`: float|None  # N/A when trials_matrix None or N<2；PBO 仅多配置 factor mining N≥10，单 edge 如 gap N=1 结构性 N/A
  - `haircut`, `min_trl`: float|None
  - `days_robust`: int, `n`: int  # n=raw picks（非 effective day-clusters）
  - `n_effective`: int|None  # v2 加——day_paired effective n（derived，非 Verdict.n），消除 n 歧义
  - `frozen_commit`, `updated_commit`: str|None, `updated_at`: str|None  # v2 加 updated_*——回溯后覆盖（接 S165 R1，DimensionValidation docstring 已承诺 updated_* 路径）
  - `data_snapshot_id`: str|None  # v2 加——as_of/PIT bundle-id（接 S162 pit_store），治数据态不锁
  - `note`: str
  }

- **R2 wire backtest-overfit**：import + 适配层接 `vendor/skill-backtest-overfit/scripts/`：
  - `deflated_sharpe.py`（DSR/PSR/MinTRL）：trials_matrix=None → lenient 单估计降级（deflated_sharpe.py:160-168 代码自警 "lower bound, makes DSR lenient"），**Verdict.dsr_method 须透明标 `lenient_single_estimate`**（R4 Recorder 同步落盘）——治"少报 n_trials=自欺"的同等坑：漏 trial Sharpes 同样骗。
  - `pbo_cscv.py`：**pbo=None when trials_matrix is None or N<2**（pbo_cscv.py:88 `if N<2: raise ValueError`，verifier 捕获→N/A 非 crash）；PBO 仅适用多配置 factor mining（N≥10），单 edge 如 gap N=1 结构性 N/A（UI 标 "N/A (single-strategy)" 区别 "待建 (not-yet-wired)"）。
  - `purged_kfold.py`：wire **`PurgedKFold.split()`（splitter，yield train/test indices）** 非 `cross_val_score_purged`（后者需 sklearn estimator fit()/score()，§44 无 ML 模型，cross_val_score_purged 不可用）；split() 增强既有 walk-forward 的时序 OOS 切分（互补非重复，purge label-overlap + embargo post-test）。
  - `haircut.py`（Bonferroni/Holm/BHY 多重检验）。
  - acceptance：**grep `.split(` 在 verifier walk-forward/OOS path 被调用**（非裸 import；S153 v1 臆造引用教训——bare `from ... import PurgedKFold` 不通过 gate）。

- **R3 合并 §44v2 harness**（两 script 集**分离**，治 grill reuse_rot lens 证"9 脚本=合并源"混淆）：
  - **Parameterize-ROOT 集**（~10 脚本含硬编码绝对路径 `Vibe-Research-S151`，需改 VR_DATA_DIR）：lianban_lift, gap_window_lift, overnight_gap_decomposition, valuation_pe_lift, pead_event_study, index_ma20_regime_fetch, zt_pool_seal_time_lift, miaoban_superset_31d_lift, block_trade_lift, index_ma20_regime_lift。
  - **Merge-source 集**（~12 脚本含 day_paired|permutation|bonferroni|walk_forward，合并进 verifier）：platform_breakout_lift, first_plate_h2_lift, block_trade_lift, _event_lhb_probe, low_absorption_c3_lift, pead_event_study, first_board_layer_lift, lockup_lift, index_ma20_regime_lift, lianban_lift, multifactor_combo_test, multifactor_combo_validation。
  - 交集（4）：lianban, pead_event_study, block_trade_lift, index_ma20_regime_lift。
  - **walk-forward 唯一源**（spec 必须点名，否则 R3 walk-forward 不可实现）：platform_breakout_lift, multifactor_combo_test, multifactor_combo_validation, low_absorption_c3_lift（均不在硬编码-ROOT 集）。
  - 合并 day_paired_lift（非池化，按日聚类 effective n）+ within-day permutation null_p95（survivor resampling）+ Bonferroni/BH（全局+per-family，按 n 调）+ walk-forward（true OOS 或显式标冻结非 OOS）→ verifier 内部组件。保留 `backend/tools/` 脚本作 CLI wrapper（不删，参数化 ROOT）。

- **R4 qlib Recorder 实验追踪**（v2 pin 数据态非仅代码）：
  落盘「data_snapshot_id（= as_of/PIT bundle-id，接 S162 pit_store）+ 输入查询 spec（date range, code universe, DB 表/源）+ 全 input artifact content hash（baostock_kline_cache subset + first_board_premium_baseline.json + gene_scores rows）+ **完整 return series（非仅 hash——hash 单向 verify-but-not-regenerate，qlib Recorder save_objects 存全系列）** + params + n_trials + trials_matrix 存在性+hash + dsr_method + frozen_commit + verdict + timestamp」一条 recorder_id。
  **两条复现判据**（spec 原混淆）：(a) verdict-reproducibility = 从 STORED 全系列重算（确定性，恒成功）；(b) data-revalidation = 从 pinned as_of PIT bundle 重导 series + hash 比；不匹配 → 诚实标"前复权重算（corporate action 后），原 verdict 基于 as_of 数据，需 re-baseline"非假绿。
  前复权 mutation（baostock adjustflag='2' retroactively 可变）：PIT bundle 在 ingest 时 snapshot 前复权系列 as_of，**同 as_of 永不 re-fetch**（first_board_premium_baseline.py:126 + refresh_kline_cache.py:51 均 adjustflag='2'）。SQLite 或 JSON 落 `.vibe-research/verifier_recorder/`。

- **R5 前置窗口 sanity（S159 §5A authoritative，enforced 非 advisory）**：verify 前多窗口对比（隔夜 gap / D+1 日内 / path 的 **mean+中位+胜率+base_rate**，S159 §5A 口径，**不算 lift/IC**——window sanity 是轻定位非 lift/IC 计算；IC 属 post-sanity verifier 步 R3 day_paired_lift + §3 gap run）。无窗口优势 → 标 "exploratory" 不上重方法论（治 §44v1 错窗口根因）。

- **R6 n 门槛（S159 R2）**：**n<200 picks 或 days_robust<60 → 标 "underpowered" 不判 "劣于随机/证否"**。**证否须 days_robust≥60 且 selection_lift<1**（gate，消除 §3 "n<60" 歧义致 gap 误判证否）。Bonferroni/BH 按 n 调：小 n（<60 天）→ BH（Benjamini-Hochberg），大 n（≥60 天）→ Bonferroni K=6-8，**单 edge 假设 K=1 或小 K（gap 变体数），绝不引 §44v1 的 ~20 因子数（不同 testing family：selection vs event-edge）**。

- **R7 不外推 + edge_type 结构化**：verdict 只覆盖所测窗口+所测 edge_type，不外推"无 edge"。**selection-falsified verdict（edge_type=selection, status=falsified）须带 note "selection falsified; population event edge may exist (see event verdict)"**，S165 UI 须以 edge_type 作主 scoping 标签旁 status——selection-falsified 永不被读成"gap 无 edge"。gap 标 hypothesis 非 verified。

- **R8 lift_to_multiplier 接线生产**（CLAUDE.md §1.2 P0，治 grill honesty/reuse_rot lens 证"REGISTRY 改标是 lipstick"）：
  - `candidate_funnel/evaluation.py` lift_to_multiplier 加 `days_robust` 参数；**days_robust<60 → provisional cap ×0.5**（非 ×1.0 全权重，CLAUDE.md §1.2：seal_amount days=5 不该 ×1.0）。
  - 接线 `_apply_evaluation_layer`（evaluation.py:199/205 替代直读 frozen `weight_multiplier`）+ `strategy_funnel_registry.py:434`（替代 `DIMENSION_LIFT_REGISTRY["gene_score"].weight_multiplier` 直读）——这是 CLAUDE.md §1.2 P0 "lift_to_multiplier 接线生产（替代直接读冻结 weight_multiplier）"。
  - 调和生产 "validated" 标签与 verifier "robust_edge"（DSR>0+Bonferroni+days≥60）；勿留两套不一致判据（gap 42 天 run 否则 verifier 说 underpowered 而 lift_to_multiplier 说 validated ×1.0）。

## 3. gap §44v2 run（priority 1 应用，验证 gap 是否 edge）

- 现 `backend/tools/gap_window_lift.py` 14 天 naive 池化（statistics.mean + per-T quintile + 一个 pearson placeholder，无 day_paired/permutation/Bonferroni/walk-forward）。
- **诚实数据链**（v2 修，治 grill data_repro/feasibility lens 证"baostock kline_cache"错描）：
  - gap return series 读自 **pre-computed `first_board_premium_baseline.json`**（gap_window_lift.py:27/48 `net_gap = premium - COST`），**非 baostock kline_cache 直接**（kline_cache 仅一字板 filter，gap_window_lift.py:43-47）。
  - 扩 14→42 天 = **re-run `backend/tools/first_board_premium_baseline.py --days 42`**（读 gene_scores.db eastmoney_live dates + **em_zt_topic_pool**（东财涨停池，astock.py:243 / data/sources/eastmoney.py:183）per-date + baostock kline → regenerate baseline.json ~42 天样本）。**非 ths_limit_up_pool**（同花顺，lianban_lift 用，不同源不同 universe）。
  - 再跑 gap_window_lift.py on regenerated baseline。
  - Recorder pin baseline provenance（content hash of first_board_premium_baseline.json + generation params {days_back, pool_source, date_range, generator_commit}）。
  - 口径 mismatch（first_board_premium_baseline.py:264 T close from zt_pool raw price unadjusted vs T+1 open from baostock 前复权 line 270）：split 间 distort premium，须一致化（both adjusted or both raw）非仅复现。
- **gap 是 event edge 非 selection edge**（v2 修，治 grill honesty lens）：gap run 须出 **两个独立 verdict**：
  - **population event-edge verdict**（全涨停 gap return series vs base rate，K=1，DSR n_trials=1，edge_type=event）——回答 §3 标题"验证 gap 是否 edge"，用 **day-clustered one-sample t-test（mean gap>0 after costs?）+ binomial（WR>50%）**，**非 lift/permutation/Bonferroni（测 selection）**。Materiality floor：day_mean 须 > `_EVENT_MATERIALITY_FLOOR`（0.003=0.3%）以区分 "robust" 与 "thin positive"——统计显著但净收益 <0.3% 不算 robust（spec 原 line 83 mean>0 更新为 mean>0.3% with rationale：0.3% 是 minimum net-of-cost day-mean，低于此则噪声/薄正信号非 robust；cost-relative override `floor=max(0.003, cost*0.5)` 使高 cost 场景更保守）。
  - **selection verdict**（K=small BH，edge_type=selection）——回答"因子能否选哪个涨停 gap 更大"（已知 gene_score lift 0.942x falsified）。
  - "gap 是否 edge"由 **population event verdict** 答，**非 selection verdict**。
- **42 天结构性 underpowered**：days_robust=42<60 → R6 gate → **expected verdict = underpowered，NEVER robust/证否**（spec 早已设计 line 32/33，非缺失分支）。walk-forward 42 天 0 窗（platform_breakout_lift.py WALK_TRAIN=100+TEST=20）→ 优雅降级标 "walk_forward: insufficient data, skipped" 非静默空。
- Bonferroni/BH K = gap 实测假设数（K=1 单 edge 或小 K 变体），**绝不引 §44v1 ~20 因子数**（不同 family）。DSR n_trials=20（§44v1 path factors）作**唯一跨实验 data-snooping 校正**，justify 为 judgment 非 silent inherit（n_trials=20 跨窗口属不同 family 是可辩护的，但须文档化）。
- gap capture/intraday defer 到方向层（60 天 live 积累，非 NOW）。
- Chen2017 nuance：gap 是大户的不可复制，但 retail 可 intraday 打板捕获（非完全不可复制）——prior 倾向薄/难，但 verify via 基建（便宜，daily-bar NOW）。

## 4. 受影响文件

- 新建 `backend/s44_verifier/verifier.py`（verifier 主模块 + Verdict dataclass + verify() 纯函数 + event_metrics sub-dataclass）。
- 新建 `backend/s44_verifier/recorder.py`（qlib Recorder 模式实验追踪 + data_snapshot_id pin + 两复现判据）。
- 新建 `backend/s44_verifier/wiring.py`（适配层 import vendor/skill-backtest-overfit/scripts/：DSR lenient flag + PBO N/A guard + PurgedKFold.split() wire）。
- 合并 `backend/tools/` Merge-source 集 12 脚本的 day_paired+permutation+Bonferroni/walk-forward 进 verifier（见 R3 两集分离；脚本保留作 CLI wrapper）。
- 改 `backend/tools/` Parameterize-ROOT 集 10 脚本（见 R3）：`vr_paths.resolve_data_dir()`（VR_DATA_DIR，已含 .vibe-research，改 `DATA_DIR/X`）或 `Path(__file__).resolve().parents[2]`（repo root，须 `ROOT/'.vibe-research'/X`）——**两者非互换**，不硬编码绝对路径 Vibe-Research-S151。
- 改 `backend/tools/first_board_premium_baseline.py`（加 days_back 参数化 + pool_source 决策 em_zt_topic_pool + 口径一致化 adjusted/raw）。
- 改 `candidate_funnel/evaluation.py`（lift_to_multiplier 接线生产：加 days_robust 参数 + days<60→×0.5 + 接 _apply_evaluation_layer:199/205 + strategy_funnel_registry:434）。

## 5. 验收标准

- [ ] R1 verifier 签名 + Verdict dataclass（含 edge_type/tradeable/event_metrics/event_status/dsr_method/not_validated/n_effective/updated_*/data_snapshot_id）+ 单测（AAA pattern）。
- [ ] R2 DSR（lenient 透明标 dsr_method）+ PBO（N<2→N/A 非 crash）+ PurgedKFold.split()（非 cross_val_score_purged）+ haircut wire；acceptance = `.split()` 调用非裸 import。
- [ ] R3 day_paired+permutation+Bonferroni/BH+walk-forward 合并进 verifier（两集分离 + walk-forward 源点名）；backend/tools/ 脚本 CLI wrapper + ROOT 参数化。
- [ ] R4 Recorder 落盘（data_snapshot_id + 全 input hash + 完整 return series + 两复现判据）；前复权 as_of snapshot 不 re-fetch。
- [ ] R5 窗口 sanity enforced（mean+中位+胜率+base_rate，不算 lift/IC；无窗口优势标 exploratory）。
- [ ] R6 n 门槛 enforced（n<200 或 days_robust<60 标 underpowered；证否须 days≥60 且 selection_lift<1；BH 小 n / Bonferroni K=6-8 大 n，单 edge K=1 非 §44v1 的 20）。
- [ ] R7 edge_type 结构化（selection-falsified 带 note + S165 UI edge_type 主标签）。
- [x] R8 lift_to_multiplier 接线生产（days<60→×0.5 + _apply_evaluation_layer + strategy_funnel_registry 替代直读冻结）。
- [ ] gap §44v2 run（re-run first_board_premium_baseline.py --days 42 → 两个 verdict：event population K=1 t-test + selection K=small BH）→ 42 天结构性 underpowered，落 Recorder。
- [ ] pytest 单测全绿 + gap run 两复现判据（verdict-reproducibility 恒成功 + data-revalidation as_of hash 比）。

## 6. 合规与工程底线自查

- [x] 不臆造：verifier 实算（DSR/PBO/CSCV 公式从 backtest-overfit skill + López de Prado 文献），禁心算禁 naive 池化；gap 数据链诚实（baseline.json 非 kline_cache 直接；em_zt_topic_pool 非 ths）。
- [x] 私有数据隔离：Recorder 落盘写 .vibe-research 不进 git。
- [x] em_get 防封：gap run 用 baostock daily（无防封）+ em_zt_topic_pool 走 em_get 限流（非 ths_limit_up_pool）。
- [x] §44 降级参考性建议：verifier 是判定器非阻塞 gate（但 gap verdict 影响是否建 capture）。
- [x] verdict 外推禁令：gap 标 hypothesis，跑 §44v2 后才称 robust/证否；selection-falsified 带 note 不外推"无 edge"；edge_type 结构化。
- [x] 不闭门造车：wire backtest-overfit skill（开源）+ qlib Recorder 模式 + López de Prado/Chen2017 文献；spec-grill 8-lens 对抗验证修 37 真洞。

## 7. 分级

medium（新 verifier 模块 + wire skill + 合并 harness + gap run + lift_to_multiplier 接线）。issue 层单轮 review。免 feature 分支（design-agnostic，不碰生产选股）。spec-grill 已过（v2 修 37 真洞），实现后跑 gap run sanity 验（两 verdict + 42 天 underpowered 预期）。
