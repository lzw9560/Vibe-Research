# Spec: S201 — CRITICAL bug 修复（cost 口径统一 + gap 前视修复）

> 状态：草案（quant-system-brainstorm verdict ww1bqpg70 2 CRITICAL bug，撞"判断须可复现"工程底线）
> 作者：Claude  日期：2026-09-13
> 分级：medium（承重 accounting.py + gap_classifier.py，影响 §44 net verdict + chat.TOOLS + fusion + R4）
> 关联：[[S200]] §6.9 优先 spec / [[S194-信号融合基线]] F3 / [[S193-缺口理论集成]] R5 / 对抗审 ww1bqpg70

## 1. 问题 / 目标（2 CRITICAL bug）

**Bug1：cost 口径不一致**（撞"判断须可复现"底线）
- `accounting.py:30 ROUND_TRIP_COST_PCT=0.70`（spread 0.60% + slippage 0.10%，不含佣金/印花）+ 印花 0.10%/0.05% + 佣金 5 元×2 → ~0.80%+ round-trip
- `run_s194_f3_verdict.py:26 A_SHARE_ROUND_TRIP_COST=0.002`（0.2% = 佣金 0.025%×2 + 印花 0.05% + 滑点 0.10%，**不含 spread 0.60%**）
- S194 注释明说"0.7% 是美股/过度假设"——accounting 的 spread 0.60% 是美股假设，A 股 bid-ask spread 实际小（主流股 0.01-0.10%）
- **影响**：§44 net verdict 用哪个成本决定结论——breakout arm net -1.14%（accounting 0.70%）vs +0.36%（S194 0.2%），S192 实盘评估 + S194 F3 verdict 都受影响，不可复现

**Bug2：gap_classifier 前视**（_is_filled D+1..D+3）
- `gap_classifier.py:81-95 _is_filled` 扫 idx+1..idx+3（未来 bar）判 D 日缺口是否 3 日回补
- 突破/持续分类（:178/:187）require `not filled`——D 日信号标签偷看 D+1..D+3 未来
- S193 R5 v3 对抗审 wn80mbbm6 Q4 CRITICAL：3 日准确率 61.9%/59.9% 被前视膨胀非 clean OOS
- **影响**：chat.TOOLS query_gap_regime + fusion_pipeline gap_regime + R4 gap_scan 推送 + S193 R5 准确率都吃前视标签

## 2. 需求

### R1：cost 口径统一（Bug1）
- [ ] R1a：确认 A 股真实成本（spread/佣金/印花/滑点各多少）——查 accounting.py + 实盘数据
- [ ] R1b：统一 ROUND_TRIP_COST_PCT——accounting 0.70% 含 spread 0.60%（美股假设）→ 改 A 股真实（spread 0.05-0.10% + slippage 0.10% + 印花 + 佣金 ≈ 0.20-0.30%），或 S194 改用 accounting 口径（若 spread 0.60% 合理）
- [ ] R1c：§44 net verdict 复算——cost 口径统一后，breakout arm net verdict 重跑（-1.14% 或 +0.36% 取决于口径），S192 实盘评估 + S194 F3 verdict 同步
- [ ] R1d：标 cost_caliber（mixed-caliber 不出 verdict，verdict §44v2 一致性门）

### R2：gap 前视修复（Bug2）
- [ ] R2a：`_is_filled` 训练可用未来（标签训练），实盘信号只用 T 及之前 bar 重算（verdict 方案）
- [ ] R2b：gap_classifier 分训练/实盘模式（训练 `_is_filled` 用未来，实盘不用或用 T 之前 bar 代理）
- [ ] R2c：S193 R5 v3 重跑（前视修复后，突破/持续 3 日准确率重算，确认非前视上界）
- [ ] R2d：chat.TOOLS query_gap_regime + fusion_pipeline + R4 gap_scan 同步（实盘模式）

### R3：TDD + 对抗审
- [ ] R3a：6 视角对抗审修复方案（cost 口径对错 + 统一方案 + gap 前视修复 + 影响范围 + TDD 验收 + 时序）
- [ ] R3b：test_accounting + test_gap_classifier 加 cost 口径 + 前视修复 case

## 3. 受影响文件

| 文件 | 改动 |
|---|---|
| `backend/engine/accounting.py:30` | ROUND_TRIP_COST_PCT 0.70→A 股真实（待 R1a 确认）|
| `backend/engine/gap_classifier.py:81-95` | _is_filled 训练/实盘模式分（R2a/b）|
| `backend/tools/run_s194_f3_verdict.py:26` | A_SHARE_ROUND_TRIP_COST 与 accounting 统一（R1b）|
| `backend/s44_verifier/verifier.py` | cost_caliber 一致性门（R1d）|
| `backend/tests/test_accounting.py` + `test_gap_classifier.py` | cost 口径 + 前视修复 case（R3b）|

## 4. 验收

- [ ] A1：cost 口径统一（accounting + S194 同口径，标 cost_caliber）
- [ ] A2：§44 net verdict 复算（breakout arm net verdict 重跑，确认 -1.14% 或 +0.36%）
- [ ] A3：gap 前视修复（_is_filled 训练/实盘分模式）
- [ ] A4：S193 R5 v3 重跑（前视修复后突破/持续准确率重算）
- [ ] A5：pytest not live 全绿
- [ ] A6：6 视角对抗审修复方案过

## 5. 合规（撞工程底线"判断须可复现"）

- [x] 不臆造：cost 口径从 accounting.py + S194 实证 + A 股真实成本查证
- [x] 判断须可复现：cost 口径统一后 §44 net verdict 可复现（当前 0.70% vs 0.2% 不可复现）
- [x] gap 前视：修复后实盘信号无前视（训练/实盘分模式）

## 6. 关联

- [[S200]] §6.9 优先 spec（2 CRITICAL）
- [[S194-信号融合基线]] F3 verdict（cost 影响净收益结论）
- [[S193-缺口理论集成]] R5 v3（前视影响准确率）
- [[S198 衰竭翻转]]（gap 前视修复是独立 spec，非 S198 翻 label）
- 对抗审 ww1bqpg70（2 CRITICAL bug）+ 本 spec 6 视角审修复方案
