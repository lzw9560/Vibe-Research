# Tasks — S203 龙头战法数字化改造

> 状态：草案→**部分实施**（2026-09-14 起草；2026-09-16 主 loop 标记进度，见下方）。
> 关联：[[./spec.md]]、[[./plan.md]]、[[../_shared/dragon-score-dimension-registry.md]]。

## 实施状态（2026-09-16）

- ✅ **T0** grep zt_count_250d 7 文件：审计确认 7 文件引用全在（gene_based:91/131/248 + strategy_base:348/380 + funnel/scoring:97/105 + routers/workflow.py:221/250 + scheduler/notifications.py:57）。手动确认 task，basis 有效。
- ✅ **T1** dimension_registry.py：DONE（`06f898a`，Dimension+DIMENSION_REGISTRY+战法ScoreConfig+3 战法 config）。
- ✅ **T2** dragon_score.py：DONE（`06f898a`，composite 0-100）。⚠️ `_normalize` 是骨架待接线（harness 层公式）。
- 🔶 **T3** dragon_head C2/C3 seal gate：**match 逻辑 DONE（first_board_limitup, gene_based.py:455-509 有 C1+C2+C3）**；**msc data-wiring DEFERRED**（aggregation.py:183 msc 只 pattern/sector_rank/rel_strength，缺 zt_count_today + seal_to_float_ratio；涨停 path msc=None 全无）。spec T3 "gene_based.py:393 改 dragon_head" 过时——实际首板战法是 `first_board_limitup`（已建 C2/C3），`dragon_head`（旧龙头战法）只 C1 是设计如此（不同战法）。wiring 剩余：① seal_to_float_ratio 从 pool_item merge 进 msc（易，pool_item 可得）+ ② zt_count_today 从 sector_cycle 进 msc（需 sector 查询集成）+ ③ 涨停 path 也建 msc（limitup_strategy.py:566）。"专门 wiring task"——data-plumbing 非加条件。
- ⏸️ **T4** consecutive_relay C1 lbc≥2：**NOT done**（2026-09-16 核 gene_based.py:91/98：C1 仍 `zt_count_250d>=2` 非 `lbc>=2`）。S203 P3 待实现（T0 grep 7 文件已确认，可改）。
- ✅ **T5** leader_drop_reversal：DONE（`06f898a`，LeaderDropReversalStrategy，大跌从 close 差复算不依赖 pctChg）。
- 🔶 **T6** intraday_loss_breaker：built+green **UNWIRED**（`c5e641e`，stage-1 待 G4 接 router/scheduler）。
- ⏸️ **T7** QMT 4 模板：spec-only 未建（放 specs/S203/templates/ 标 BLOCKER）。
- ✅ **T8** regime-stratified harness ×2（first_board_limitup + reverse_package）：built（`06f898a`），verdict 须等 G1 pctChg+isST 全到位（pctChg DONE，isST DEFERRED）+ S204 verifier（DONE）。
- ✅ **T9** sensitivity_sweep：built（`06f898a`），待 G6 验 overfit 检测。
- ⏸️ **T10** 全量验收：G7，未做。

**关键依赖**：S203 P5 regime harness（T8）的 verdict 现依赖 G1 pctChg（DONE `7e75465`）+ S204 verifier（DONE `fb2cc65`）。isST（T2 S204）DEFERRED 不阻塞 S203 match 逻辑（用 close 价格+em_get 涨停池数据），只阻塞 ST 股一字板 5% 阈值精度。

---

# Cross-spec 全局 phase 序（synth）

> 来自 plan-writing workflow `wpy8b0kef` synth（cross-spec 依赖排序+一致性）。

## 全局 phase 序（推荐）

