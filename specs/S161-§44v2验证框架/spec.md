# Spec: S161 — §44v2 验证框架（wire backtest-overfit + 合并 verifier + Recorder）

> 状态：草案（S160 component 1，priority 1，design-agnostic + edge-independent）
> 关联：S160 / S159 / s44-quant-validation-loop / vendor/skill-backtest-overfit/SKILL.md
> 分级：medium（新 verifier 模块 + wire skill + 合并 harness + gap run）—— issue 层单轮 review，免 feature 分支（design-agnostic 不碰生产选股）

## 0. 问题

§44v2 方法论 sound（day_paired+permutation+Bonferroni+walk-forward）但散落 `tools/` 脚本 + PBO/CSCV/DSR/Harvey/purged-kfold 全仓 0 实现（grill #6，grep 0 命中）+ gap 14 天 naive 池化无重方法论（grill #1，gap_window_lift.py 仅 statistics.mean+per-T quintile）。需要单一 design-agnostic verifier（测试任何候选 edge 的判定器，不依赖 gap）+ wire backtest-overfit skill + qlib Recorder 实验追踪。

## 1. 目标

建 §44v2 验证框架为 design-agnostic 模块——给定 return series + n_trials + 可选 trials_matrix → verdict（robust edge / underpowered / 证否）。wire `vendor/skill-backtest-overfit`（DSR/PBO/CSCV/purged-kfold/haircut）+ 合并 `tools/` 散落 day_paired_lift+permutation+Bonferroni+walk-forward + qlib Recorder 实验追踪（落盘 n_trials 喂 DSR）。这是 López de Prado "alpha assembly line" 的验证 gate。

design-agnostic 成立：验证统计量（day-paired lift / permutation null / Bonferroni / DSR / PBO）对任意 return series 算法一致，不关心 entry 怎么生成（gap close→next-open vs selection open→exit 都喂得进）。

## 2. 需求清单

- **R1 verifier 签名**：`verify(returns: pd.Series, n_trials: int, trials_matrix: pd.DataFrame|None = None, periods_per_year: int = 252, window_sanity: dict|None = None) -> Verdict`。`Verdict` dataclass = {status: Literal["robust_edge","underpowered","falsified","exploratory"], lift, ci_low, ci_high, p_bonferroni, dsr, pbo, haircut, min_trl, days_robust, n, frozen_commit, note}。纯函数，不可变。
- **R2 wire backtest-overfit**：import + 适配层接 `vendor/skill-backtest-overfit/scripts/`：`deflated_sharpe.py`（DSR/PSR/MinTRL，Bailey & López de Prado 2014）+ `pbo_cscv.py`（PBO via CSCV，Bailey et al. 2017，需 N≥10 trials matrix）+ `purged_kfold.py`（净化+禁运 K-Fold CV，López de Prado 2018 ch.7）+ `haircut.py`（Bonferroni/Holm/BHY 多重检验，Harvey & Liu 2015）。grep 非零接线（治 grill #6）。
- **R3 合并 §44v2 harness**：`tools/` 散落的 day_paired_lift（非池化，按日聚类 effective n）+ within-day permutation null_p95（survivor resampling）+ Bonferroni（全局+per-family，按 n 调）+ walk-forward（true OOS 或显式标冻结非 OOS）→ verifier 内部组件。保留 `tools/` 脚本作 CLI wrapper（不删，参数化 ROOT）。
- **R4 qlib Recorder 实验追踪**：每次 verify 落盘「输入快照（return series hash + params + n_trials + frozen_commit）+ verdict + timestamp」一条 recorder_id 可复现。喂 DSR 诚实 n_trials 前提（少报 n_trials = 自欺，DSR 错）。SQLite 或 JSON 落 `.vibe-research/verifier_recorder/`。
- **R5 前置窗口 sanity（S159 R1，enforced 非 advisory）**：verify 前先多窗口对比（隔夜 gap / D+1 日内 / path 的 mean+中位+胜率+base rate+IC/lift）定位优势窗口。无窗口优势 → 标 "exploratory" 不上重方法论（不抬杠，治 §44v1 错窗口根因）。
- **R6 n 门槛（S159 R2）**：n<200 picks 或 days_robust<60 → 标 "underpowered" 不判 "劣于随机"。Bonferroni 按 n 调（小 n FDR Benjamini-Hochberg，大 n K=6-8）。
- **R7 不外推**：verdict 只覆盖所测窗口+所测 edge，不外推"无 edge"（grill 外推禁令，s44-quant-validation-loop 教训）。

## 3. gap §44v2 run（priority 1 应用，验证 gap 是否 edge）

