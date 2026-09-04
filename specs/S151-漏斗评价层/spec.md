# Spec: S151 — 漏斗评价层（预登记+降权梯度+回溯+诚实标注+即时处理）

> 状态：草案（§F breakout ×0.5 vs ×0.1 待用户拍板 + 待 T5.2 审查 workflow）
> 作者：Claude  日期：2026-09-04
> 关联：S150（采集修复）、S153（量化模型验证）、[量化模型验证路线.md](../量化模型验证路线.md)

## 1. 问题 / 目标

§44 证否选股维度（gene rho≈0 / breakout 1.36 / 换手 0.9979 / 封单 0.9897 / path_lift 0.978 全<2x 或<1），但当前 candidate_funnel 漏斗用 gene/breakout（已证无效）+ 换手剔除（robust<1），**4 套评分（gene_score/eight_standards/first_board_analysis/strategy_score）无统一评价层**，`capped` 二值封顶是最接近的。用户看漏斗以为选股有 edge，实际无。

**目标**：为漏斗新增统一评价层，透明嵌入 `_run_funnel_impl`（funnel.py:466，card 构建后、return 前），5 支柱：(1) 预登记冻结 DIMENSION_LIFT_REGISTRY（§44 已测值静态冻结，commit hash 锁定）+ (2) 降权梯度（×0.1/×0.5/×1.0 不硬剔）+ (3) 30日+n≥100 首次回溯 60日复验 + (4) 诚实标注（"选股层无 validated 维度，edge 待盘中验证"）+ (5) 选股层即时处理（换手×0.1 踢出 + gene×0.1 保留采数 + tradability 硬剔保留 R2）。不改 R1/R2/SELF 三层结构、不新增 API。

## 2. 背景

- 漏斗 3 层（S148 b 重构后）：R1 fetch / R2 `_filter_tradability`（ST/创业/退市硬剔）/ SELF watchlist → build_diagnosis_card
- 4 套评分无统一评价层：gene_score（rho≈0）/ eight_standards（capped 二值封顶）/ first_board_analysis（9维加权）/ strategy_score（_collect 独立）
- §44 基础设施可复用：`judge_lift_four_states`（first_board_settlement.py:272-298）/ `PASS_LIFT_FLOOR=2.0` `PASS_LIFT_HARD_FLOOR=1.0`（forward_test.py:35-36）/ `ForwardTestSummary`（forward_test.py:152-187）
- **关键缺口**：per-dimension lift 无可查询存储（换手0.9979/breakout1.36/gene rho≈0/封单0.9897 只硬编码在 docstring+记忆）→ 需新建 `DIMENSION_LIFT_REGISTRY`
- 即时处理时序：换手 lift<1→×0.1 踢出，但 turnover_pct 在 R2 之后采集（funnel.py:394-409），所以换手即时处理须在 activity 采集后（funnel.py:466），不能放 R2

## 3. 需求清单（R1-R6）