- G1 全局地基(先行): S204 T1+T2 (R14 pctChg+isST 注入)。baostock cache 5231 股 7 字段无 pctChg 污染 ALL 回测——必须最先。同时启动 S204 T3 (forward_test_records 回补 cron 0 18 * * 0-4)——长任务须早 kick off 积累交易日(完成在 G6)。S203 P3 (consecutive_relay lbc) 须在此阶段先做 zt_count_250d 全 7 文件 grep 确认 blast radius(routers/workflow.py+scheduler/notifications.py 不可漏),确认后改 consecutive_relay.c1 引用不删列
- G2 并行 A — S204 §44v2 verifier 修正(须先改 test RED): S204 T5 (R8 双算+R5 查 ALL 窗口,同步改 test_s44_verifier.py :807/:839/:853/:235/:1086) + 补 R11 task (event_drift.py 新建,edge_type=event 牛市 drift 两样本修正——CRITICAL:当前无 task 须补) + R12 (n<200 guard 折进 T5)。然后 S204 T6 (R10 Bonferroni split_into_subphases+family_grouping.py 新建+K 冻结)。依赖 G1(回测数据可信才能验 verifier 改动)
- G2 并行 B — S203 Track A 战法语义(独立于 S204): S203 P1 (dimension_registry.py+dragon_score.py 纯数据结构+composite,TDD 先 test_dimension_registry+test_dragon_score)。可同时推进 S203 P3 (consecutive_relay C1 lbc≥2,grep 确认后改 gene_based.py:91)。两者无外部依赖
- G3 并行 A — S203 战法卡(依赖 G2-B P1): S203 P2 (dragon_head C2 zt_count_today≥2 + C3 seal_to_float_ratio≥0.005,merge 进 market_scan_ctx 同 sector_rank 模式零 migration) + S203 P4 (leader_drop_reversal 新建:龙头+大跌≥7%+吞没+量≥1.2x,大跌从 close 差复算不依赖 pctChg)。match 逻辑可跑,verdict 须等 G5
- G3 并行 B — S204 多日跟踪架构(依赖 G1 不依赖 G2-A): S204 T9 (tracking_pool_repo+indicator_snapshots 两表,复用 _ensure_tables/:89 幂等) → T10 (early_admission T-1 pit guard) → T11 (escalation_engine 复用 transition CAS:280+ensure_candidate:261,maturity 标探索性) → T12 (R5/R6 decayed→FILTERED 非→CANDIDATE 防振荡,tracking label 不进 enum)
- G4 并行 — S203 风控+模板+S204 sizing(独立): S203 P7 (intraday_loss_breaker enforce 单笔>5%禁加仓/合计>8%禁开新仓,复用 DrawdownBreaker pattern,不依赖 baostock) + S203 P8 (QMT 四模板标 BLOCKER 放 specs/ 不进生产) + S204 T7 (DIM_ARM_MAP arm-sizing 非 gene arm 走 arm_multiplier 替代硬 1.0,依赖 G2-A T5) + S204 T8 (R3 enforce scheduler seed.py 加 enforce key,依赖 T3+T7 非 T9-T12)
- G5 收敛 — S203 §44 harness(须 G2-A S204 verifier+R11 + G1 pctChg 全到位): S203 P5 (regime_stratified_dragon_head/consecutive_relay/leader_drop_reversal/reverse_package_lift ×4,复用 gap_regime_stratified.py:233 compute_regime_labels MA20 3-way + _s44_wire.wire_verdict n_comparisons=4 per family)。K=12 拆 3 family K=4≤8(T6 split)。leader_drop_reversal edge_type=event 须 R11 drift 修正才 verdict 可靠,否则标 provisional。同时 S204 T13 (sensitivity_sweep.py harness,依赖 G2-A T5+T6)
- G6 sweep+验收 — S203 P6 (sensitivity sweep 读 registry SWEEP_PARAMS 调 wire_verdict,overfit 检测 edge 仅单 v=overfit block production,K 含 sweep 次数冻结 pre-registration,依赖 G5 T13+S203 P5)。然后 S204 T4 (underpowered 标注:gene~60天/seal 10天/STI 0天→underpowered 不外推,cancel_rate 标不可得不臆造 0.0,mootdx tick 标 BLOCKER)。须等 T3 backfill 积累≥60 天解除 §44 写回阻塞
- G7 全量验收: S203 P9 (pytest -m 'not live' 全绿含新 test 文件 + §4 验收 gate 逐条核对:metric=day_paired lift net_mean / pass=post-change≥pre-change / regression=lift 掉>10% block / verdict enum robust_edge×1.0+exploratory×0.5+underpowered×0.5+falsified block / sweep gate=edge≥2/4 邻近值)。baostock 依赖 harness test 须确认 S204 T1 pctChg 已修后去 skipif。涉及数据输出跑 ~/tools/financial_rigor.py 验算

## 交接面注意（integration_notes）

