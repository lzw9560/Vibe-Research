# Spec: S198 — 衰竭缺口 regime label 条件翻转（needs-spec-first，gate 验证后 conditional flip）

> 状态：草案（对抗审 wrtii49pz verdict needs-spec-first，6 视角全票不现在翻码；先 spec + gate 验证）
> 作者：Claude  日期：2026-09-13
> 分级：medium（跨层 engine+ai+scheduler+tools+graph，无 feature 分支直接 develop，issue 层单轮 review）
> 关联：[[S193-缺口理论集成]] R5 v3 / [[S199-S194重测方向感知编码]]（direction-aware encoding 是 S194 真修，S198 relabel 不修 S194）/ [[S159-§44应用规约v2]]
> 对抗审 verdict：wrtii49pz（6 视角 needs-spec-first，3 CRITICAL + 详细 spec_points 11 条）

## 1. 问题 / 目标

**衰竭缺口 regime label "反转"（gap_classifier.py:185）被 S193 R5 v3 实测证伪**——衰竭后 5 日 continuation 54.8% vs 普通基线 43%（cluster-robust t+9.19/p=0.0000/Bonf=0.0000/n_days=160/4114 case，全表唯一无前视标签 line 182 不查 _is_filled）。

**但验证有 4 缺口**（verdict 3 CRITICAL）：
1. **用错测试**——verify_gap_classification.py:157 喂 day_clustered_t_test 的是单样本全局基线（returns=[hit-0.43]），测"衰竭 continuation > 43% pooled 基线"非"衰竭 vs 同日普通"的同日配对。正确 day_paired_lift 在 s44_verifier/stats.py:197 已实现已 import 没调
2. **无 permutation null**——项目对类似 gap 都用 permutation（s44_gap_run_60d/lockup_lift/multifactor），但 verify:177 defer（HIGH）。翻唯一没 permutation 的 label 低于项目标准
3. **regime-mix 未拆**——9 月牛月 pooled（99 bull/70 bear 天），continuation 是牛市 base behavior，+11.8% delta 可能 substantial 部分是 regime artifact。gap_regime_stratified.py MA20 bull/bear/range 拆分模式只用在隔夜 gap 没用在衰竭分类
4. **bare flip 是 wrong unit**——三重 CRITICAL：(a) 方向 bug：翻"趋势中继"后 _REGIME_DIRECTION 映射向"向上"，但 R5 显示向下衰竭 57.9% continuation=价格续跌，47% 向下 case 反方向；(b) label 碰撞："趋势中继"已被持续缺口占用（gap_classifier.py:190），复用使两类同值 0.7 不可区分；(c) 不修 S194：no_contribution 真因是方向无关编码（fusion_pipeline.py:84-87 丢 gap.direction）非 0.5/0.7 值

**目标**：先 gate 验证（day_paired_lift + permutation + regime-stratified + 10日），仅当全过后才 conditional flip 衰竭 label（:185 only → "动能延续"，非"趋势中继"）。direction-aware encoding 是 S199 独立 spec（S194 真修），S198 relabel 必要但不充分。

## 2. 需求清单

### R1：验证 gate（非阻塞，同 cache 几分钟-小时）
- [ ] R1a：跑 day_paired_lift（s44_verifier/stats.py:197，已实现已 import 未调，同 165MB cache 分钟级）——衰竭 survivors vs 普通 raw **同日配对**，决定性测试
- [ ] R1b：跑 permutation_p_value（stats.py:300，同 cache）——verify 脚本自标 HIGH TODO 从未执行
- [ ] R1c：跑 walk_forward_oos（stats.py:374，同 cache）——检查衰竭-continuation edge 时序稳定性
- [ ] R1d：用 index_ma20_regime.json + gap_regime_stratified.py 模式做 bull/bear/range 拆分——确认 edge 在 bear 月也成立非仅 bull-pooled
- [ ] R1e：引用 10 日窗口数（已算未述，10 日 55.7%）——确认非窗口依赖

### R2：条件翻转（仅当 R1 验证全过后）
- [ ] R2a：TDD——改 test_gap_classifier.py:137 + test_gap_scan.py:77 期望新 label [RED]
- [ ] R2b：翻 gap_classifier.py:185 exhaustion regime = "动能延续"（**line 185 ONLY，NOT line 180 向下突破"反转"**——R5 未测+有前视 _is_filled）
- [ ] R2c：新 label 选"动能延续"（非"趋势中继"——碰撞 :190 持续缺口 + _REGIME_DIRECTION 向上对向下 case 方向错；非"延续"——语义太泛）。_REGIME_DIRECTION 加"动能延续"→"中性"映射（保留安全 AI-defer）OR 重构为方向感知
- [ ] R2d：confidence 0.65 可选降至 0.6（对齐动能延续/持续中继 regime）——optional 不阻塞

### R3：direction-aware encoding 是 S199 独立 spec（S198 relabel 不修 S194）
- S194 no_contribution 真因 = 方向无关编码（GAP_REGIME_ENCODE 丢 direction + fusion_pipeline.py:84-87 丢 gap.direction）非 label 值
- S198 relabel 使 encode 0.5→0.7 但 fix 不了 S194（根因方向无关非值）
- **S199 方向感知编码才是 S194 真修**——S198 relabel 必要但不充分，S194 重测走 S199 不混入 S198

