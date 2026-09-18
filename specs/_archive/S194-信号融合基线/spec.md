# Spec: S194 — 信号融合基线（few-shot 检索 + 贝叶斯权重 + 消融验证）

> 状态：草案（grill-me 2026-09-12 Q14-Q16 定方法论 + 6 视角 spec grill 修订）
> 作者：Claude  日期：2026-09-12
> 分级：large（新基建——信号对齐层 + few-shot 引擎 + 贝叶斯权重 + F1 消融验证）
> 关联：[[../S193-缺口理论集成/spec.md]]、[[../S171-长线价值/spec.md]]、`backend/tools/multifactor_combo_validation.py`（已证否的 ML 多因子融合，§1.1 对账）、`s168-12harness-verdict-selection-no-edge`、`multiline-strategy-direction`（multifactor null verdict）、`rigorous-methodology-timely-retrospective-no-hallucination`、`s193-195-spec-grill-findings-2026-09-12`

## 1. 问题 / 目标

**方法论修正（Q13-Q14 grill）**：项目 §44v2 至今验的全是**单信号买卖 lift**（breakout 选股证否、T+0 OFI 证否、gap 隔夜 net≈0）——但用户反思：**"所有信号独立分析都可能没价值，融合判断才是正确思路"**。单信号 §44 不过 ≠ 融合无价值。

**目标**：搭信号融合基线——把分散信号（缺口 regime + OFI + 选股 + 资金流 + 趋势臂）聚到一层，用 **few-shot 检索 + 贝叶斯权重**融合，**不验单信号 §44**，验 **F1 消融**（加某信号 vs 不加的融合 lift 增量）+ **F3 融合整体 §44**。

### 1.1 先验 null 对账（spec grill CRITICAL#1 修订）

**已存在的高置信先验 null（必须 engage，不能无视）**：`backend/tools/multifactor_combo_validation.py`（20KB）已实现更严的 ML 多因子融合验证——walk-forward CV（leave-one-day-out 14 folds）+ OOS R²/IC + Bonferroni(4 模型) + anti-feature-selection，测 16 因子。memory `multiline-strategy-direction` 记 verdict **`any_multifactor_edge = 无（置信度高）`**（6 模型 OOS R²∈[-0.117,+0.016] 全≤0.02，lift=0.66x 反向）。

**为何 S194 AI-reasoning 融合 ≠ 已证否的 ML 多因子融合**（区分论证，非假设）：
- **机制不同**：multifactor_combo_validation 测的是**统计 ML 模型**（OLS 回归 + tree 模型）线性/非线性组合；S194 是 **AI-reasoning few-shot 检索**（AI 查信号组合→检索历史 case→contextual reasoning 综合研判）。AI 能做 contextual reasoning（情境模式识别）统计模型不能。
- **但诚实标注**：AI-reasoning 在统计 OOS 上确实弱（非确定，见 §2.1 FS1 caveat）——multifactor null 适用于 ML 融合，不直接外推到 AI-reasoning 融合，但**也不保证 AI-reasoning 有 edge**。
- **逻辑闭环**：若 multifactor null（高置信无 combo edge）为真，S194 F1 消融可能显示"每信号边际贡献≈0"→全标冗余→重新发现 multifactor null（白费 5 跑 §44）；若 S194 跑出"融合有 edge"=用更弱方法推翻对抗证否过的高置信 null，**须非凡证据**（memory `rigorous-methodology`）。
- **Phase 4 ML 上线即重走证否路**：§7 Phase 4 "数据够 5000+→上 ML"——ML 融合恰是 multifactor_combo_validation 已证否的，Phase 4 须 engage 该 null 或论证新 ML 机制不同。

**结论**：S194 不假设"AI-reasoning 融合有 edge"，而是**用 F1 消融 + F3 融合§44 实测验证**（接受可能重发现 null 的风险，但诚实标注）。spec 不把"融合才是正确思路"当未经验证反思直接立为目标——而是当**待验假设**，跟 multifactor null 对账。

## 2. 融合架构（Q15-Q16 grill 定 + spec grill 修订）

**不上 ML 框架（Q15）**——1092 trades 小样本（trade_journal.db 实测 1092 rows，spec grill 证伪"零表"误报），训练模型必过拟合（S161 DSR/PBO 会证）。先 **few-shot 统计融合**，后期数据够（5000+ case）再上 ML（须 engage multifactor null，见 §1.1）。

### 2.1 两范式结合 + OOS 可行性（spec grill HIGH#3 修订）

- **FS1 检索式 few-shot（RAG 风格，喂 AI）**：AI 查当前信号组合→检索历史相似 case→AI 综合研判。零训练 + 可解释。
  - **⚠️ OOS 不可行 caveat（spec grill HIGH#3）**：FS1 AI 推理**非确定**（同输入不同次跑结论不同）+ 全库检索不区分 in/out-sample（lookahead 泄漏）→ **无法 walk-forward OOS**，§44v2 verifier 套不上。FS1 **不过 §44 gate**（标"非确定 AI 研判，不参与 F1 消融 §44 验证"）。
