# Tasks: S194 — 信号融合基线

> 状态：spec✅（grill 6 真问题修）→ plan✅ → tasks（本文件）→ 实现
> 依赖序：R1→R3→R5→R6（Phase 3a minimal 验证闭环）→R2→R4（Phase 3b AI 研判层）

## Phase 3a · minimal 验证闭环（FS2-only 链路，先验"融合有无 edge"）

### R1 · signal_align 信号对齐层

- [x] T1.1 `engine/signal_align.py` 新建——纯函数 `align_signals(signals: list[dict], target_date: str) -> list[dict]`，把异质信号（缺口日级 + OFI 盘中 + 资金流 + 选股 T-1）锚到 D 日统一时间戳，标准化 `{signal_name, value, confidence, timestamp, source}` 格式
  - 依赖：S193 classify_gap + S176 OFI + breakout 选股 + stock_fund_flow + S181 趋势臂（信号源已存在）
  - 验收：4+ 信号对齐到 D 日，时间戳统一，格式标准化 ✅ 13 测试绿（test_mixed_time_scales_all_anchored_to_d 验 5 信号锚 D）
  - effort: medium（时间尺度对齐逻辑 + 标准化）
  - 实现注：统一锚定 timestamp=target_date（日级/盘中/T-1 全锚 D）；value=None 跳过不臆造；per-source 适配器（gap→regime / ofi row→ofi / breakout→score 等）留调用方/后续 adapter，本函数不耦合具体源（YAGNI）
- [x] T1.2 单测 `tests/test_signal_align.py`——异质信号对齐 case（日级/盘中/T-1 混合）+ 边界（缺信号/时间戳错）
  - 验收：对齐逻辑正确 + 边界不炸 ✅ 13 测试（3 类：TestAlignTimestamps 4 / TestStandardizeFormat 3 / TestEdgeCases 6）
  - effort: low

### R3 · bayesian_signal_weight FS2 贝叶斯权重

- [x] T3.1 `engine/bayesian_signal_weight.py` 新建——`BayesianSignalWeight` 类，每信号 Beta-Bernoulli 先验（历史 reliability）→ 后验更新权重，延伸 S180 bayesian_arm_size 的 Beta-Bernoulli 模式
  - 依赖：S180 bayesian_arm_size（复用 Beta-Bernoulli 模式）+ signal_align 对齐后信号 + trade_journal 历史 reliability 数据
  - 验收：给每信号产 `{signal: weight}` 后验权重，少样本下先验主导 ✅ 19 测试绿（weights 批量产 {signal:weight}，Beta(1,1)+0 数据→0.5 先验主导）
  - effort: medium（Beta-Bernoulli 后验 + 历史可靠性数据接入）
  - 实现注：后验**均值**闭式 `(α+s)/(α+β+s+f)` 无 scipy（bayesian_arm_size 的 ppf(0.05) 用于保守仓位 sizing，权重用均值语义不同）；per-signal 先验 dict + weight/weights 方法；reliability_tier 复刻 §44v2 分级（n<30 insufficient / n_days<60 underpowered / ≥60 robust）
- [x] T3.2 先验设定——信号权重先验靠专家判断（缺口/OFL/选股/资金流/趋势 各初始可靠性）+ 标"先验驱动非数据驱动"（spec §6 风险）
  - 验收：5 信号先验值 + caveat 标注 ✅ DEFAULT_SIGNAL_PRIORS 5 信号全 Beta(1,1) 无信息（诚实基线不预置未证实 edge），docstring 标先验驱动 + ofi/fund_flow 无 arm 历史长期靠先验
  - effort: low（设定值 + 文档）
- [x] T3.3 单测 `tests/test_bayesian_signal_weight.py`——Beta-Bernoulli 后验更新 case（先验+数据→权重）+ 边界（零数据/全对/全错）
  - 验收：后验收敛正确 + 边界不炸 ✅ 19 测试（3 类：TestBetaBernoulliWeight 8 含先验拉扯/保守先验/数据压过先验 + TestReliabilityTier 6 含边界 + TestBayesianSignalWeight 5 含 per-signal/default/批量/空）
  - effort: low

### R5 · ablation_runner F1 消融（只 FS2，复用 multifactor OOS 框架）

- [x] T5.1 `tools/ablation_runner.py` 新建——F1 消融跑（含某信号 FS2 权重 vs 不含），**复用 multifactor_combo_validation.py 的 walk-forward CV + Bonferroni + anti-feature-selection OOS 框架**（继承，非重造，spec grill MEDIUM#6 DRY）
  - 依赖：bayesian_signal_weight（R3 FS2 权重作 feature 输入）+ multifactor_combo_validation.py（OOS 框架）+ §44v2 verifier
  - 验收：每信号（缺口/OFL/选股/资金流）跑出增量贡献 ✅ 11 测试绿（build_ablation_matrix + run_signal_ablation + ablation_verdict 纯逻辑，walk_forward_fn 注入可 mock）
  - effort: medium-high（复用框架 + FS2 权重作 feature 接入）
  - 实现注：feature[case,signal]=信号值×FS2权重 per-case（权重单独无方差模型学不到）；walk_forward_fn 注入（组合非 OOP 继承，per dep map）；build_ablation_matrix 接重建后的 cases_signal_values + fs2_weights，不耦合信号源（T5.3 接重建管线）
