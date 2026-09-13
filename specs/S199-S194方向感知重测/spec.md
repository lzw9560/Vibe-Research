# Spec: S199 — S194 方向感知编码重测

> 状态：草案（S198 flip 衰竭→动能延续 gate 5/5 PASS + S201c gap candidate 去前视 都 done，S194 no_contribution 真因=方向无关编码，重测 unblock）
> 作者：Claude  日期：2026-09-13
> 分级：medium（reconstruct_s194_signals.py + run_s194_ablation.py 离线重跑，非生产 fusion_pipeline.py）
> 关联：[[S194-信号融合基线]] F1 no_contribution / [[S193-缺口理论集成]] R5 v2 诊断 / [[S198-衰竭regime条件翻转]] flip done / [[S201c]] gap candidate done

## 1. 问题 / 目标

S194 F1 消融结论：gap signal **no_contribution**（delta_ic≈0，p=0.33 非显著）。gap-theory 对抗审（S193 R5 v2，wn80mbbm6）诊断真因：

- S194 用**方向无关 regime 标量编码**（`reconstruct_s194_signals.py:25` GAP_REGIME_ENCODE：无=0/噪声=0.1/反转=0.5/动能延续=0.5/趋势中继=0.7/趋势启动=0.9）——gap regime 本是**方向性信号**（趋势启动 up=多头启动 / down=空头反转），编码成方向无关标量**丢方向信息**。
- A 股 long-only（做空受限 §1.1 弱合规）→ 向下 regime 不可交易，方向无关编码把空头信号当多头喂，稀释 upward edge。
- `gap_direction` 字段已在 `reconstruct_s194_signals.py:86` 捕获但**未进编码**（只作元数据），S198 flip 后 regime="动能延续" 也未带方向。

**前置已 done**：S198 flip（衰竭 反转→动能延续，gate 5/5 PASS：day_paired lift=1.33 / permutation p=0.002 / regime bull 61.5%+bear 56.6%）+ S201c（gap candidate 去 _is_filled 前视）→ S199 重测 unblock。

**目标**：方向感知编码重跑 S194 ablation，看 gap 信号是否有 edge（翻 or 确认 no_contribution）。

## 2. 需求

### R1：方向感知编码
- [ ] R1a：GAP_REGIME_ENCODE 改方向感知——regime score × direction weight（A 股 long-only：direction=="向上"→score，=="向下"→0 或中性，因做空受限不可交易）
- [ ] R1b：保留旧方向无关编码作对照（A/B 两版，delta_ic 对比，证明 edge 来自方向感知非他因）
- [ ] R1c：gap_direction 进编码非仅元数据（line 86 现只作元数据）

### R2：重跑 ablation
- [ ] R2a：`run_s194_ablation.py` 用方向感知编码重跑 F1 消融（加 gap vs 不加 gap 的融合 lift 增量）
- [ ] R2b：delta_ic 重算（方向感知 A vs 旧方向无关 B 对照）

### R3：§44 验证（§44v2 应用规约，S159）
- [ ] R3a：day_clustered_t_test + permutation_p_value（gap 方向感知信号的 lift，同日配对非全局基线）
- [ ] R3b：Bonferroni K≤8（若多窗口 3/5/10 日或多 regime 对比）
- [ ] R3c：前置窗口 sanity（多窗口对比定位优势在哪，§44v2 规约①）

### R4：结论判定（诚实，不外推）
- [ ] R4a：若方向感知 delta_ic 正 + p<0.05 = gap 有 edge（翻 S194 no_contribution）
- [ ] R4b：若仍 ~0 + 非显著 = 真无 edge（确认 no_contribution，gap 不进融合权重）
- [ ] R4c：明确"测了什么 vs 没测什么"（禁外推"已测部分无 edge"→"整体无 edge"，§44v2 外推禁令）

## 3. 受影响文件

| 文件 | 改动 |
|---|---|
| `backend/tools/reconstruct_s194_signals.py` | GAP_REGIME_ENCODE 方向感知（R1），保留旧版对照 |
| `backend/tools/run_s194_ablation.py` | 重跑 F1 消融 A/B（R2）|
| `backend/s44_verifier/stats.py` | day_clustered+permutation+Bonferroni 复用（R3，已有）|
| `backend/tools/verify_gap_classification.py` | 多窗口 sanity（R3c，已有 R5 v3 框架）|

## 4. 验收

- [ ] A1：方向感知编码落地（regime×direction，A 股 long-only up=score/down=中性）
- [ ] A2：F1 消融重跑（A/B 对照 delta_ic）
- [ ] A3：§44 验证（day_clustered+permutation+Bonferroni+前置窗口 sanity）
- [ ] A4：结论判定（翻 or 确认 no_contribution，诚实标注测了/没测）
- [ ] A5：pytest not live 全绿
- [ ] A6：≥6 视角对抗审（方法论 spec，CLAUDE.md 自动复盘 2026-09-05）

## 5. 合规（弱合规，工程底线）

- [x] 不臆造：基于 S194 已有数据重测，方向感知编码设计基于 gap-theory 对抗审诊断（非拍脑袋）
- [x] 判断须可复现：方向感知 delta_ic + §44 p 值可复算（`s44_verifier` 已有 day_clustered+permutation）
- [x] gap 前视：S201c candidate 已修（去 _is_filled 前视，实盘信号无前视）
- [x] 私有数据隔离：baostock cache 走 `.vibe-research/`（已 .gitignore）

## 6. 关联

- [[S194-信号融合基线]] F1 no_contribution（重测对象，delta_ic≈0 p=0.33）
- [[S193-缺口理论集成]] R5 v2（诊断方向无关编码真因，wn80mbbm6）
- [[S198-衰竭regime条件翻转]] flip done（衰竭→动能延续，gate 5/5 PASS，commit c8d6e08）
- [[S201c]] gap candidate done（去 _is_filled 前视，candidate 语义两侧）
- gap-theory 图谱（S198 flip 已落 code，S199 重测后更新 delta_ic 结论）

## 7. 诚实判定（先验）

- 方向感知编码**可能**翻 S194 no_contribution（若 edge 来自 upward regime 被方向无关稀释），但**也可能**仍无 edge（若 gap regime 本身无选股力，方向感知救不了——breakout arm §44 已证否弱选股 1.36x）。
- S198 flip 证衰竭 continuation（动能延续），但 continuation ≠ 选股 edge（[[breakout-trade-profitable-despite-falsified-selection]]：交易盈利≠选股 edge，止盈止损创造正 EV）。
- **不预设结论**——跑完 R2/R3 看 delta_ic + p 值定。若翻 no_contribution 须过 §44v2（day_paired+permutation+Bonferroni+前置窗口 sanity）。