- [ ] R1 预登记冻结：新建 `backend/candidate_funnel/evaluation.py`，定义 `DIMENSION_LIFT_REGISTRY`（frozen dataclass），初始化为 §44 已测值静态冻结表（commit hash 锁定事后不调）。判定：lift≥2.0+CI不重叠+n≥100且≥30交易日→validated(×1.0)；1.0≤lift<2.0→未validated(×0.5)；lift<1.0 robust→劣于随机(×0.1)；n<30→探索性(×1.0 待数据)。初始冻结值（全部来自 §44 脚本输出，禁臆造）：gene_score{rho≈0.030,n:2332,days:38,劣于随机,×0.1} / breakout{1.363,n:43691,days:42,未validated,×0.5} / turnover{0.9979,n:14366,days:167,劣于随机,×0.1} / seal_amount{0.9897,n:177,days:5,探索性,×1.0} / path_lift{0.978,n:627/2708,days:44,劣于随机,×0.1}。vol_surge{2.046,validated,×1.0}标"非选股层参照"不参与降权
- [ ] R2 降权梯度：`lift_to_multiplier(lift,n,ci_overlap,robust)→(status,multiplier)` 纯函数，复用 `judge_lift_four_states` + `PASS_LIFT_FLOOR`/`PASS_LIFT_HARD_FLOOR` 常量。映射：lift<1 robust→('劣于随机',0.1) / 1≤lift<2→('未validated',0.5) / ≥2+CI不重叠→('validated',1.0) / n<30→('探索性',1.0)。不硬剔（tradability 硬剔保留 R2）。`compute_strategy_score`（strategy_funnel_registry.py:435 contribution=val*w）注入 runtime multiplier：contribution=val*w*multiplier（B2 运行时方案不改 strategy_weights.json 持久文件便于 A/B）
- [ ] R3 回溯触发：`scheduled_tasks.py` 新增 `evaluation_backtest` executor，复用 s066_validation_checkpoint 范式（line 1230-1267：数信号日→达阈值→写 checkpoint JSON+WARNING+返 DUE+操作指引；未到期返 not_due+进度）。两档：30日+n≥100→首次回溯（per-dimension day_paired_lift，复用 first_board_layer_lift.day_paired_lift:138 非池化防池化假象）；60日→复验（重跑 lift+判升级/降级）。回溯结果写 `VR_DATA_DIR/evaluation_lifts.db`（vr_paths 隔离不进 git），DIMENSION_LIFT_REGISTRY 从静态冻结表升级 DB-backed 动态读（首次回溯后生效）。到点只提醒不自动验证（同 s066）。seed 默认 task cron `0 18 * * 1`
- [ ] R4 诚实标注：FunnelResult 加 `evaluation_summary: Optional[dict]=None`（models.py:238 后，复用 market_context 同款），注入 {honest_label:"选股层无validated维度,edge待盘中验证", dimensions:[{dim_id,lift,n,status,weight,note}], pending_dims, frozen_commit}。DiagnosisCard 加 `evaluation: Optional[dict]=None`（models.py:173 后，复用 gene_score/seat_detail 同款），结构 {score_weight,lift_status,demoted_dims,honest_label,validation_note}，None=未接 evaluation 不阻断既有路径。前端 HonestyBanner.tsx:14-19 硬编码 bullet 替换为从 dimension_validations 动态渲染 per-dimension 列表+降权梯度表。FunnelLayerCard.tsx 得分 span 旁加降权 pill。DiagnosisCard.tsx GeneScoreBlock 补"§44 rho≈0，无方向性"标签。SelectionPipeline.tsx LayerStep 加验证状态 pill
- [ ] R5 选股层即时处理：新建 `_apply_evaluation_layer(cards,genes,activity,eff,date)` 在 funnel.py:466 插入。三步：(1) 即时处理——遍历 cards 查 activity[code].turnover_pct 存在+DIMENSION_LIFT_REGISTRY['turnover'].lift=0.9979 robust<1→evaluation.score_weight×0.1+status='demoted'（踢出排序但留 final_candidates 供审计）；gene_score 子对象存在→×0.1+status='unranked'（保留采数不参与排序）；tradability 已 R2 硬剔不重复。(2) 降权梯度——每卡按命中维度查 DIMENSION_LIFT_REGISTRY 调 lift_to_multiplier 映射。(3) 诚实标注——构建 evaluation_summary 挂 FunnelResult。函数签名遵循 `_filter_tradability` 范式（返 mutated cards list），复用 `attach_first_board_analysis` post-hoc card-mutation 模式（不改 build_diagnosis_card 的 9 参数）。eval 透明嵌 run_funnel，precompute/_collect/candidates router 无需改
- [ ] R6 合规与工程底线：(a) 不臆造——DIMENSION_LIFT_REGISTRY 初始值全来自 §44 脚本输出（gene_score_directionality/kline_ta_validation/first_board_layer_lift/s145_recompute_path），禁心算；(b) 私有数据隔离——回溯 DB 写 VR_DATA_DIR（vr_paths.resolve_data_dir）不进 git 不落 home；(c) 防封——评价层不新增东财端点，turnover/seal 复用已有 activity fetch（走 em_get 限流）；(d) 弱合规——用户可见输出挂轻量风险提醒"历史统计特征,市场有风险"；(e) §44 已降级参考性建议（S084 reframe），评价层降权不阻塞实现，标注用非门——passed=False 不阻断 run_funnel 返回

