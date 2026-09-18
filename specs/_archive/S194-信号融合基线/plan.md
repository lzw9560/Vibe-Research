# Plan: S194 — 信号融合基线（few-shot 检索 + 贝叶斯权重 + 消融验证）

> 关联：[[spec.md]]（grill 修订后，6 真问题全修）、[[../S193-缺口理论集成/spec.md]]、`backend/tools/multifactor_combo_validation.py`（复用 OOS 框架）、`s193-195-spec-grill-findings-2026-09-12`

## 技术方案

### 核心架构（spec §2 定 + grill 修订）

```
信号源（S193 缺口 / S176 OFI / breakout 选股 / 资金流 / 趋势臂）
    ↓
[R1 signal_align] 多尺度时间戳对齐 → 锚到 D 日统一格式 {signal_name, value, confidence, timestamp, source}
    ↓
    ├─ [R2 fewshot_retriever] FS1 检索历史相似 case（trade_journal 1092 起点）→ top-K 喂 AI
    │   ⚠️ 不过 §44（非确定 + 全库 lookahead 泄漏），价值靠 AI 研判 + 用户反馈定性
    └─ [R3 bayesian_signal_weight] FS2 Beta-Bernoulli 后验权重（延伸 S180）→ {signal: weight}
        ✅ 可 OOS（确定函数），参与 F1 消融
    ↓
[R4 fusion_layer] 综合 FS1 检索结果 + FS2 权重 → {regime, direction, confidence, top_similar_cases, signal_weights}
    ↓
喂 chat.run_chat system prompt（AI 综合研判，不直接触发买卖）
    ↓
[R5 ablation_runner] F1 消融（只 FS2，复用 multifactor OOS 框架）→ 每信号增量贡献
[R6 F3] FS2-only event edge §44（可复现，测融合 event 群体收益 lift）
```

### 模块拆分（5 模块 + 依赖序）

| 序 | 模块 | 职责 | 依赖 |
|---|---|---|---|
| 1 | `engine/signal_align.py` | 多尺度信号时间戳对齐（缺口日级+OFI 盘中+资金流+选股 T-1）→ D 日统一格式 | S193 classify_gap + 现有 OFI/选股/资金流信号源 |
| 2 | `engine/fewshot_retriever.py` | FS1 检索历史 case（trade_journal 1092 起点）+ 相似度（先 cos/Jaccard） | signal_align 对齐后信号 + trade_journal 数据 |
| 3 | `engine/bayesian_signal_weight.py` | FS2 Beta-Bernoulli 后验权重（延伸 S180 bayesian_arm_size） | signal_align + 历史信号 reliability 数据 |
| 4 | `engine/fusion_layer.py` | 综合 FS1+FS2 → 研判产出喂 AI | signal_align + R2 + R3 |
| 5 | `tools/ablation_runner.py` | F1 消融（只 FS2）+ F3 event §44 | **复用 multifactor_combo_validation.py OOS 框架**（walk-forward CV + Bonferroni + anti-feature-selection）+ fusion_layer + §44v2 verifier |

**依赖序**：R1（对齐）→ R2/R3（检索/权重，可并行）→ R4（融合）→ R5/R6（验证，R5 消融 + R3 event §44）。

### 数据流

1. **信号采集**：各信号源产原始信号（缺口 regime 来自 S193 classify_gap，OFI 来自 S176，选股来自 breakout 候选池，资金流来自 stock_fund_flow，趋势来自 S181 趋势臂）
2. **对齐（R1）**：signal_align 把不同时间尺度（日级/盘中/T-1）锚到 D 日统一时间戳 + 标准化格式
3. **检索（R2 FS1）**：fewshot_retriever 用对齐后信号组合 → trade_journal 历史 case 库检索 top-K 相似 → 返 `[{historical_case, similarity, outcome}]`
4. **权重（R3 FS2）**：bayesian_signal_weight 用历史 reliability（信号准不准）→ Beta-Bernoulli 后验 → `{signal: weight}`
5. **融合（R4）**：fusion_layer 综合 FS1 检索结果 + FS2 权重 → `{regime, direction, confidence, top_similar_cases, signal_weights}`
6. **喂 AI**：fusion_layer 输出注入 chat.run_chat system prompt → AI 综合研判（飞书 bot 问股时带融合输出）
7. **验证（R5/R6）**：ablation_runner 跑 F1 消融（只 FS2）+ F3 event §44（复用 multifactor OOS 框架）

## 取舍（为何选这些 + 备选为何不选）

### 选：FS2-only F1 消融（不 FS1）
- **选因**：FS2 贝叶斯权重是确定函数（先验+数据→后验），可 walk-forward OOS；FS1 AI 推理非确定 + 全库检索 lookahead 泄漏，§44v2 verifier 套不上（spec grill HIGH#3）
- **备选 FS1 F1 不选**：FS1 非确定，F1 消融两侧（with/without FS1）都含随机 AI 推理，lift 增量是噪声——verdict 不可信。FS1 价值靠"AI 研判 + 用户反馈"定性，不硬过 §44