- pctChg 交接面(最承重)：baostock cache(7 字段)是回测主路径，baostock_src.py:27 KLINE_FIELDS(含 pctChg+isST)是 fallback 不需注入。S204 T1 优先跑 refresh_kline_cache.py 全量刷新 cache 补原值；回退方案 harness 层 enrich_pctchg(bars)=(close[d]-close[d-1])/close[d-1]*100 可复算非臆造。isST 不默认 '0'——ST 股一字板 5% 阈值(bar_utils.py:63)，不派生则误用 10% 漏判，须从 baostock_src.fetch_stock_basic 派生。决策#12 harness 层注入不动 bar_utils.py 源码(共享 bar 工具被 engine+strategies 共用)。S203 Track A(match 逻辑)用 close 价格+em_get 涨停池数据不依赖 pctChg——只有 P5 harness 依赖，双轨分离成立
- window-sanity 交接面(决策#7 supersede)：verifier-side only 查 ALL 窗口，harness-side 不按胜出窗口调 edge_type(data-snooping)。S203 regime_stratified harness 只传 window_sanity dict 给 verifier，不做 edge_type 后调。verifier.py:258 当前 `edge_window=_WINDOW_FOR_EDGE.get(edge_type)` 单窗口→改查 ALL keys。注意 lift≥1.0(有优势→过 R5 gate 进重方法论)≠ lift≥2.0(robust_edge verdict)，三层不混：R5 gate 过≠robust，robust 仍须 lift≥2+CI 不重叠+days≥60
- R3 enforce 交接面：真实 gap 两处(scheduler/seed.py:265 evaluation_backtest task payload 无 enforce key + evaluation.py:241 DIM_ARM_MAP arm-sizing 空转)。trade_journal.py:399-400 实测是 query_winrate_trends 显示标签('与 lift_to_multiplier 脱节搁置')非 sizing 路径——DO NOT 改 trade_journal(spec §1.2 CRITICAL 修正)。gene 因子级已 DONE(scoring.py:69 gene_multiplier 接 lift_to_multiplier)，T7 扩展 arm 级(非 gene arm 走 arm_multiplier 替代硬 1.0)。evaluation.py:195 lift_to_multiplier 是纯函数(同输入→同输出)可安全复用
- Dragon Score vs scoring.py DRY 交接面(§8 HIGH)：scoring.py 实测 14 个 score_dim 函数(dim1_sector~dim9_event + seal_time/sector_link/market_cap/seal_ratio/turnover)，非 spec 说的'9 维'。Dragon Score 5 维不替代不调 scoring.py——不同抽象层(scoring=候选筛选层按市场档位分层 production-validated S174/S180；Dragon Score=战法级 ranking flat 先验权重标 overfit)。共享的是底层数据模型(limitup_screener/models.py:50 seal_to_float_ratio、sector_cycle.py:165 zt_count_today)非评分逻辑。flat 25/25/20/15/15 标 overfit 风险——sweep 后不调权重(调=过拟合)，R3 enforce 做长期校准。R2 seal 0.5%(评分门槛 top40%)vs limitup_strategy.py:232 5%(硬过滤 top10%)10x 差异合理(不同口径)不冲突
- seal_to_float_ratio 交接面：不给 gene_scores DB 加列(避免 migration+回补 7466 行×46 天)。涨停池 raw(limitup_screener/models.py:50 已算好 ratio)merge 进 market_scan_ctx dict(strategy_base.py:127 已有 sector_rank 同模式)，零 migration。S203 P2 读 msc.seal_to_float_ratio 同 msc.sector_rank 模式
- escalation 交接面(决策#11)：只 candidate→watching 自动晋级，watching 以上人工(半自动化助手定位，A 股 T+1 容错率低 auto-fire holding=自动买入不可当日卖)。复用 workflow_state_repo.py:280 transition CAS(WHERE status=期望态原子抢占)+ :261 ensure_candidate(ON CONFLICT DO NOTHING 幂等)，不改 workflow_state_machine.py:25 _ALLOWED_TRANSITIONS。decay 走 WATCHING→FILTERED reason='decayed'(非→CANDIDATE 防振荡)，tracking_pool.current_status 是 tracking 级 label(admit/tracking/decayed/promoted)不进 WorkflowStatus enum
- Bonferroni K 交接面(决策#9/#10)：selection 只 Bonferroni 不用 BH(verifier.py:299-303 p_bh=None 硬编码保留)；event 只 BH(:364-371 Bonferroni 不参与 event status)。K>8 拆≤8 子 phase 保 Bonferroni 严格(stats.py:33 _MAX_BONFERRONI_K=8 是拆非 cap)。family grouping 去重等价(bollinger==zscore 数学等价等)。S203 K=12 按 regime 拆 3 family 各 K=4，跨 regime 探索性不跨 family Bonferroni-Holm。sweep 次数计入 K(每参数 4-5 值×多维×多战法)，K 冻结 pre-registration(§44v2 rule③ 防后调)
- T3 backfill 是长任务须早启动：forward_test_records 当前 ~20 天(实测)，回补至 ≥60 天是时间积累(不可臆造/加速，须真实交易日)。T3 须在 G1 最早启动 cron(0 18 * * 0-4)开始积累，虽完成最晚(≥60 天≈3 个月)才解除 §44 写回阻塞。不可因'放最后'而晚启动——backfill 是 long-running 须早 kick off

## ordering 理由
S204 数据 blocker 先于 S203 战法实现，原因不是"谁更重要"而是"污染半径"。baostock cache 缺 pctChg(is_unbuyable_next_bar 对一字板判可买)污染的是 ALL 回测 returns——不只 S203 的四个 regime_stratified harness，连已有的 lianban_lift/gap_window_lift/first_board_layer_lift 全受污染(实测 lianban_lift.py:19 KLINE=baostock cache + :68 _is_unbuyable_next_bar)。这意味着: 在 pctChg 修好前,任何 §44 verdict(不论 S203 新建还是 S198/S199 旧 harness 重跑)都不可信。所以 S204 T1/T2 是全局地基,不是"S204 的事"。\n\n§44v2 verifier 修正(R8/R5/R10/R11)次之,因为 S203 P5 harness 调 wire_verdict——verifier 不对,harness 出的 verdict 就不对。具体: R5 单窗口 bug(verifier.py:258 只查 _WINDOW_FOR_EDGE[edge_type] 一窗)会让 selection 型战法的隔夜 gap edge 漏测(§44v1 错窗口灾难重现);R8 双算缺失(verifier.py:343 只给 event/overnight_gap 算 event_metrics)会让 selection 型战法缺 event_metrics;R10 K=12 被 stats.py:349 min(k,8) 压成 K=8 声称 0.05/12 实际 0.05/8(masking overcount)。这三条不修,S203 P5 的 K=12 regime-stratified verdict 是错的。\n\nS203 Track A(P1 registry/dragon_score、P2 dragon_head C2/C3、P3 consecutive_relay lbc、P4 leader_drop_reversal match 逻辑、P7 风控 gate、P8 QMT 模板)可以与 S204 并行推进,因为 match 逻辑读的是 close 价格 + em_get 涨停池数据(sector_rank/seal_to_float_ratio/lbc/zt_count_today),不走 baostock pctChg 路径。leader_drop_reversal 的大跌≥7% 可从 close 差复算不依赖 pctChg 字段。只有 verdict(P5 harness)和 sweep(P6)须等 S204。这个双轨分离经实测验证成立。\n\nS204 多日跟踪架构(T9-T12)独立于 S203,复用 workflow_state_repo CAS 不改 _ALLOWED_TRANSITIONS,可与 S203 Track A 并行。R3 enforce(T8)读 days_robust 从 frozen registry + forward_test_records(T3 backfill),不依赖 escalation 架构——plan Phase 3 rationale 说"依赖 Phase 2 escalation"是过度表述,实测 forward_test_records 已存在(~20 天)T3 独立回补即可。

## consistency issues（4 drafts 间须调和，已在本文件落定时处理）

- CRITICAL — R11 (event drift fix) and R12 (n<200 guard) 有 plan+module+tdd 但无 task。S204-plan Phase 1 明列'R8 + R10 + R11 + R12'，module_split 有 B4(event_drift.py 新建)，tdd_strategy 提 test_event_drift；但 S204-tasks P2 只给 T5(R8+R5)/T6(R10)/T7(R9 arm-sizing)/T8(R3 enforce)，无任何 task 覆盖 R11/R12。同时 S203 P5 硬依赖 S204-R11（leader_drop_reversal edge_type=event，牛市 base_rate=0 drift 假阳性）。修复：R11 必须 or 加 T5b（event_drift.py 新建，被 verifier._compute_event_metrics 调，event null mean>0→两样本/减市场均值）；R12 可折进 T5（n<200 pre-check 标 underpowered）。实测 s44_verifier/ 无 event_drift.py（只有 stats/verifier/wiring/haircut/ic_ir/overfit/pbo/recorder），须新建
- HIGH — S203-tasks 是占位 stub。提供的 S203-tasks JSON 实际是 {"spec":"test","phases":[{"phase":"P0","tasks":[{"acceptance":"test",...}]}]}，无可执行 checklist。S203-plan 有完整 dependency_order(P1-P9)+tdd_strategy+module_split，但 tasks 须从这些 drafting 出来：T_dragon_score(P1 registry+composite)/T_dragon_head_seal_gate(P2 C2+C3)/T_consecutive_relay_lbc(P3,须 grep 全 7 文件先)/T_leader_drop_reversal(P4)/T_intraday_loss_breaker(P7)/T_qmt_templates(P8)/T_regime_stratified_harness(P5 等 S204)/T_sweep(P6 等 S204)。当前两 spec 交付不对称：S204-tasks 完整 13 task，S203-tasks 空白
- MEDIUM — R3 enforce 依赖表述矛盾。S204-plan Phase 3 rationale 写'Phase 2（escalation 产出 forward_test_records 喂 R3）'，暗示 R3 enforce 依赖多日跟踪架构(Phase 2)。但 S204-tasks 把 T8(R3 enforce) 放 P2、在 T9-T12(跟踪架构 P3) 之前。实测 forward_test_records 已存在(~20 天)，T3(backfill) 独立回补不依赖 escalation。所以 tasks 排序(T8 先于 T9-T12)实际更对——T8 依赖 T3(backfill)+T7(arm-sizing) 非 T9-T12。须修正 plan Phase 3 rationale 去掉'依赖 Phase 2 escalation'，改为'依赖 T3 backfill'
- MEDIUM — underpowered 标注 phase 位置不一致。S204-plan 把 R15/R16/R17 放 Phase 5(最后，依赖全)。S204-tasks 把 T4(underpowered labeling) 放 P1(最早，依赖 T1+T3)。两者不矛盾而是不同标注对象：T4 静态标注数据源(gene_scores~60 天/seal 10 天/STI 0 天→underpowered 标签，可早做)；plan Phase 5 动态标注 verdict(跑完 verdict 后标 provisional ×0.5)。两套都需要但 phase 归属须在 plan 里区分清楚——T4=数据源诚实标注(early)，Phase 5=verdict 降权(late)
- MEDIUM — lift≥1.0 vs lift≥2.0 语义混用。S204-tasks T5 acceptance 写'任一窗口 lift≥1.0→非 exploratory'；但 §44 robust_edge verdict 须 lift≥2+CI 不重叠+days≥60。draft 多处把'proceed 过 R5 gate'与'robust verdict'混为一谈。须厘清三层：(1)R5 gate 任一窗口 lift≥1.0=有优势→过 gate 进重方法论(非 exploratory)；(2)exploratory verdict=1≤lift<2 或 days<60→ship ×0.5 provisional；(3)robust_edge=lift≥2+CI 不重叠+robust+days≥60→ship ×1.0。S203-plan §4 HIGH-3 已正确列这 enum，但 S204-tasks T5 描述须对齐不混用
- LOW — zt_count_250d blast radius 低估。S203-plan 写'5 处引用(gene_based.py×3 + funnel/scoring.py + strategy_base.py)'。实测 grep 显示 7 文件：gene_based.py:91/131/248(3 函数)、strategy_base.py:348/380、funnel/scoring.py:97/105、routers/workflow.py:221/250、scheduler/notifications.py:57。draft 漏了 routers/workflow.py + scheduler/notifications.py。P3 plan 正确说'不删列只改 consecutive_relay 的 C1 引用'所以影响可控，但'grep 先确认'范围须覆盖全 7 文件非 3，尤其 workflow.py:250 getattr 回退读 zt_count_250d
- LOW — 路径前缀错误。S203-plan'已核实 file:line'写 backend/first_board/scoring.py，实测是 backend/strategies/first_board/scoring.py(多 strategies/ 前缀)。sector_divergence.py draft 说'backend/ 非 routers/'——实测两处都有(./sector_divergence.py 根 + ./routers/sector_divergence.py)，draft 指根的，正确。路径错误只影响 grep 定位不影响逻辑，但'已核实'栏须路径精确

---

## Tasks（TDD checklist）


### P0 blast radius 前置

- [ ] **T0**: grep zt_count_250d 全 7 文件引用确认（L1 修正：非 5 处是 7 文件）
   - 依赖: 无
   - 验收:
1. test_grep_covers_7_files — grep 覆盖 gene_based.py:91/131/248 + strategy_base.py:348/380 + funnel/scoring.py:97/105 + **routers/workflow.py:221/250**（getattr 回退）+ **scheduler/notifications.py:57**（draft 原漏这两处）
2. 确认 break_reseal/rebound 战法仍读 zt_count_250d 作门槛（不改这些，只改 consecutive_relay C1）
   - test: 人工 grep 确认记录

### P1 数据结构 + composite（独立 S204，G2-B 并行）

- [ ] **T1**: dimension_registry.py — Dimension + DIMENSION_REGISTRY + 战法ScoreConfig + S203 3战法 config
   - 依赖: 无
   - 骨架:
```python
@dataclass(frozen=True)
class Dimension:
    name: str; data_source: str; normalization: str
    sweep_range: tuple[float, ...]; overfit_risk: str
    applicable_战法: tuple[str, ...] | None; notes: str

@dataclass(frozen=True)
class 战法ScoreConfig:
    战法: str; dimensions: tuple[str, ...]
    weights: dict[str, float]  # sum=1.0
    edge_type: str  # 标"待验"（决策#7 verifier-side，window sanity 后定不预设）
    sweep_params: dict[str, list]; cost_model: str

DIMENSION_REGISTRY: dict[str, Dimension] = {...}  # 5 共享维度
STRATEGY_CONFIGS: dict[str, 战法ScoreConfig] = {
    "龙头首板": ..., "接力": ..., "反包": ...,
}
```
   - 验收:
1. test_dimension_frozen — Dimension frozen dataclass，setattr 报 FrozenInstanceError
2. test_weights_sum_one — 每战法 config weights sum=1.0
3. test_edge_type_marked_unverified — edge_type 含"待验"标注（决策#7 verifier-side，不预设）
4. test_applicable_战法_nonempty — 每维度 applicable 列表非空
5. test_dry_vs_scoring — Dimension 与 scoring.py score_dim* 不同层（共享数据源 seal_to_float_ratio/zt_count_today 不共享逻辑），guard：不 import scoring.py
   - test: tests/test_dimension_registry.py

- [ ] **T2**: dragon_score.py — composite 0-100 计算（非 ML，对齐 weight-as-ml-feature-is-inert）
   - 依赖: T1
   - 骨架:
```python
def dragon_score(config: 战法ScoreConfig, code: str, trade_date: str, indicators: dict) -> float:
    score = 0.0
    for dim_name, weight in config.weights.items():
        dim = DIMENSION_REGISTRY[dim_name]
        raw = _read_indicator(indicators, dim.data_source, code, trade_date)
        normalized = _normalize(raw, dim.normalization)  # → [0,1]
        score += normalized * weight
    return score * 100  # → 0-100
```
   - 验收:
1. test_composite_range — dragon_score 返回 [0, 100]
2. test_missing_dim_normalized_zero — 缺失维度 normalized=0 不报错，贡献=0
3. test_weight_missing_contribution_zero — 权重缺失维度贡献=0
4. test_non_ml_guard — 分数不喂回 gene_score/scoring.py 参与排序（guard：dragon_score 不被 gene_score import）
5. test_pure_function — 同输入→同输出（无副作用）
   - test: tests/test_dragon_score.py

### P2 首板 dragon_head 补 C2/C3（G3-A，依赖 T1）

- [ ] **T3**: dragon_head C2 板块共振 + C3 封单门槛（gene_based.py:393 改，seal merge 进 market_scan_ctx 零 migration）
   - 依赖: T1
   - 骨架:
```python
# gene_based.py:393 dragon_head match 加：
# C1 保留 sector_rank≤3
# C2 新增: msc.zt_count_today >= 2  (sector_cycle.py:165, 探索性门槛须 sweep)
# C3 新增: msc.seal_to_float_ratio >= 0.005  (涨停池 raw merge 进 market_scan_ctx, 同 sector_rank 模式)
# strategy_base.py:127 market_scan_ctx 加 seal_to_float_ratio 键（从涨停池 raw limitup_screener/models.py:50 取，零 migration）
```
   - 验收:
1. test_c1_sector_rank_retained — C1 sector_rank≤3 保留不删
2. test_c2_zt_count_today — C2 zt_count_today≥2 命中（板块共振）
3. test_c3_seal_gate — C3 seal_to_float_ratio≥0.005 命中
4. test_no_market_scan_ctx_degrades — 无 market_scan_ctx → data_ok=False 整战法降级（非 crash）
5. test_seal_none_field_level — seal_to_float_ratio=None → 字段级 data_unavailable 非 block 整战法
6. test_seal_merge_zero_migration — seal_to_float_ratio 从涨停池 raw merge 进 msc，gene_scores DB 不加列
7. test_seal_05_vs_5pct口径 — 0.5% 评分门槛（top40% 品质封单）vs limitup_strategy.py:232 5% 硬过滤（top10%），10x 差异合理（不同口径）
   - test: tests/test_dragon_head_seal_gate.py

### P3 接力 consecutive_relay C1 改 lbc≥2（G1/G2-B，T0 grep 先）

- [ ] **T4**: consecutive_relay C1 从 zt_count_250d≥2 改 lbc≥2
   - 依赖: T0（grep 7 文件确认 blast radius 先）
   - 骨架:
```python
# gene_based.py:91 consecutive_relay C1 改：
#   旧: zt_count_250d >= 2  →  新: lbc >= 2  (当下连板≥2, from 涨停池 ths_lb_cache)
# zt_count_250d 降为 C2 辅助加分（不删列，break_reseal/rebound 仍读）
```
   - 验收:
1. test_c1_lbc_replaces_zt_count — C1 lbc≥2 替代 zt_count_250d≥2
2. test_lbc_1_not_match — lbc=1 不命中（非二板）
3. test_zt_count_250d_demoted_c2 — zt_count_250d 降为 C2 加分不做门槛
4. test_other_战法_unaffected — break_reseal/rebound 仍读 zt_count_250d 不受影响（blast radius R5）
5. test_grep_7_files_confirmed — T0 grep 确认 7 文件引用后改（含 workflow.py:250 getattr 回退）
   - test: tests/test_consecutive_relay_lbc.py

### P4 反包 leader_drop_reversal 新建（G3-A，依赖 T1）

- [ ] **T5**: leader_drop_reversal 新建战法卡（不改 reverse_package，大跌从 close 差复算不依赖 pctChg）
   - 依赖: T1
   - 骨架:
```python
@dataclass(frozen=True)
class LeaderDropReversalMatch:
    code: str; trade_date: str; drop_pct: float; is_engulf: bool; vol_ratio: float

def match(code, trade_date, bars, gene_scores) -> LeaderDropReversalMatch | None:
    # 核心龙头: sector_rank≤3 or gene_scores.high_gene=1
    # T-N 日大跌: (close[T-N] - close[T-N-1]) / close[T-N-1] <= -0.07  (从 close 差复算, 不依赖 pctChg)
    # T 日吞没: close[T] >= open[T-N] 且 open[T] <= close[T-N]  (吞没前日阴线)
    # 放量: volume[T] / volume[T-N] >= 1.2
    # MA 位置: close[T] 在 MA5/MA10 附近
```
   - 验收:
1. test_drop_7pct — 大跌≥7% 检测（从 close 差复算，不依赖 pctChg 字段）
2. test_engulf — 吞没 close≥前日 open 且 open≤前日 close
3. test_vol_1_2x — volume_breakout≥1.2x
4. test_leader_confirm — 龙头确认 sector_rank≤3 or high_gene
5. test_non_leader_drop_no_match — 非龙头大跌不命中
6. test_reverse_package_unchanged — reverse_package 战法不受影响（R7 保留，有 629 笔回测验证）
7. test_event_drift_provisional — edge_type=event，verdict 须等 S204 R11（T5b）drift 修正才可靠，否则标 provisional
   - test: tests/test_leader_drop_reversal.py

### P7 风控 gate（G4，独立 S204）

- [ ] **T6**: intraday_loss_breaker enforce（单笔>5% 禁加仓/合计>8% 禁开新仓+冷却，复用 DrawdownBreaker pattern）
   - 依赖: 无（不依赖 baostock/S204，基于持仓浮亏）
   - 骨架:
```python
@dataclass(frozen=True)
class LossBreakerState:
    code: str; date: str; realized_loss_pct: float; is_blocked_add: bool; is_blocked_new: bool

def check_eligibility(code, intraday_breaker, drawdown_breaker) -> bool:
    # 四层乘积: final_size = arm_size × portfolio_mult × lift_mult × intraday_mult
    # 单笔浮亏>5% → should_block_add=True（该 code 当日禁加仓）
    # 合计>8% → should_block_new=True（全账户禁开新仓+冷却）
    # 复用 DrawdownBreaker pattern (engine/drawdown_breaker.py:77 enforced/disabled)
```
   - 验收:
1. test_single_loss_5pct_block_add — 单笔浮亏>5% → should_block_add=True
2. test_single_loss_below_5pct — 单笔浮亏<5% → False
3. test_total_8pct_block_new — 合计>8% → should_block_new=True
4. test_cooldown_enforce — 冷却期内 enforce（不重置）
5. test_four_layer_product — final_size = arm × portfolio × lift × intraday 计算
6. test_risk_rules_upgrade_enforce — risk_rules.py 从诊断（report）升级 enforce（block+cooldown），不破坏现有 report API
   - test: tests/test_intraday_loss_breaker.py

### P8 QMT 参考模板（G4，独立）

- [ ] **T7**: QMT 4 模板（specs/S203/templates/，标 BLOCKER 不进生产）
   - 依赖: 无
   - 骨架:
```python
# specs/S203/templates/board_hit_trigger.py — 价格触涨停+封成比>阈值→排队买入（BLOCKER: 需 xtquant+L2）
# specs/S203/templates/vwap_stop.py — 实时 VWAP+跌破→卖出（BLOCKER: 需 mootdx tick 实时）
# specs/S203/templates/seal_ratio_monitor.py — 轮询 em_zt_topic_pool 取 seal_amount+amount 算封成比<5%→预警（Vibe 侧可做）
# specs/S203/templates/big_loss_breaker.py — 单笔>5%/合计>8% enforce（Vibe 侧可做, 复用 T6）
```
   - 验收:
1. test_templates_in_specs — 4 模板在 specs/S203/templates/ 不进 backend/
2. test_blocker_marked — board_hit_trigger/vwap_stop 标 BLOCKER（Vibe 无 xtquant/mootdx tick 实时）
3. test_seal_ratio_vibe_side — seal_ratio_monitor 可 Vibe 侧跑（em_get 涨停池有 seal_amount+amount）
4. test_big_loss_reuses_t6 — big_loss_breaker 复用 T6 intraday_loss_breaker
   - test: tests/test_qmt_templates.py

### P5 regime-stratified §44 harness ×4（G5 收敛，等 S204）

- [ ] **T8**: regime_stratified_dragon_head/consecutive_relay/leader_drop_reversal/reverse_package_lift ×4
   - 依赖: T3, T4, T5, **S204 R14(pctChg)+R8(verifier双算)+R10(Bonferroni拆≤8)+R11(event_drift)**
   - 骨架:
```python
# 复用 gap_regime_stratified.py:233 compute_regime_labels (MA20 3-way: bull/bear/range)
# 4 战法各一 harness: regime_stratified_<战法>_lift.py (~300 行)
# picks 按 D 日 regime 分层 → day_paired_lift → wire_verdict(n_comparisons=4 per family)
# K=12 (3 regime×4 战法) 按 regime 拆 3 family 各 K=4≤8 (决策#9, S204 T6 split)
# leader_drop_reversal edge_type=event 须 R11 (S204 T5b) drift 修正才 verdict 可靠
```
   - 验收:
1. test_ma20_3way_regime_labels — MA20 3-way regime 分层正确（bull/bear/range）
2. test_k4_per_family_bonferroni — K=4 per family Bonferroni（非 K=12 cap 到 8）
3. test_wire_verdict_n4 — wire_verdict n_comparisons=4 per family
4. test_cross_regime_exploratory — 跨 regime 标探索性（不跨 family Bonferroni-Holm）
5. test_small_n_regime_underpowered — 小 n regime 标 underpowered 不外推
6. test_leader_drop_event_drift_provisional — leader_drop_reversal verdict 须 R11 修正，否则 provisional
7. test_pctchg_dependency — baostock 依赖 harness test 标 skipif S204 R14 未落地（或 mock pctChg）
   - test: tests/test_regime_stratified_dragon_lift.py

### P6 sensitivity sweep（G6，等 S204 R13）

- [ ] **T9**: sensitivity sweep 读 registry SWEEP_PARAMS（overfit 检测，K 含 sweep 次数冻结）
   - 依赖: T8, **S204 R13(sweep harness)**
   - 骨架:
```python
# 调 S204 tools/sensitivity_sweep.py sweep_param(战法_config, param, values)
# 从 registry §5 SWEEP_PARAMS 取: seal_to_float_ratio[0.3/0.5/0.7/1.0], relay_vol_ratio[1.0/1.5/2.0/2.5/3.0], sector_top_n[1/3/5/10]
# overfit: edge 仅单 v 且邻近无 → overfit block production; 多邻近 → 稳健; 无 v → 无 edge 不外推
# K 含 sweep 次数冻结 pre-registration (§44v2 rule③)
```
   - 验收:
1. test_sweep_3_params — 三参数都扫（决策#2：封单+量能+板块）
2. test_overfit_single_value — edge 仅单 v → overfit_flag=True block production
3. test_robust_multi_value — edge 多邻近 v → robust_flag=True
4. test_no_edge_no_extrapolate — 无 v 出 edge → 标 no_selection_edge 不进融合
5. test_sweep_k_includes_count — K 含 sweep 次数冻结 pre-registration
6. test_weights_not_tuned_after_sweep — sweep 后不调权重（调=过拟合，R10 overfit risk）
   - test: tests/test_sensitivity_sweep.py（或复用 S204 test_sensitivity_sweep.py）

### P9 全量验收（G7）

- [ ] **T10**: 全量 pytest + §4 验收 gate 逐条核对
   - 依赖: T1-T7（Track A），T8/T9 等 S204
   - 验收:
1. test_pytest_not_live_green — `pytest -m "not live"` 全绿（含新 test 文件）
2. test_§4_metric — metric=day_paired lift net_mean
3. test_§4_pass_threshold — pass=post-change lift ≥ pre-change OR net_mean>0
4. test_§4_regression — regression=lift 掉>10% block
5. test_§4_verdict_enum — verdict enum: robust_edge×1.0 + exploratory×0.5 + underpowered×0.5 + falsified block
6. test_§4_sweep_gate — sweep gate: edge≥2/4 邻近值 pass，单点 overfit block
7. test_baostock_harness_skipif — baostock 依赖 harness test 确认 S204 T1 pctChg 已修后去 skipif
8. test_financial_rigor — 涉及数据输出跑 ~/tools/financial_rigor.py 验算
   - test: 全量 pytest
