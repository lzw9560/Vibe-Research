# Spec: S194 — 信号融合基线（few-shot 检索 + 贝叶斯权重 + 消融验证）

> 状态：草案（grill-me 2026-09-12 Q14-Q16 定方法论）
> 作者：Claude  日期：2026-09-12
> 分级：large（新基建——信号对齐层 + few-shot 引擎 + 贝叶斯权重 + F1 消融验证）
> 关联：[[../S193-缺口理论集成/spec.md]]（缺口 regime 作融合池一信号）、[[../S171-长线价值/spec.md]]（价值因子信号）、`s168-12harness-verdict-selection-no-edge`、`rigorous-methodology-timely-retrospective-no-hallucination`

## 1. 问题 / 目标

**方法论修正（Q13-Q14 grill）**：项目 §44v2 至今验的全是**单信号买卖 lift**（breakout 选股证否、T+0 OFI 证否、gap 隔夜 net≈0）——但用户反思：**"所有信号独立分析都可能没价值，融合判断才是正确思路"**。单信号 §44 不过 ≠ 融合无价值。

**目标**：搭信号融合基线——把分散信号（缺口 regime + OFI + 选股 + 资金流 + 趋势臂）聚到一层，用 **few-shot 检索 + 贝叶斯权重**融合，**不验单信号 §44**，验 **F1 消融**（加某信号 vs 不加的融合 lift 增量）+ **F3 融合整体 §44**。

## 2. 融合架构（Q15-Q16 grill 定）

**不上 ML 框架（Q15）**——1092 trades 小样本，训练模型必过拟合（S161 DSR/PBO 会证）。先 **few-shot 统计融合**，后期数据够（5000+ case）再上 ML。

**两范式结合**：

- **FS1 检索式 few-shot（RAG 风格，喂 AI）**：AI 查当前信号组合（缺口 regime + OFI + 资金流）→ 检索历史相似 case（trade_journal 1092 case 起点）→ AI 综合研判。**融合不靠模型，靠 AI 推理 + 历史案例**。零训练 + 可解释。
- **FS2 贝叶斯更新（信号权重）**：延伸 bayesian_arm_size S180（Beta-Bernoulli）作信号 reliability 先验——某信号历史准→权重高，不准→权重低。少样本下先验主导，样本增后验收敛。数学严谨 + 自适样本量。

**跳过 FS3 k-NN**——距离定义难（不同信号尺度）+ 不如 FS1 AI 推理灵活，YAGNI。

## 3. 需求清单

- [ ] R1：信号对齐层 `signal_align.py`
  - 不同信号时间尺度对齐（缺口日级 + OFI 盘中 + 资金流 ?级 + 选股 T-1）→ 锚到 D 日统一时间戳
  - 每信号产标准化输出 `{signal_name, value, confidence, timestamp, source}`
  - 信号池：缺口 regime（S193）+ OFI（S176）+ breakout 选股（现有）+ 资金流 + 趋势臂
- [ ] R2：few-shot 检索引擎 `fewshot_retriever.py`（FS1）
  - 历史 case 库：trade_journal 1092 case 作起点（信号组合 + 后续走势）
  - 相似度检索：当前信号组合 → 检索历史 top-K 相似 case
  - 相似度度量：信号组合向量距离（先简单 cos/Jaccard，后期可改）
  - 返：`[{historical_case, similarity, outcome}]` 喂 AI 研判
- [ ] R3：贝叶斯信号权重 `bayesian_signal_weight.py`（FS2，延伸 S180）
  - 每信号 Beta-Bernoulli 先验（历史 reliability）→ 后验更新权重
  - 少样本下先验主导（专家设定 + 历史数据），样本增后验自适应
  - 输出：`{signal_name: weight}` 给融合层
- [ ] R4：融合层 `fusion_layer.py`
  - 输入：对齐后信号池 + few-shot 检索结果 + 贝叶斯权重
  - 输出：综合研判 `{regime, direction, confidence, top_similar_cases, signal_weights}` 喂 AI / 决策层
  - **不直接触发买卖**——喂 AI 综合研判 + 用户决策（§1 弱合规）