- **FS2 贝叶斯更新（信号权重）**：延伸 bayesian_arm_size S180（Beta-Bernoulli）作信号 reliability 先验。数学严谨 + 自适样本量。
  - **OOS 可行**：FS2 后验是确定性函数（先验+数据→后验），可 walk-forward OOS。**F1 消融只测 FS2**（确定可复现），FS1 不参与 §44 验证。

**跳过 FS3 k-NN**——距离定义难 + 不如 FS1 AI 推理灵活，YAGNI。

**关键修正**：F1 消融（R5）只测 FS2 贝叶斯权重（确定可 OOS），不测 FS1 AI 检索（非确定）。FS1 的价值靠"喂 AI 研判用户反馈"定性评估，不硬过 §44。

## 3. 需求清单

- [ ] R1：信号对齐层 `signal_align.py`
  - 不同信号时间尺度对齐（缺口日级 + OFI 盘中 + 资金流 ?级 + 选股 T-1）→ 锚到 D 日统一时间戳
  - 每信号产标准化输出 `{signal_name, value, confidence, timestamp, source}`
  - 信号池：缺口 regime（S193）+ OFI（S176）+ breakout 选股（现有）+ 资金流 + 趋势臂
- [ ] R2：few-shot 检索引擎 `fewshot_retriever.py`（FS1，**不过 §44**）
  - 历史 case 库：trade_journal 1092 case 作起点（信号组合 + 后续走势）
  - 相似度检索：当前信号组合 → 检索历史 top-K 相似 case
  - 返：`[{historical_case, similarity, outcome}]` 喂 AI 研判
  - **caveat（spec grill HIGH#3）**：FS1 非确定 + 全库检索 lookahead 泄漏，**不过 §44 gate**——价值靠"AI 研判 + 用户反馈"定性评估，不参与 F1 消融 §44 验证
- [ ] R3：贝叶斯信号权重 `bayesian_signal_weight.py`（FS2，**可 OOS，参与 F1**）
  - 每信号 Beta-Bernoulli 先验（历史 reliability）→ 后验更新权重
  - 少样本下先验主导（专家设定 + 历史数据），样本增后验自适应
  - 输出：`{signal_name: weight}` 给融合层
- [ ] R4：融合层 `fusion_layer.py`
  - 输入：对齐后信号池 + few-shot 检索结果（FS1）+ 贝叶斯权重（FS2）
  - 输出：综合研判 `{regime, direction, confidence, top_similar_cases, signal_weights}` 喂 AI / 决策层
  - **不直接触发买卖**——喂 AI 综合研判 + 用户决策（§1 弱合规）
- [ ] R5：F1 消融验证（**只测 FS2，spec grill HIGH#3+#4 修订**）
  - 跑融合策略（含某信号 FS2 权重）vs 不含（其他不变）→ 对比融合 lift 增量
  - **只测 FS2 贝叶斯权重**（确定可 OOS），FS1 AI 检索不参与（非确定，§2.1）
  - 工具：复用 §44v2 verifier walk-forward OOS + S161 PurgedKFold
  - **统计功效约束（spec grill HIGH#4）**：leave-one-out 增量 delta << 单信号效应，n=1092 小样本检测边际贡献功效低——须给最小可检测效应量 + 功效门槛；**underpowered 标"探索性不判冗余"**（per §159 §44v2 应用规约"小 n 短窗标 underpowered 不判劣于随机"，复刻 §44v1 underpowered 假阴性的纠错）
- [ ] R6：F3 融合整体 §44（**spec grill CRITICAL#2 修订——selection 不可复现，改设计**）
  - **原设计问题**：用 selection edge_type 须 survivors_by_day（可复现的"哪些标的被选中"），但 R4"不触发买卖喂 AI+用户决策"→ AI 推理非确定 + 用户决策非确定 → survivors 不可复现定义，违反 §1.2 工程底线"判断须可复现"
  - **修订设计三选（实现时定）**：
    - (a) **FS2-only event edge**：F3 只测 FS2 贝叶斯权重触发的融合 event（确定），用 event edge_type（测群体收益 lift，不测选股力）——回答不了"融合能否选股"但可复现
    - (b) **冻结 AI 输出回测**：跑一次 FS1+FS2 融合，冻结 AI 输出作确定性 survivors→过 §44，但 verdict 只适用那次冻结（非策略一般选股力）
    - (c) **只验 FS2 selection**：F3 只测 FS2 权重排序的 selection edge（survivors=FS2 权重 top-N，确定），排除 FS1
  - **推荐 (a) FS2-only event edge**——最简 + 可复现 + 诚实（不声称测选股力，测融合 event 群体收益）
  - 过 §44 2x lift → 融合有效；不过 → 标"融合无 validated edge"降级（接受可能重发现 multifactor null，见 §1.1）

