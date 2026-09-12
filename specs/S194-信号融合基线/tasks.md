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

- [x] T5.1 `tools/ablation_runner.py` 新建——F1 消融跑（含某信号 FS2 权重 vs 不含）
  - 依赖：bayesian_signal_weight（R3 FS2 权重）+ multifactor_combo_validation.py（_permutation_pval 复用）+ §44v2 verifier
  - 验收：每信号跑出增量贡献 ✅ v2 重设计后 13 测试绿（build_fusion_composite + run_composite_ablation + composite_ablation_verdict）
  - effort: medium-high
  - 实现注 v1→v2 重设计（adversarial verify 报 CRITICAL 后）：v1 把 feature=信号值×FS2权重 喂 walk_forward_cv ML 模型，但 FS2 权重是 per-signal 常量被 StandardScaler+树阈值数学吃掉（模型看不见权重）→ 测的是信号值本身预测力（= multifactor null 弱化重测）非 FS2 权重贡献。v2 改融合分 Σ(值×权重) 作单一预测分数（权重直接乘数无模型能吃掉），消融时权重设 0，per-fold walk-forward + delta 置换 p + 跨信号 Bonferroni + underpowered 区分 harmful/模糊 + 1 信号/0 折边界 guard。不喂 walk_forward_cv 模型（融合分自身即预测，IC=spearman）。
- [x] T5.2 统计功效约束——给最小可检测效应量 + 功效门槛；**underpowered 标"探索性不判冗余"**（per §159 §44v2 应用规约）
  - 验收：功效分析 + underpowered caveat 标注 ✅ v2：composite_ablation_verdict 用 delta_pval（非 full_pval，修 v1 错假设）+ adjusted_alpha=bonf_alpha/K（跨信号 Bonferroni，v1 缺）+ underpowered 分 harmful（delta<0）/exploratory（delta>0，修 v1 一视同仁 bug）
  - effort: low（分析 + 文档）
- [x] T5.3 F1 消融实测——跑信号增量贡献排序
  - 验收：信号增量排序 + underpowered 标注 ✅ v2 实测跑通（reconstruct_s194_signals.py 重建 1048 case 的 breakout+gap 信号值，run_s194_ablation.py 跑融合分消融）
  - effort: low
  - 实测结果（v2）：融合分 IC≈0.033（无 edge）；breakout 权重有害（delta_ic=-0.03，移除后 IC 升 0.033→0.064，verdict=exploratory_harmful）；gap 权重略正（delta_ic=+0.013，p=0.23 非显著，verdict=exploratory）；两信号均 underpowered（n_days=52<60）不判。breakout 胜率 33.4%（316 赢/631 输）本就是 §44 证否弱信号，权重低(0.334)加进融合分等于加噪声——结果合理。
  - ⚠️ 局限：只测了 breakout+gap 2 信号（ofi 历史逐笔无法回补；fund_flow 网络限流本轮跳）；FS2 权重用全量 reliability 算（lookahead），但 underpowered verdict 不受影响；要严格 OOS 须 per-fold reliability_fn 重算权重（后续按需）。
  - 数据真相：dep-map agent 之前说"DB 空"是查错文件——.vibe-research/trade_journal.db 有 1092 行（breakout 1040+floor 52），本机就能跑。

### R6 · F3 融合整体 §44（FS2-only event edge）

- [x] T6.1 F3 用 **event edge_type**（不用 selection——spec grill CRITICAL#2 survivors 不可复现），survivors=FS2 权重触发的融合 event（确定可复现）
  - 依赖：§44v2 verifier + multifactor null（§1.1 对账）+ R3 FS2
  - 验收：event edge §44 verdict ✅ 5 测试绿（interpret_f3_verdict 纯函数 + run_s194_f3_verdict.py 跑通）
  - effort: low
  - 实现注：pass 门 = status=='robust_edge'（**非 2x lift**——event edge selection_lift 恒 None，dep map s44-verifier 视角确认原验收"过 §44 2x lift"与 event edge 矛盾，已修）；必须传 dates 做 day-clustering（n_effective=49 非 pooled 947，防 §44v1 inflate artifact）；round_trip_cost=0.007 进 materiality floor max(0.003, cost×0.5)。
- [x] T6.2 F3 实测——跑融合整体 §44，跟 multifactor null 对账（spec §1.1）——过 §44=融合有 edge；不过=重发现 multifactor null，诚实标"融合无 validated edge"降级
  - 验收：F3 verdict + multifactor null 对账结论 ✅
  - effort: low
  - 实测结果：status=underpowered（days_robust=49<60），event_status=event_thin_positive，day_mean=0.0024（+0.24%/日 正但微小），p_bh=0.497 非显著，n_effective=49（day-clustered）。fusion_conclusion=fusion_underpowered，null_engagement=consistent with multifactor null（无 validated 融合 edge，诚实降级 spec §6）。与 multifactor null 一致——融合基线无验证到的 edge，§44v2 underpowered 护栏没逼出假结论。
  - ⚠️ Phase 3a 代理局限：R4 融合层未建，F3 用现有真实交易（breakout arm 为主）收益当"融合 event"代理——测的是"系统当前交易有无 event edge"非"FS2 加权融合 event edge"。Phase 3b R4 建后用真 FS2 加权融合 event 收益复跑。