### R4：下游同步（仅 R2 flip 后）
- chat.TOOLS query_gap_regime（ai/tools/ta_tools.py:20）regime enum 列表更新
- fusion_pipeline.py:26 + reconstruct_s194_signals.py:25 GAP_REGIME_ENCODE DRY 重复提取 shared constant（两份相同 dict）
- fusion_layer.py:17-24 _REGIME_DIRECTION 加"动能延续"→"中性"
- R4 gap_scan.py:40 推送文案 caveat 去掉（label 已正确）
- gap-theory.md 图谱衰竭条目"R5 证伪 极性疑误 待复验"→"R5 v3 cluster-robust confirmed 已翻"+ regime mapping table + logic rules
- case 库 s194_signal_values.json 重跑 reconstruct_s194_signals.py 重生成（否则 fewshot 检索 mismatch）
- S194 融合消融重测（方向感知编码后，走 S199）

## 3. 受影响文件

| 文件 | 改动 |
|---|---|
| `backend/tools/verify_gap_classification.py` | R1 跑 day_paired_lift + permutation + regime-stratified + 10日（同 cache）|
| `backend/engine/gap_classifier.py:185` | R2b 翻 regime="动能延续"（仅 :185，非 :180）|
| `backend/engine/fusion_layer.py:17-24` | R2c _REGIME_DIRECTION 加"动能延续"→"中性"|
| `backend/engine/fusion_pipeline.py:26` + `reconstruct_s194_signals.py:25` | R4 GAP_REGIME_ENCODE DRY 提取 shared constant |
| `backend/ai/tools/ta_tools.py:20` | R4 query_gap_regime regime enum 更新 |
| `backend/scheduler/executors/gap_scan.py:40` | R4 推送文案 caveat 去掉 |
| `backend/tests/test_gap_classifier.py:137` + `test_gap_scan.py:77` + `test_fusion_layer.py:34-35` | R2a TDD 期望新 label [RED 先改] |
| `investing/strategies/gap-theory.md` | R4 衰竭条目 confirmed-flip + regime mapping + logic rules |

## 4. 验收

- [ ] A1：day_paired_lift survive（paired delta>0, p<0.05）——同日配对非全局基线
- [ ] A2：permutation p<0.05（within-day null）
- [ ] A3：per-regime table 显示衰竭 continuation 在 bull AND bear 均成立（或至少非 bull-only）
- [ ] A4：10 日窗口 55.7% 一致（非窗口依赖）
- [ ] A5：walk_forward_oos 时序稳定（加分项非 gate）
- [ ] **flip 仅在 A1+A2+A3 全过后**；任一失败→保留"反转"label+保留 gap_scan.py caveat
- [ ] A6：pytest not live 全绿（TDD test_gap_classifier + test_gap_scan + test_fusion_layer 同步）

## 5. 合规与工程底线自查

- [x] 不臆造：R1 验证用 s44_verifier 已实现方法（day_paired_lift/permutation/walk_forward），同 cache 实数
- [x] §44v2 不外推：R5 v3 cluster-robust 不够翻生产（用错测试+permutation 缺+regime-mix），补后 likely 翻但不 pre-commit
- [x] 经典理论保留：Wyckoff 衰竭=反转是定义性的，R5 证伪的是 CODE 代理（n_recent≥2+vol_ratio）非理论本身。图谱 gap-theory.md 保留经典定义+标代理校准中非翻经典定义
- [x] label scope：仅 :185 exhaustion，NOT :180 向下突破（R5 未测+有前视 _is_filled）
- [x] S198 relabel 不修 S194（方向无关编码是 S199）

## 6. 关联

- [[S193-缺口理论集成]] R5 v3（cluster-robust survive Bonferrini，但验证有 4 缺口）
- [[S199-S194重测方向感知编码]]（direction-aware encoding 是 S194 真修，S198 relabel 必要但不充分）
- [[S159-§44应用规约v2]]（n≥60 门槛跑全套方法论 day_paired+permutation+Bonferroni+walk-forward，当前只跑 2/4）
- 对抗审 wrtii49pz（6 视角 needs-spec-first，spec_points 11 条）
- memory: [[gap-exhaustion-polarity-flipped]]（R5 v3 发现）+ [[gap-classification-look-ahead-bias]]

## 7. 实现时序

- **阶段一（验证 gate，非阻塞，同 cache 几分钟-小时）**：R1a day_paired_lift + R1b permutation + R1c walk_forward + R1d regime-stratified + R1e 10日检查
- **阶段二（条件翻转，仅当 R1 全过）**：R2a TDD [RED] → R2b 翻 :185 "动能延续" [GREEN] → R4 下游同步 → A6 pytest
- **S199 独立**：方向感知编码重设计是 S194 真修，S198 relabel 不混入
- **commit**：feat(S198):
- **对抗审**：码前非码后（本 spec 即 wrtii49pz 审结果）