## 4. 受影响文件

| 文件 | 改动 |
|---|---|
| backend/candidate_funnel/evaluation.py（新） | R1-R2：DIMENSION_LIFT_REGISTRY + lift_to_multiplier + _apply_evaluation_layer |
| backend/candidate_funnel/models.py | R4：DiagnosisCard 加 evaluation + FunnelResult 加 evaluation_summary |
| backend/candidate_funnel/funnel.py | R5：line 466 插入 _apply_evaluation_layer 调用 |
| backend/strategies/strategy_funnel_registry.py | R2：line 435 contribution=val*w*multiplier + line 689 scored 加 evaluation |
| backend/scheduled_tasks.py | R3：evaluation_backtest executor + seed task |
| backend/tests/test_s151_evaluation_layer.py（新） | R1-R5 测试 |
| frontend/src/lib/candidates.ts | R4：DimensionValidation interface + PassedItem.evaluation? + FunnelResult.evaluation_summary? |
| frontend/src/components/ui/DimensionValidationBadge.tsx（新） | R4：色码徽标 红/琥珀/绿/灰 + Tooltip |
| frontend/src/components/ui/HonestyBanner.tsx | R4：动态渲染 per-dimension 列表 |
| frontend/src/components/ui/FunnelLayerCard.tsx | R4：维度徽标 + 降权 pill |
| frontend/src/components/candidate/DiagnosisCard.tsx | R4：GeneScoreBlock §44 rho≈0 标签 |
| frontend/src/components/pipeline/SelectionPipeline.tsx | R4：LayerStep 验证状态 pill |

## 5. 设计方案

**A. 预登记阈值表（DIMENSION_LIFT_REGISTRY）**：`backend/candidate_funnel/evaluation.py`，frozen dataclass `DimensionValidation` + 模块级 `DIMENSION_LIFT_REGISTRY: dict[str, DimensionValidation]`。每条含 dimension_id/label/lift/n/days_robust/ci_lo/ci_hi/validation_status/weight_multiplier/note/frozen_commit/frozen_at。初始冻结值见 R1（5 维度 + vol_surge 参照）。frozen_commit=写入时 git HEAD hash。回溯模块写 updated_commit+updated_at 不覆盖 frozen_*（审计追溯链）。判定复用 `judge_lift_four_states` + `PASS_LIFT_FLOOR=2.0`/`PASS_LIFT_HARD_FLOOR=1.0`。

**B. 降权梯度（lift_to_multiplier + _apply_evaluation_layer）**：纯函数 `lift_to_multiplier(lift,n,ci_overlap,robust)→(status,multiplier)`，映射劣于随机→0.1/未validated→0.5/validated→1.0/探索性→1.0。`_apply_evaluation_layer` 在 funnel.py:466 插入（card 构建后、return 前），复用 `attach_first_board_analysis` post-hoc card-mutation 范式（不改 build_diagnosis_card 9 参数）。三步：即时处理（换手 demoted+gene unranked）+降权梯度注入+诚实标注构建。

**C. 回溯 task（scheduled_tasks evaluation_backtest）**：复用 s066_validation_checkpoint 范式，数信号日→30日+n≥100 首次回溯/60日复验→写 checkpoint+WARNING+返 DUE+操作指引。回溯跑 per-dimension day_paired_lift（非池化防 4.686x→1.723x 假象）。结果写 VR_DATA_DIR/evaluation_lifts.db，DIMENSION_LIFT_REGISTRY 升级 DB-backed 动态读（首次回溯后生效，未回溯前用冻结值）。到点只提醒不自动验证。seed cron `0 18 * * 1`。