### Phase 3a 验证闭环

- [ ] T3a.1 跑 Phase 3a minimal 链路（R1+R3+R5+R6）——验"融合有无 §44 edge"
  - 验收：F1 消融增量 + F3 event §44 verdict，跟 multifactor null 对账
  - effort: low（汇总 T5.3+T6.2）

## Phase 3b · AI 研判层（Phase 3a 验出有 edge 才投，避免白费）

### R2 · fewshot_retriever FS1 检索（不过 §44）

- [x] T2.1 `engine/fewshot_retriever.py` 新建——`FewshotRetriever` 类，检索历史相似 case（trade_journal 1092 case 起点），相似度先 cos/Jaccard
  - 依赖：signal_align（R1 对齐后信号）+ reconstruct_s194_signals.py 重建的 case 信号值
  - 验收：当前信号组合 → top-K 相似历史 case ✅ 13 测试绿（cosine_sim + encode_case + retrieve + FewshotRetriever 类）
  - effort: medium（检索 + 相似度度量）
  - 实现注：case 库用 reconstruct_s194_signals.py 重建的 breakout_score + gap_regime_encoded 作特征；query 当天对齐信号；cosine 相似度 top-K；outcome 按 net_pnl 符号分类 hit/miss/neutral 喂 AI。
- [x] T2.2 标 **FS1 不过 §44 caveat**（spec grill HIGH#3——非确定 + 全库 lookahead 泄漏），价值靠 AI 研判 + 用户反馈定性
  - 验收：caveat 标注 + 不过 §44 gate ✅ 模块 docstring 明标 FS1 不过 §44（非确定 AI + 全库 lookahead，§44v2 verifier 套不上），不参与 F1 消融 §44 验证
  - effort: low（文档）
- [x] T2.3 单测 `tests/test_fewshot_retriever.py`——检索 top-K case + 相似度边界
  - 验收：检索正确 + 边界 ✅ 13 测试（TestCosineSim 4 + TestEncodeCase 3 + TestRetrieve 4 + TestFewshotRetriever 2）
  - effort: low

### R4 · fusion_layer 融合层

- [x] T4.1 `engine/fusion_layer.py` 新建——`fusion_layer(signals_aligned, fs1_results, fs2_weights) -> {regime, direction, confidence, top_similar_cases, signal_weights}`，综合 FS1 检索结果 + FS2 权重 → 研判产出喂 AI
  - 依赖：signal_align（R1）+ fewshot_retriever（R2 FS1）+ bayesian_signal_weight（R3 FS2）
  - 验收：产综合研判 dict 喂 AI ✅ 9 测试绿（regime from gap / direction from regime / FS2 加权 confidence / 透传 top_similar_cases + signal_weights）
  - effort: medium（综合逻辑 + 格式）
  - 实现注：regime 取 gap 信号 value（缺口 regime），无 gap→"未知"；direction 由 regime 派生（启动/中继→向上，反转/噪声→中性，反转歧义由 AI 终判）；confidence=Σ(sig_conf×fs2_weight)/Σ(fs2_weight)（信号不在 weights→权重 0 排除）；不触发买卖喂 AI（§1 弱合规）。
- [x] T4.2 接 chat.run_chat system prompt——飞书 bot 问股时注入融合输出（AI 综合研判带 regime/方向/置信度/top 相似 case）
  - 依赖：fusion_layer（R4.1）+ chat.py run_chat + 信号适配器（gap/breakout）
  - 验收：飞书 bot 问股带融合输出 ✅ run_chat 加 fusion_output 参数（默认 None 向后兼容）注入 build_fusion_context；tools/run_fusion_for_query.py 全链路跑通（bars→gap+breakout 适配器→align→fewshot→weights→fusion→context）
  - effort: low（接 system prompt）
  - 实现注：run_chat(fusion_output=...) 可选参数，有则 build_fusion_context 拼进 context 填 SYSTEM_PROMPT。compute_fusion_for_query(stock,date) 跑全链路产 fusion_output。飞书 bot 接线（parse stock→compute_fusion_for_query→run_chat）是最后生产连线步骤。
  - 实测（600519@2026-09-10）：regime=无（无缺口）、direction=中性、confidence=0.38、breakout 权重 0.334/gap 0.5、fewshot 检索 3 相似 case。链路通。

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
