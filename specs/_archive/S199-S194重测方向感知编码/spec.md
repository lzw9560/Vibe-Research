# Spec: S199 — S194 重测（方向感知 gap 编码 + 衰竭重标 + multifactor null + regime 分拆）

> 状态：草案（设计先做；衰竭重标部分待 S198 workflow verdict 定翻转；实现待 S198 + 数据）
> 作者：Claude  日期：2026-09-13
> 分级：large（改 reconstruct_s194_signals 编码 + ablation cases_vals + regime 分拆 + multifactor null 重跑）
> 关联：[[S194-信号融合基线]] R5 no_contribution / [[S193-缺口理论集成]] R5 v3 / [[S198 衰竭翻转]]（pending）/ [[S159-§44应用规约v2]]

## 1. 问题 / 目标

**S194 R5 no_contribution 真因**（S193 R5 v3 对抗审 wn80mbbm6 verdict trigger_new_spec）：
- gap delta_ic=+0.008（正，非负，p=0.33 非显著）——不是"被错误否决的强 edge"
- 真因 = **方向无关编码**：`reconstruct_s194_signals.py:25-31 GAP_REGIME_ENCODE` 把 regime 映成 0-0.9 无方向标量，`gap_direction` 在 :85 重建了却没喂 cases_vals（`run_s194_ablation.py:48` 只用 `gap_regime_encoded`）
- 次因 = 常数 0.5 先验权重（`run_s194_ablation.py:42`）+ long-only 样本缺负向变化
- breakout 才是有害项（delta -0.008~-0.03），gap 微正非负

**目标**：用方向感知 gap 编码重测 S194 融合消融，看缺口（带方向）是否有 edge。verdict 明确**不预断有 edge**（regime 依赖 + 幅度>2% 仅 42.9% + long-only 缺负向）——这是探索性重测，非"翻案"。

## 2. 需求清单

### R1：方向感知 gap 编码（核心，独立于 S198）
- `reconstruct_s194_signals.py` GAP_REGIME_ENCODE 改带方向符号：
  - 向上缺口 regime 正，向下负
  - 趋势启动向上=+0.9 / 向下=-0.9；趋势中继向上=+0.7 / 向下=-0.7；反转向上=-0.5（向上反转=跌，预期负）/ 向下=+0.5；噪声±0.1
- `run_s194_ablation.py:48` cases_vals 的 "gap" 从 `gap_regime_encoded`（标量）→ `gap_regime_directed`（带符号）
- 喂 `gap_direction` 进 cases_vals（二维编码备选：regime 标量 + direction ±1 分量）

### R2：衰竭重标（待 S198 verdict）
- 若 S198 verdict "翻 regime 极性"（反转→延续）：衰竭 regime 值从 0.5（反转）→ 0.7（延续/趋势中继），方向感知编码相应改
- 若 S198 "不翻"：衰竭保持"反转" label + caveat（R5 v3 实测延续，label 疑误）
- **此 R 阻塞待 S198 workflow verdict**

### R3：regime 分拆（牛/熊/震荡）
- 按 上证 MA20>MA60 多头 / 非多头 分拆 case，分别跑 ablation
- S193 R5 v3 发现 regime-mix（9 月牛月权重高，1 月失效被 pooled 掩盖）——分拆后看缺口 edge 是否只在牛月
- 参考 breakout arm regime 依赖（[[breakout-trade-profitable-despite-falsified-selection]]）

### R4：multifactor null（S194 已有，复用）
- ablation_runner 的 multifactor._permutation_pval + walk_forward_cv（S194 R5 v2 已实现）
- 重测用同 null 方法论，只改 cases_vals 编码（R1）+ 分拆（R3）

### R5：不预断 edge + 诚实终点
- verdict 明确"不预断有 edge"——重测可能仍 no edge（regime 依赖 + 幅度不够 + long-only）
- 若重测仍 no edge：诚实标"方向感知编码也 no edge"，gap 信号在融合池无增量（非编码缺陷，是信号本身弱）
- 若有 edge：spec 升级（方向感知 gap 进融合权重）

## 3. 受影响文件

| 文件 | 改动 |
|---|---|
| `backend/tools/reconstruct_s194_signals.py` | GAP_REGIME_ENCODE 改带方向符号 + 输出 gap_regime_directed |
| `backend/tools/run_s194_ablation.py:48` | cases_vals "gap" 用 gap_regime_directed + 喂 gap_direction |
| `backend/tools/run_s194_f3_verdict.py` | regime 分拆后 per-regime 跑 F3 verdict |
| `backend/tests/test_ablation_runner.py` | 加方向感知编码 case 测 |

## 4. 验收

- [ ] A1：方向感知 gap 编码落地（gap_regime_directed 带符号，gap_direction 喂 cases_vals）
- [ ] A2：衰竭重标按 S198 verdict（翻/不翻）
- [ ] A3：regime 分拆（多头/非多头）per-regime ablation
- [ ] A4：重测后判 edge——有 edge 升级融合权重 / no edge 诚实标"方向感知也 no edge"
- [ ] A5：pytest not live 全绿

## 5. 合规与工程底线自查

- [x] 不臆造：gap 编码从 classify_gap regime+direction 算，非手填
- [x] 不预断 edge（verdict 明确）——重测是探索性，非"翻案"
- [x] 私有数据隔离：cases 在 .vibe-research/（gitignored）
- [x] §44 v2 不外推：重测结果不预判，no edge 不外推成"缺口无 edge"（只说"方向感知编码下 no edge"）

## 6. 关联 + 依赖

- [[S194-信号融合基线]] R5 no_contribution（本 spec 重测）
- [[S193-缺口理论集成]] R5 v3（gap continuation 预测力 survive Bonferrini，但 S194 编码丢方向）
- [[S198 衰竭翻转]]（**阻塞 R2**——待 verdict 定衰竭重标）
- [[breakout-trade-profitable-despite-falsified-selection]]（regime 依赖参考）
- 对抗审 wn80mbbm6 verdict trigger_new_spec（"方向感知编码+衰竭重标+multifactor null+regime 分拆连贯重测"）

## 7. 实现时序

- **现在（9-13）**：spec 草案（设计先做）+ R1 方向感知编码设计（独立于 S198）
- **S198 verdict 后**：R2 衰竭重标定（翻/不翻）
- **实现**：R1-R4（改编码 + ablation + regime 分拆 + multifactor null 重跑）
- **验收**：A4 判 edge（不预断）