**D. 诚实标注（后端 FunnelResult + 前端动态渲染）**：FunnelResult.evaluation_summary 注入 honest_label+dimensions+pending_dims+frozen_commit。run_funnel 透明嵌入→调用方无需改。前端 candidates.ts 加 DimensionValidation interface；新建 DimensionValidationBadge.tsx（色码徽标）；HonestyBanner.tsx 动态渲染 per-dimension；FunnelLayerCard 加维度徽标+降权 pill；DiagnosisCard GeneScoreBlock 补 §44 rho≈0 标签（闭合诚实缺口——当前 gene_score 看似 validated 实际 rho≈0）；SelectionPipeline LayerStep 加验证状态 pill。

**E. 已知限制——proxy 映射 + per-factor §44 gap**：§44 验的是 composite（gene rho≈0）/TA feature（breakout 1.363）/filter（turnover 0.9979），但 strategy_weights.json 权重乘的是 7 个个体因子（红盘率/封板率/炸板后溢价/相对强度/均线多头/量能信号/板块强度），这些个体因子没被直接 §44 测过。评价层用 proxy 映射（gene composite rho≈0→推断 gene-based 因子也无方向性→×0.1，标注"indirect, composite→factor inference"）。per-factor §44 验证登记 follow-up（新 spec，复用 S153 R7/R8 harness 结构对每个 weight factor 跑 day_paired_lift）。S153 是"每维度 deep dive"（platform_breakout C3+low_absorption C3），评价层是"全维度 gradient 应用"——前者产出 lift/CI/n，后者消费它做降权。

**F. breakout ×0.5 vs ×0.1 差异（待用户拍板）**：用户框架"选股层即时处理"写"gene/breakout→×0.1 保留采数不参与排序"，但 breakout lift=1.363x（CI 不重叠，42 日 robust）按降权梯度 1≤lift<2→×0.5。**spec 按梯度严格执行 ×0.5**，理由：(1) 1.363x≥1 不该归"劣于随机"档；(2) 梯度规则是核心机制，breach 一处则全表可信度下降；(3) gene rho≈0 是真"无信号"（Spearman 无单调），breakout 1.363x 是"弱正信号"——两者本质不同不该同档。若用户认为 1.363x 离 2x 太远实质噪声，可在 DIMENSION_LIFT_REGISTRY 标 note='用户 override:1.363x→×0.1' 并冻结（显式 override 非默认梯度）。**此差异留待用户拍板**。

**G. 复用点清单**：judge_lift_four_states / PASS_LIFT_FLOOR+PASS_LIFT_HARD_FLOOR / ForwardTestResult / attach_first_board_analysis post-hoc 范式 / _filter_tradability 硬剔范式 / DiagnosisCard Optional[dict] 降级 / _wilson/_wilson_pct / day_paired_lift（非池化）/ four_state / s066_validation_checkpoint / S153 R7/R8 harness 结构。

## 6. 验收标准

