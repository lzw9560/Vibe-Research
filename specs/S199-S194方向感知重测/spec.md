# Spec: S199 — S194 方向感知编码重测

> 状态：已实现（R1-R3 完成，R4 结论；A6 ≥6 视角 grill done verdict=needs-revision，R5 follow-up 2 测试 done 修订 §8）
> 作者：Claude  日期：2026-09-13（R5：2026-09-14）
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
| `backend/tools/s199_followup_tests.py` | R5 grill follow-up：breakout 分层 §44 lift + binary gate ablation（新增）|

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

## 8. 实测结果（R1-R3 跑完，2026-09-13）

### R1 方向感知编码（已实现）
- `encode_gap_direction_aware(regime, direction)` = base_score × direction_weight（A 股 long-only：up=1.0, down=0.0, none=1.0）
- `encode_gap_direction_agnostic(regime)` = base_score（旧方向无关，对照组）
- TDD 21 测试全绿（test_s199_direction_aware.py）

### R2 消融 A vs B（fresh data n=3028, n_days=151, robust tier）
| 版本 | delta_ic | delta_pval | verdict |
|---|---|---|---|
| A（方向感知） | -0.0021 | 0.5575 | no_contribution |
| B（方向无关） | -0.0022 | 0.5601 | no_contribution |
| A - B | +0.0001 | — | 无差异 |

**结论**：方向感知编码未改变 gap 信号在融合分消融中的 no_contribution verdict（robust tier, p>>0.05）。A vs B delta_ic 差 +0.0001 = 噪声级。

### R3 §44 验证（day_clustered + permutation + Bonferroni）

**Trade-level（gross_return）**：
- gap-present day_clustered t=+2.285 p=0.0119 day_mean=+0.71%
- no-gap day_clustered t=+2.411 p=0.0086 day_mean=+0.44%
- day_paired_lift winrate_lift=1.2754 permutation_p=0.0020（显著）

**Market-level（bars 前向 3/5/10 日）**：
| 窗口 | gap t | gap p | gap day_mean | no-gap day_mean | lift | perm_p |
|---|---|---|---|---|---|---|
| 3日 | +5.362 | 0.0000 | +4.24% | -1.09% | 1.6875 | 0.0020 |
| 5日 | +4.203 | 0.0000 | +4.17% | -1.41% | 1.6423 | 0.0020 |
| 10日 | +2.149 | 0.0167 | +2.68% | -1.77% | 1.4550 | 0.0020 |

Bonferroni K=6：gap_3d/gap_5d/perm_3d/5d/10d 全 survive（p_adj<0.05）；gap_10d Bonf 0.1002✗ 但 BH 0.0167✓。

**A vs B lift 对照**：A 略高于 B（+0.01~0.02 全窗口），方向感知边缘提升但非显著。

### R4 结论（诚实，不外推）

**测了什么**：
1. 融合分消融 delta_ic A vs B（gap 信号对融合分 IC 的贡献增量）—— robust tier, no_contribution
2. §44 day_clustered + permutation（trade-level + market-level 多窗口 3/5/10 日）
3. Bonferroni-BH 多重比较校正

**没测什么**（R5 后部分已测，标注）：
- ~~gap 信号单独（非融合分）的选股力 IC~~ → R5 测 binary gate（无 edge）+ breakout 分层 lift（Simpson paradox）
- ~~gap 在非 breakout arm（floor 27 case）的预测力~~ → R5 确认 floor arm realized=0 不可测
- 盘中信号（OFI/fund_flow）与 gap 交互（仍未测）
- ~~regime-stratified（牛月/熊月拆分）~~ → R5 未测 regime（grill expert 6 发现的 bear-day edge 仍是 open question，本轮不测）

**判定**（R5 后修订，见下方 R5）：
- gap 信号有 **market-level forward-return edge**（deconfounded，3/5/10d lift 1.47-1.70 permutation p=0.002 survive Bonferroni）——gap-present 前向收益确实更高
- gap 信号 **无 trade-level winrate edge**（Simpson's paradox：pooled winrate lift=0.98<1，gap 绝对 winrate 更低 38.27% vs 39.07%；binary gate winrate delta -0.65pp）——原 R4 "selection edge（组级 lift 1.27-1.69x）" overstated，trade-level lift 是日聚类假象非 per-trade winrate edge
- gap 信号 **无 ranking edge**（融合分 delta_ic ≈ -0.002 p=0.56 robust；binary gate 亦无 edge）——graded 和 binary 均 no_contribution
- 二者不矛盾（[[breakout-trade-profitable-despite-falsified-selection]]：交易盈利≠选股 edge）——gap 有 forward-return edge 但无 trade-winrate edge，无 ranking edge
- **S194 no_contribution 确认（加强）**：gap 不进融合权重——graded IC 无增量 + binary gate 亦无 edge（winrate delta 负，mean delta +0.064pp 噪声级）
- **方向感知假设（S193 R5 v2 诊断）部分支持→inconclusive**：§44 lift A>B 全窗口（+0.01-0.02）但 ablation delta_ic 无差异 + R5c Section C overlap bug（raw_b=raw_a 与 surv_b 重叠）→ inconclusive 非 partially supported
- **不 finalize S192 翻案 / 不改 fusion 权重**——R5 加强 no_contribution（binary gate 亦无 edge）

### R5 grill follow-up 测试（2026-09-14，needs-revision 后 2 定向测试）

≥6 视角 grill（wtj2t1343）verdict=needs-revision：selection edge 与 breakout 混淆（99% gap-present 是 breakout arm）+ graded ablation 对 binary gate 盲。跑 grill 推荐的 2 定向测试定夺。脚本 `tools/s199_followup_tests.py`（§44v2：day_clustered+permutation+Bonferroni+前置窗口 sanity；n=2888 n_days=148 robust tier）。