- 现 `tools/gap_window_lift.py` 14 天 naive 池化（statistics.mean + per-T quintile + 一个 pearson placeholder，无 day_paired/permutation/Bonferroni/walk-forward）。
- 用 baostock daily kline_cache + ths_limit_up_pool 扩 gap 样本 14→42 天（**gap 是 daily-bar 量** D 收盘→D+1 开盘，统计验证不需 60 天 intraday——intraday 只卡 capture/执行 deferred）。
- 跑 §44v2 重方法论：day_paired 非池化（按日聚类 effective n≈14-42）+ within-day permutation null_p95 + Bonferroni K=~20（§44v1 已试因子数）+ walk-forward + DSR n_trials=20。
- verdict：robust edge（lift≥2x 过 Bonferroni + DSR>0 + days_robust≥60）/ underpowered（n<60 标待 live 60 天复验）/ 证否（lift<1 或 PBO 高）。
- gap capture/intraday（封板检测/pre-seal buy）defer 到方向层（60 天 live 积累，非 NOW）。
- Chen2017 nuance：gap 是大户的不可复制，但 retail 可 intraday 打板捕获（非完全不可复制）——prior 倾向薄/难，但 verify via 基建（便宜，daily-bar NOW）。

## 4. 受影响文件

- 新建 `backend/s44_verifier/verifier.py`（verifier 主模块 + Verdict dataclass + verify() 纯函数）。
- 新建 `backend/s44_verifier/recorder.py`（qlib Recorder 模式实验追踪）。
- 新建 `backend/s44_verifier/wiring.py`（适配层 import vendor/skill-backtest-overfit/scripts/）。
- 合并 `tools/{gap_window_lift,overnight_gap_decomposition,first_board_layer_lift,kline_ta_validation,...}.py` 的 day_paired+permutation+Bonferroni+walk-forward 逻辑进 verifier 内部组件（tools/ 脚本保留作 CLI wrapper）。
- 改 `tools/` 9 脚本 ROOT 参数化（grill #3）：`Path(__file__).resolve().parents[2]` 或 `VR_DATA_DIR`，不硬编码 Vibe-Research-S151。
- 改 `candidate_funnel/evaluation.py` REGISTRY 改标（grill #3，S160 §4）：DIMENSION_LIFT_REGISTRY 注释改"§44 v1 窗口偏差 no-edge 记录（待 v2 重测）"，不灌进新底座当 final。

## 5. 验收标准

- [ ] R1 verifier 签名实现 + 单测（给定已知 return series → 正确 verdict，AAA pattern）。
- [ ] R2 DSR/PBO/CSCV/purged-kfold/haircut grep 非零（wire backtest-overfit）。
- [ ] R3 day_paired+permutation+Bonferroni+walk-forward 合并进 verifier（tools/ 脚本作 CLI wrapper）。
- [ ] R4 Recorder 落盘（输入快照+verdict+frozen_commit 一条 recorder_id 复现）。
- [ ] R5 前置窗口 sanity enforced（无窗口优势标 exploratory 不上重方法论）。
- [ ] R6 n 门槛 enforced（n<200 或 days_robust<60 标 underpowered）。
- [ ] gap §44v2 run（14→42 天 daily-bar）出 verdict（robust/underpowered/证否），落 Recorder。
- [ ] pytest 单测全绿 + gap run 复现（recorder_id 重算一致）。

## 6. 合规与工程底线自查

- [x] 不臆造：verifier 实算（DSR/PBO/CSCV 公式从 backtest-overfit skill + López de Prado 文献），禁心算禁 naive 池化。
- [x] 私有数据隔离：Recorder 落盘写 .vibe-research 不进 git。
- [x] em_get 防封：gap run 用 baostock daily（无防封）+ ths_limit_up_pool 走 _ths_get 限流。
- [x] §44 降级参考性建议：verifier 是判定器非阻塞 gate（但 gap verdict 影响是否建 capture）。
- [x] verdict 外推禁令：gap 标 hypothesis，跑 §44v2 后才称 robust/证否，不外推"无 edge"。
- [x] 不闭门造车：wire backtest-overfit skill（开源）+ qlib Recorder 模式 + López de Prado/Chen2017/Hua'an 文献。

## 7. 分级

medium（新 verifier 模块 + wire skill + 合并 harness + gap run）。issue 层单轮 review。免 feature 分支（design-agnostic，不碰生产选股）。grill 留给"verifier 方法论变更"（本 spec 是 framework 接线非方法论本身，可免重 grill，但实现后跑 gap run sanity 验）。