- [x] T5.2 统计功效约束——给最小可检测效应量 + 功效门槛（spec grill HIGH#4）；**underpowered 标"探索性不判冗余"**（per §159 §44v2 应用规约"小 n 短窗标 underpowered 不判劣于随机"）
  - 验收：功效分析 + underpowered caveat 标注 ✅ ablation_verdict 套 reliability_tier（n<30 insufficient / n_days<60 underpowered → "exploratory" 不判冗余 + caveat 标注；robust → contributes/redundant/no_contribution by delta_ic+pval）
  - effort: low（分析 + 文档）
- [ ] T5.3 F1 消融实测——跑 4 信号（缺口/OFL/选股/资金流）增量贡献排序
  - 验收：4 信号增量排序 + underpowered 标注
  - effort: low（跑现有框架）
  - ⏳ 数据阻塞：需生产 trade_journal.db（1092 case）+ per-case 信号值重建（重跑 4 信号生成器），本机 DB 空（dep map 确认两份 DB size 0）→ 延后到能访问生产 DB 时跑

### R6 · F3 融合整体 §44（FS2-only event edge）

- [ ] T6.1 F3 用 **event edge_type**（不用 selection——spec grill CRITICAL#2 survivors 不可复现），survivors=FS2 权重触发的融合 event（确定可复现）
  - 依赖：ablation_runner（R5 框架）+ bayesian_signal_weight（R3 FS2）+ §44v2 verifier
  - 验收：event edge §44 verdict 过/不过 2x lift
  - effort: low（R5 框架延伸）
- [ ] T6.2 F3 实测——跑融合整体 §44，跟 multifactor null 对账（spec §1.1）——过 §44=融合有 edge；不过=重发现 multifactor null，诚实标"融合无 validated edge"降级
  - 验收：F3 verdict + multifactor null 对账结论
  - effort: low（跑 + 对账）

### Phase 3a 验证闭环

- [ ] T3a.1 跑 Phase 3a minimal 链路（R1+R3+R5+R6）——验"融合有无 §44 edge"
  - 验收：F1 消融增量 + F3 event §44 verdict，跟 multifactor null 对账
  - effort: low（汇总 T5.3+T6.2）

## Phase 3b · AI 研判层（Phase 3a 验出有 edge 才投，避免白费）

### R2 · fewshot_retriever FS1 检索（不过 §44）

- [ ] T2.1 `engine/fewshot_retriever.py` 新建——`FewshotRetriever` 类，检索历史相似 case（trade_journal 1092 case 起点），相似度先 cos/Jaccard
  - 依赖：signal_align（R1 对齐后信号）+ trade_journal 1092 case（实测 rows）
  - 验收：当前信号组合 → top-K 相似历史 case
  - effort: medium（检索 + 相似度度量）
- [ ] T2.2 标 **FS1 不过 §44 caveat**（spec grill HIGH#3——非确定 + 全库 lookahead 泄漏），价值靠 AI 研判 + 用户反馈定性
  - 验收：caveat 标注 + 不过 §44 gate
  - effort: low（文档）
- [ ] T2.3 单测 `tests/test_fewshot_retriever.py`——检索 top-K case + 相似度边界
  - 验收：检索正确 + 边界
  - effort: low

### R4 · fusion_layer 融合层

- [ ] T4.1 `engine/fusion_layer.py` 新建——`fusion_layer(signals_aligned, fs1_results, fs2_weights) -> {regime, direction, confidence, top_similar_cases, signal_weights}`，综合 FS1 检索结果 + FS2 权重 → 研判产出喂 AI
  - 依赖：signal_align（R1）+ fewshot_retriever（R2 FS1）+ bayesian_signal_weight（R3 FS2）
  - 验收：产综合研判 dict 喂 AI
  - effort: medium（综合逻辑 + 格式）
- [ ] T4.2 接 chat.run_chat system prompt——飞书 bot 问股时注入融合输出（AI 综合研判带 regime/方向/置信度/top 相似 case）
  - 依赖：fusion_layer（R4.1）+ chat.py TOOLS（§3 约定）
  - 验收：飞书 bot 问股带融合输出
  - effort: low（接 system prompt）

### Phase 3b 闭环

- [ ] T3b.1 跑 Phase 3b AI 研判链路（R2+R4+T4.2）——飞书 bot 问股带融合输出
  - 依赖：Phase 3a 验出有 edge（T3a.1）
  - 验收：飞书 bot 问股返融合研判
  - effort: low（汇总）

## 验收（spec §5）

- [ ] A1：signal_align 把 4+ 信号对齐到 D 日（T1.1）
- [ ] A2：fewshot_retriever 检索历史 top-K 相似 case（T2.1，不过 §44）
- [ ] A3：bayesian_signal_weight 给信号权重 Beta-Bernoulli 后验（T3.1，可 OOS）
- [ ] A4：fusion_layer 产综合研判喂 AI（T4.1+T4.2）
- [ ] A5：F1 消融跑 FS2 权重增量贡献（T5.3，含功效约束 + underpowered 标探索性）
- [ ] A6：F3 融合整体 §44 verdict（T6.2，FS2-only event edge，过/不过 2x lift）
- [ ] A7：pytest not live 全绿（含新单测 T1.2/T2.3/T3.3）

## 不做（超范围 / YAGNI / grill 已否）

- FS3 k-NN（spec §2 跳过——距离定义难 + 不如 FS1 AI 推理灵活）
- FS1 过 §44（spec grill HIGH#3——非确定 + 全库 lookahead 泄漏，套不上 verifier）
- selection edge F3（spec grill CRITICAL#2——survivors 不可复现）
- 从零造 ablation_runner OOS（spec grill MEDIUM#6——复用 multifactor_combo_validation.py 框架）
- Phase 4 ML（spec §7——数据够 5000+ + engage multifactor null 后再说）