## 4. 受影响文件（spec grill MEDIUM#6 修订——复用 multifactor）

| 文件 | 改动 |
|---|---|
| `backend/engine/signal_align.py` | **新建**：信号对齐层（多尺度时间戳对齐） |
| `backend/engine/fewshot_retriever.py` | **新建**：FS1 few-shot 检索引擎（不过 §44） |
| `backend/engine/bayesian_signal_weight.py` | **新建**：FS2 贝叶斯信号权重（延伸 S180，可 OOS） |
| `backend/engine/fusion_layer.py` | **新建**：融合层（综合研判产出，喂 AI） |
| `backend/chat.py` | 融合层接 system prompt（AI 研判带融合输出） |
| `backend/tools/ablation_runner.py` | **新建**：F1 消融跑（**复用 multifactor_combo_validation.py 的 walk-forward/Bonferroni/OOS 框架**，非从零造——spec grill MEDIUM#6 DRY） |

**复用 multifactor_combo_validation.py**（spec grill MEDIUM#6）：F1 消融 + F3 融合§44 实质是 multifactor_combo_validation 的弱化版（FS2 贝叶斯权重 < multifactor 的 ML 组合严，但 OOS 框架可复用）。ablation_runner 继承 multifactor 的 walk-forward CV + Bonferroni + anti-feature-selection 框架，FS2 权重作 feature 输入，不重造。

## 5. 验收

- [ ] A1：signal_align 把 4+ 信号对齐到 D 日（缺口/OFL/选股/资金流）
- [ ] A2：fewshot_retriever 检索历史 top-K 相似 case（trade_journal 起点，不过 §44）
- [ ] A3：bayesian_signal_weight 给信号权重（Beta-Bernoulli 后验，可 OOS）
- [ ] A4：fusion_layer 产综合研判喂 AI（飞书 bot 问股时带融合输出）
- [ ] A5：F1 消融跑 FS2 权重增量贡献（只测 FS2，含功效约束 + underpowered 标探索性）
- [ ] A6：F3 融合整体 §44 verdict（FS2-only event edge，过/不过 2x lift）
- [ ] A7：pytest not live 全绿

## 6. 风险与盲点

- **小样本**：1092 case few-shot 检索可能检索到不相似 case——相似度阈值 + 案例数要诚实标注
- **贝叶斯先验设定**：信号权重先验靠专家判断（少样本下影响大），须标"先验驱动非数据驱动"
- **信号条件独立性**：FS2 贝叶斯假设信号独立，但实际信号相关——先验约束下风险可控，后期可加相关性校正
- **F1 消融 underpowered（spec grill HIGH#4）**：leave-one-out 小样本功效低，可能假"冗余"verdict（Type II，复刻 §44v1 假阴性）——须给最小可检测效应量 + underpowered 标"探索性不判冗余"
- **F3 不可复现（spec grill CRITICAL#2）**：FS1 AI 推理 + 用户决策非确定 → survivors 不可复现 → F3 改 FS2-only event edge（可复现但不测选股力，诚实降级）
- **multifactor null 对账风险（spec grill CRITICAL#1）**：S194 可能重发现 multifactor null（F1 全冗余 + F3 无 edge）=白费 5 跑 §44；或用更弱方法推翻高置信 null 须非凡证据——接受风险，诚实标注

## 7. 分阶段

1. **Phase 1**：S195 图谱认知层（done）
2. **Phase 2**：S193 缺口函数（done，classify_gap 11 测试绿）
3. **Phase 3**：S194 融合基线（本 spec，最重）—— 信号对齐 + few-shot 引擎 + 贝叶斯权重 + F1 消融（只 FS2）+ F3（FS2-only event edge）
4. **Phase 4**（后期）：数据够 5000+ case + **engage multifactor null**（论证新 ML 机制 ≠ 已证否的 ML 多因子，或接受重走证否路）+ 过 S161 DSR/PBO → 上 ML 框架

## 8. 关联

- [[S193-缺口理论集成]]（缺口 regime 作融合池一信号）
- [[S171-长线价值]]（价值因子信号）
- `backend/tools/multifactor_combo_validation.py`（已证否的 ML 多因子融合，§1.1 对账 + §4 复用 OOS 框架）
- `multiline-strategy-direction`（multifactor null verdict）
- `s168-12harness-verdict-selection-no-edge`（单信号 §44 证否——S194 验融合不验单信号的方法论修正）
- `rigorous-methodology-timely-retrospective-no-hallucination`（F1 消融 + F3 融合§44 防外推 + engage 先验 null）
- `s44-v1-wrong-window-retrospective`（F1 underpowered 假阴性复刻警示）
- `s193-195-spec-grill-findings-2026-09-12`（本 spec grill 6 真问题修订依据）
- `bayesian_arm_size` S180（FS2 贝叶斯权重延伸基础）