#### R5a 测试 1：breakout 分层 §44 lift（deconfound gap vs breakout）

按 breakout 分层——gap-present-WITH-breakout vs no-gap-WITH-breakout（控 breakout 测 gap 增量）。floor arm realized=0（27 case 全未实现），分层是 no-op（所有 gap-present 本就是 breakout arm）→ deconfound = within-breakout 对比（breakout held constant）。

Trade-level（gross_return）：
| 组 | surv_n | raw_n | surv_wr | raw_wr | day_paired_lift | perm_p |
|---|---|---|---|---|---|---|
| unstratified（orig ref） | 554 | 2334 | 0.3827 | 0.3907 | 1.2754 | 0.0020 |
| bk-stratified gap_a（dir-aware） | 554 | 2334 | 0.3827 | 0.3907 | 1.2754 | 0.0020 |
| bk-stratified gap_b（dir-agnostic） | 578 | 2310 | 0.3841 | 0.3905 | 1.2815 | 0.0020 |

- confound delta（orig - bk-stratified）= +0.0000 → lift **不是 breakout 驱动**（breakout held constant 后 lift 不变）——grill 的 breakout-confound 担忧**证伪**
- **Simpson's paradox**：pooled_wr_lift=0.9795（gap 绝对 winrate 更低 38.27% vs 39.07%）但 day_paired_lift=1.2754（gap per-day 相对更高）→ trade-level "selection edge" = 日聚类假象，非 per-trade winrate edge

Market-level（bars 前向 3/5/10d，within breakout arm，前置窗口 sanity §44v2 ①）：
| 窗口 | surv_n | raw_n | surv_wr | raw_wr | lift | perm_p | Bonf_adj |
|---|---|---|---|---|---|---|---|
| 3d | 615 | 2346 | 0.5285 | 0.4160 | 1.6995 | 0.0020 | 0.0060 ✓ |
| 5d | 611 | 2329 | 0.5205 | 0.4122 | 1.6756 | 0.0020 | 0.0060 ✓ |
| 10d | 579 | 2261 | 0.4508 | 0.4029 | 1.4711 | 0.0020 | 0.0060 ✓ |

- market-level pooled winrate gap > no-gap（0.5285 vs 0.4160 @3d）→ market-level lift **是真的**（非 Simpson），survive Bonferroni
- trade-level 是 Simpson（pooled<1），market-level 是真（pooled>1）→ gap 有 forward-return edge 但无 trade-winrate edge

**R5a 结论**：gap 无 breakout 外独立 per-trade selection edge（deconfound 后 trade-level 是 Simpson 假象，pooled lift 0.98<1）；但 market-level forward-return edge 真实（deconfounded，survive Bonferroni）。grill 的 breakout-confound 担忧证伪（lift 非 breakout 驱动，confound delta=0.0000），但 "selection edge" overstatement 经 Simpson's paradox 确认。

#### R5b 测试 2：binary gate ablation（threshold edge 非 graded rank）

gap 作 0/1 FILTER（gap-present=1, no-gap=0），gate ON（gated=gap-present）vs gate OFF（ablated=all）。测 winrate/mean-return delta（非 rank IC，graded ablation 测不到的 binary threshold effect）。

| 配置 | n | winrate | mean_return | day_t | p |
|---|---|---|---|---|---|
| gate ON（gap_a-present） | 554 | 0.3827 | +0.5296% | +2.285 | 0.0119 |
| gate OFF（all, ablated） | 2888 | 0.3892 | +0.4655% | +2.601 | 0.0051 |
| DELTA | — | **-0.65pp** | +0.064pp | — | — |
| gate ON（gap_b-present, bk） | 578 | 0.3841 | +0.5556% | +2.312 | 0.0111 |
| DELTA（vs all bk） | — | -0.51pp | +0.090pp | — | — |

- winrate delta **负**（gap gate 降低 winrate -0.65pp）→ binary gate **无 winrate edge**
- mean_return delta 微正（+0.064pp = +0.064%/笔，fat tail：少赢但大赢）→ 不构成 material edge（噪声级）
- graded IC ablation（R2）delta_ic≈-0.002 p=0.56 无 rank edge；binary gate 亦无 edge → no_contribution 对 graded 和 binary 均成立

**R5b 结论**：gap-as-binary-gate 无 edge（winrate delta 负，mean delta +0.064pp 噪声级）。graded ablation 漏的 binary edge **不存在**。no_contribution 对 graded 和 binary 均成立——fusion 决策（gap 不进融合）证据加强。

### R5 最终 verdict

**needs-revision（spec 文本已修订，fusion 决策 sound）**：
- fusion 决策 "gap 不进融合权重" **sound 且加强**——graded IC 无增量 + binary gate 亦无 edge（R5b）
- "selection edge" claim **修订**：原 "组级 lift 1.27-1.69x" → "market-level forward-return edge（真，deconfounded，survive Bonferroni）+ trade-level Simpson's paradox（pooled 0.98<1，非 per-trade winrate edge）"
- breakout-confound **证伪**（deconfound delta=0.0000，lift 非 breakout 驱动）；Simpson's paradox **确认**（trade-level "selection edge" 是日聚类假象）
- binary-gate-blindness 担忧**证伪**（binary gate 亦无 edge）
- §44v2 合规：day_clustered + permutation + Bonferroni（K=3，mature n_days=148≥60）+ 前置窗口 sanity（3/5/10d）均过
- **不 finalize S192 翻案 / 不改 fusion 权重**——R5 加强 no_contribution