- [ ] A1 DIMENSION_LIFT_REGISTRY 含 5 维度初始冻结值，每条 frozen_commit 非空（git HEAD hash）
- [ ] A2 lift_to_multiplier(0.9979,14366,robust=True)→('劣于随机',0.1)
- [ ] A3 lift_to_multiplier(1.363,43691,robust=True)→('未validated',0.5)（breakout 按梯度 ×0.5，§F 差异）
- [ ] A4 lift_to_multiplier(2.046,43691,ci_overlap=False)→('validated',1.0)（vol_surge 参照）
- [ ] A5 run_funnel(any_date) 返 FunnelResult.evaluation_summary 非空，honest_label='选股层无validated维度,edge待盘中验证'
- [ ] A6 turnover robust<1 候选 DiagnosisCard.evaluation.status='demoted'，score_weight=0.1
- [ ] A7 gene_score 维度候选 DiagnosisCard.evaluation.status='unranked'，score_weight=0.1（保留 final_candidates 标不参与排序）
- [ ] A8 DiagnosisCard.evaluation=None 时既有路径不阻断，model_dump 序列化正常
- [ ] A9 compute_strategy_score 注入 multiplier 后 gene 因子 contribution=val*w*0.1（缩10×），非 gene 因子 ×1.0 不变
- [ ] A10 HonestyBanner.tsx 从 dimension_validations 动态渲染 per-dimension 列表（非硬编码）；全维度<2x 时显"选股层无validated维度"
- [ ] A11 FunnelLayerCard.tsx 得分 span 旁有降权 pill：×0.1 红/×0.5 琥珀/×1.0 无 pill
- [ ] A12 DiagnosisCard.tsx GeneScoreBlock 有"§44 rho≈0，无方向性"标签，与 first_board_analysis 标签模式对齐
- [ ] A13 SelectionPipeline.tsx LayerStep 折叠态 layer_id 旁有验证状态 pill（R1 琥珀/R2 红/SELF 无）
- [ ] A14 scheduled_tasks evaluation_backtest task 在 30日+n≥100 时写 checkpoint+WARNING+返 DUE+操作指引；未到点返 not_due+进度
- [ ] A15 pytest -m "not live" --deselect (newsradar+s032+s040 flaky) 全绿 + 新增 test_s151_evaluation_layer.py 覆盖 R1-R5
- [ ] A16 cd frontend && npx tsc --noEmit 0 errors + vitest evaluation badge 测试全绿

## 7. 合规与工程底线自查

- [x] 不臆造：DIMENSION_LIFT_REGISTRY 初始值全来自 §44 脚本输出，禁心算
- [x] 私有数据隔离：回溯 DB 写 VR_DATA_DIR（vr_paths.resolve_data_dir）不进 git 不落 home
- [x] em_get 防封：评价层不新增东财端点，turnover/seal 复用已有 activity fetch
- [x] 弱合规：用户可见输出挂轻量风险提醒"历史统计特征,市场有风险"
- [x] §44 已降级参考性建议（S084 reframe），评价层降权不阻塞实现，标注用非门——passed=False 不阻断 run_funnel

## 8. 测试计划

- 单元：DIMENSION_LIFT_REGISTRY 冻结值完整性 + lift_to_multiplier 四态映射 + _apply_evaluation_layer 即时处理（turnover demoted+gene unranked）+ 降权注入 + score 降权 + 回溯 task 阈值
- 集成：run_funnel 返 evaluation_summary + DiagnosisCard.evaluation 注入 + compute_strategy_score multiplier
- 离线：pytest -m "not live" --deselect tests/test_newsradar_global_intel.py --deselect tests/test_s032_refresh_loop.py --deselect "tests/test_s040_backfill.py::test_run_backtest_async_passes_kline_cache"
- 前端：cd frontend && npx tsc --noEmit + vitest（FunnelLayerCard badge + DiagnosisCard §44 label）

## 9. 风险与回滚

- **§F breakout ×0.5 vs ×0.1 待用户拍板**——拍板后调 R1 breakout weight + A3 断言
- 风险：proxy 映射（composite→factor inference）非 direct measurement——标注"indirect"，per-factor §44 验证登记 follow-up
- 风险：DIMENSION_LIFT_REGISTRY 静态冻结值过期（§44 重跑后）——回溯 task 30/60 日更新，未回溯前用冻结值（标 frozen_commit 时间）
- 风险：评价层降权改变漏斗排序——A/B（运行时 multiplier 不改 strategy_weights.json 持久文件）对比
- 回滚：DiagnosisCard.evaluation/FunnelResult.evaluation_summary 默认 None 向后兼容（未接 evaluation 不阻断既有路径）；_apply_evaluation_layer 调用可加 config flag 关