### 选：F3 FS2-only event edge（不 selection）
- **选因**：R4"不触发买卖喂 AI+用户决策"→ AI 推理+用户决策非确定 → selection 的 survivors_by_day 不可复现定义（spec grill CRITICAL#2）。event edge 测群体收益 lift（survivors=FS2 权重触发的 event，确定可复现）
- **备选 selection 不选**：survivors 不可复现违反 §1.2 工程底线"判断须可复现"；冻结 AI 输出回测 verdict 只适用那次（非一般选股力）
- **诚实降级**：event edge 回答不了"融合能否选股"（只测群体收益），但可复现 + 不假设

### 选：复用 multifactor_combo_validation.py OOS 框架（不重造）
- **选因**：multifactor_combo_validation 已实现 walk-forward CV 14 folds + OOS R²/IC + Bonferroni + anti-feature-selection（spec grill MEDIUM#6 DRY）。ablation_runner 继承该框架，FS2 权重作 feature 输入
- **备选从零造不选**：违反 CLAUDE.md "先搜后写" + DRY；F1/F3 实质是 multifactor 弱化版（FS2 贝叶斯 < ML 组合严，但 OOS 框架可复用）

### 选：先 few-shot 统计融合（不 ML）
- **选因**：1092 case 小样本，训练模型必过拟合（S161 DSR/PBO 会证）；few-shot 零训练 + 可解释 + 不过拟合
- **备选 ML 不选（现在）**：样本不够；Phase 4 数据够 5000+ 再上 ML，**须 engage multifactor null**（论证新 ML 机制 ≠ 已证否的 ML 多因子，或接受重走证否路）

### 跳过：FS3 k-NN
- **不选因**：距离定义难（不同信号尺度）+ 不如 FS1 AI 推理灵活，YAGNI

## 实现策略（minimal 先闭环）

**Phase 3a（minimal 验证闭环）**：先打通 R1+R3+R5/R6（FS2-only 链路）——signal_align + bayesian_signal_weight + ablation_runner（复用 multifactor OOS）→ 跑 F1 消融 + F3 event §44。**目的**：最快验证"融合有无 edge"（跟 multifactor null 对账）。

**Phase 3b（AI 研判层）**：加 R2 fewshot_retriever + R4 fusion_layer → 喂 AI 综合研判。FS1 不过 §44，价值定性。

**分阶段理由**：先验"融合有无 §44 edge"（Phase 3a，跟 multifactor null 对账），有 edge 再投 AI 研判层（Phase 3b）。避免 Phase 3b 投完发现融合无 edge（白费 R2/R4）。

## 数据依赖

- **trade_journal 1092 case**（实测 rows，spec grill 证伪零表误报）——FS1 检索历史 case 库 + FS2 reliability 数据
- **S193 classify_gap**（done，11 测试绿）——缺口 regime 信号源
- **S176 OFI / breakout 选股 / stock_fund_flow / S181 趋势臂**——其他信号源（现有）
- **§44v2 verifier + S161 DSR/PBO**——F1/F3 验证工具（现有）

## 风险与回滚

- **multifactor null 风险**（spec §1.1）：F1 全冗余 + F3 无 edge = 重发现 multifactor null，白费 5 跑 §44。**回滚**：接受，诚实标注"融合无 validated edge，回 Phase 4 ML 待数据"。
- **F1 underpowered**（spec §6）：小样本假"冗余"verdict。**回滚**：标"探索性不判冗余"（per §159 §44v2 应用规约）。
- **FS1 检索相似度**：cos/Jaccard 对异质信号组合可能不准。**回滚**：先简单度量，后期改（YAGNI 先上）。
- **回滚整体**：S194 是新模块不破坏现有 arm（融合层独立，不接入 forward_test 直到 F3 过 §44）。

## 依赖序总结

1. R1 signal_align（信号对齐，基础）
2. R3 bayesian_signal_weight（FS2，可 OOS，F1 依赖）
3. R5 ablation_runner（F1 消融，复用 multifactor OOS，依赖 R3）
4. R6 F3 event §44（依赖 R5 框架 + R3 FS2）
5. **Phase 3a 闭环验证**（R1+R3+R5/R6）→ 融合有无 edge
6. R2 fewshot_retriever（FS1，不过 §44，AI 研判用）
7. R4 fusion_layer（综合 FS1+FS2 喂 AI）
8. **Phase 3b AI 研判层**（R2+R4）→ 飞书 bot 问股带融合输出

R1→R3→R5→R6（Phase 3a 闭环）→R2→R4（Phase 3b AI 层）。