- [ ] R5：F1 消融验证（Q14 核心）
  - 跑融合策略（含某信号）vs 不含（其他不变）→ 对比融合 lift 增量
  - 每信号一跑（缺口/OFL/选股/资金流各消融一次）→ 增量贡献排序
  - 无增量信号 → 标"冗余"不集成（或降权重）
  - 工具：复用 §44v2 verifier（event/selection edge_type）+ S161 PurgedKFold/walk-forward OOS
- [ ] R6：F3 融合整体 §44
  - 融合策略整体过 §44v2（selection edge_type，survivors=融合触发标的，universe=全 A/候选池）
  - 过 §44 2x lift → 融合有效；不过 → 标"融合无 validated edge"降级
  - **不验单信号 §44**（Q13 反思——单信号无 edge ≠ 融合无 edge）

## 4. 受影响文件

| 文件 | 改动 |
|---|---|
| `backend/engine/signal_align.py` | **新建**：信号对齐层（多尺度时间戳对齐） |
| `backend/engine/fewshot_retriever.py` | **新建**：few-shot 检索引擎（历史 case 库 + 相似度） |
| `backend/engine/bayesian_signal_weight.py` | **新建**：贝叶斯信号权重（延伸 bayesian_arm_size S180） |
| `backend/engine/fusion_layer.py` | **新建**：融合层（综合研判产出，喂 AI） |
| `backend/chat.py` | 融合层接 system prompt（AI 研判带融合输出） |
| `backend/tools/ablation_runner.py` | **新建**：F1 消融跑（每信号加 vs 不加对比） |

## 5. 验收

- [ ] A1：signal_align 把 4+ 信号对齐到 D 日（缺口/OFL/选股/资金流）
- [ ] A2：fewshot_retriever 检索历史 top-K 相似 case（trade_journal 起点）
- [ ] A3：bayesian_signal_weight 给信号权重（Beta-Bernoulli 后验）
- [ ] A4：fusion_layer 产综合研判喂 AI（飞书 bot 问股时带融合输出）
- [ ] A5：F1 消融跑出每信号增量贡献排序（缺口/OFL/选股/资金流）
- [ ] A6：F3 融合整体 §44 verdict（过/不过 2x lift）
- [ ] A7：pytest not live 全绿

## 6. 风险与盲点

- **小样本**：1092 case few-shot 检索可能检索到不相似 case——相似度阈值 + 案例数要诚实标注
- **贝叶斯先验设定**：信号权重先验靠专家判断（少样本下影响大），须标"先验驱动非数据驱动"
- **信号条件独立性**：FS2 贝叶斯假设信号独立，但实际信号相关（缺口+OFI 可能都跟资金流相关）——先验约束下风险可控，后期可加相关性校正
- **F1 消融工作量**：每信号一跑 §44（缺口/OFL/选股/资金流 4 跑）+ 融合整体 1 跑 = 5 跑，工作量大但一次性
- **F3 融合整体 universe 定义**：融合多信号后 survivors/universe 复杂，要清晰定义

## 7. 分阶段

1. **Phase 1**：S195 图谱认知层（最快，纯文档）
2. **Phase 2**：S193 缺口函数（纯函数 + chat.TOOLS，可独立验分类准确率）
3. **Phase 3**：S194 融合基线（本 spec，最重）—— 信号对齐 + few-shot 引擎 + 贝叶斯权重 + F1 消融
4. **Phase 4**（后期）：数据够 5000+ case + 过 S161 DSR/PBO → 上 ML 框架

## 8. 关联

- [[S193-缺口理论集成]]（缺口 regime 作融合池一信号，S193 先于 S194）
- [[S171-长线价值]]（价值因子信号，可进融合池）
- `s168-12harness-verdict-selection-no-edge`（单信号 §44 证否——S194 验融合不验单信号的方法论修正）
- `rigorous-methodology-timely-retrospective-no-hallucination`（F1 消融 + F3 融合§44 防外推）
- `bayesian_arm_size` S180（FS2 贝叶斯权重延伸基础）
