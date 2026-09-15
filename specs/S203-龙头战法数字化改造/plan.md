# Plan — S203 龙头战法数字化改造

> 状态：草案（2026-09-14，plan-writing workflow `wpy8b0kef` 起草 + 主 loop 调和）。SDD §0：spec 定稿→**plan 怎么做**→tasks 可执行 checklist。
> 关联 spec：[[./spec.md]]、[[../_shared/dragon-score-dimension-registry.md]]。

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

## 1. 实现步骤 + 依赖序

1. **P1 dimension_registry.py + dragon_score.py（新建：Dimension dataclass + DIMENSION_REGISTRY + 战法ScoreConfig + S203 三战法 config + dragon_score() composite 函数）** （无依赖）
   - rationale: 纯数据结构+composite 计算函数，无外部依赖。registry 定义 Dimension/战法ScoreConfig/STRATEGY_CONFIGS（龙头 3 sub 配置），dragon_score 读 registry 归一化加权。TDD 先写 test_dimension_registry.py + test_dragon_score.py。可独立于 S204 推进

2. **P2 首板 dragon_head 补 C2/C3（gene_based.py:393 加板块共振 zt_count_today≥2 + 封单 seal_to_float_ratio≥0.5%）** （依赖: P1）
   - rationale: 需要先做 zt_count_250d blast radius grep（R5）。seal_to_float_ratio 从涨停池 raw（limitup_screener/models.py:50）merge 进 market_scan_ctx dict（strategy_base.py:127 已有 sector_rank 同模式），不给 gene_scores DB 加列（避免 migration+回补 7466 行）。C2 用 sector_cycle.py:165 zt_count_today≥2，C3 用 seal_to_float_ratio≥0.005。不删 sector_rank≤3（C1 保留）

3. **P3 接力 consecutive_relay C1 改 lbc≥2（grep zt_count_250d 全引用确认 blast radius → gene_based.py:85 改 zt_count_250d≥2 为 lbc≥2）** （无依赖）
   - rationale: blast radius grep 先行（R5）。lbc 字段从涨停池 ths_lb_cache 取（lianban_lift.py 已用 parse_boards）。zt_count_250d 降为 C2 辅助不做门槛——不删 zt_count_250d 列（break_reseal/rebound 战法仍读），只改 consecutive_relay 的 C1 引用

4. **P4 反包 leader_drop_reversal 新建战法卡（strategies/impl/leader_drop_reversal.py：核心龙头+T-N 大跌≥7%+吞没+量≥1.2x）** （依赖: P1）
   - rationale: 新建不改 reverse_package（R7：reverse_package 有 629 笔回测+357 笔实盘验证，保留）。leader_drop_reversal 读 baostock K线（大跌≥7%+吞没+放量）+ gene_scores.high_gene（龙头确认）。edge_type=event 须 S204 R11 drift 修正才可靠 verdict——P5 harness 依赖

5. **P5 regime_stratified §44 harness ×4（S204 blocker：须 R14 pctChg + R8 verifier 双算 + R10 Bonferroni + R11 event drift 修正）** （依赖: P2, P3, P4, S204-R14, S204-R8, S204-R10, S204-R11）
   - rationale: 必须等 S204：R14 pctChg 净化 baostock returns（否则 lianban_lift/gap_regime_stratified 等 ALL baostock 依赖 harness 被污染）；R8 verifier 双算 selection_lift AND event_metrics（leader_drop_reversal edge_type=event 须 event_metrics）；R10 Bonferroni K-split（K=12→3 family×K=4≤8）；R11 event drift 修正（base_rate=0 牛市假阳性）。复用 gap_regime_stratified.py MA20 3-way pattern + _s44_wire.wire_verdict

6. **P6 sensitivity sweep（S204 blocker：须 S204 R13 sweep harness 先建）** （依赖: S204-R13）
   - rationale: sweep harness 不存在（S204 R13 新建）。sweep 本身是多重检验——K 须含 sweep 次数（决策#9 拆≤8 + #10 family 去重等价），K 冻结 pre-registration。须在 P5 verdict 出后跑——先确认 edge 在哪个窗口再 sweep

7. **P7 风控 gate Vibe 侧（intraday_loss_breaker enforce + bidding 封成比预警 + risk_rules 诊断→enforce 升级）** （无依赖）
   - rationale: 风控 gate 不依赖 S204——Vibe 侧 em_get 涨停池有 seal_amount+amount（封成比），吃大面基于持仓浮亏（不依赖 baostock）。intraday_loss_breaker 复用 DrawdownBreaker pattern（engine/drawdown_breaker.py:77 status enforced/disabled），从 risk_rules.py 诊断升级 enforce。QMT 模板标 BLOCKER 不进生产

8. **P8 QMT 参考模板（specs/S203/templates/ board_hit_trigger/vwap_stop/seal_ratio_monitor/big_loss_breaker，标 BLOCKER 不进生产）** （无依赖）
   - rationale: 不进 backend 生产代码，纯参考。标 BLOCKER 因 Vibe 无 xtquant/QMT 集成无下单路由，打板秒级竞争 Vibe 60s 轮询→延迟不可用

9. **P9 全量 pytest -m 'not live' 绿（含新 test 文件）+ §4 验收 gate 核对** （依赖: P1, P2, P3, P4, P7）
   - rationale: Track A 全部落地后跑离线测试。P5/P6 等 S204 后再跑——不影响 Track A 验收。须检查 lianban_lift/first_board_layer_lift/gap_window_lift 等 baostock 依赖 harness 是否同步改（pctChg 污染影响，但修复在 S204 R14 不在 S203）


## 2. 模块拆分（高内聚低耦合，200-400 行/模块）

| 模块 | 职责 | key files | notes |
|---|---|---|---|
| dimension_registry | 声明式维度定义+战法配置。Dimension frozen dataclass + DIMENSION_REGISTRY（5 共享维度）+ 战法ScoreConfig frozen dataclass + STRATEGY_CONFIGS（龙头首板/接力/反包 3 config） | backend/strategies/dimension_registry.py（新建 ~250 行） | DRY §8 HIGH：Dimension 与 scoring.py 的 score_dim* 函数不同层——scoring.py 是候选筛选层（按市场档位分层），Dimension 是战法级 ranking 层（flat 归一化）。共享数据源（seal_to_float_ratio/zt_count_today）不共享逻辑。flat weights 25/25/20/15/15 标 overfit 风险——sweep 后不调权重（调=过拟合） |
| dragon_score | composite 0-100 分计算。读 registry Dimension.data_source 取原始值→归一化→加权求和。纯函数无副作用 | backend/strategies/dragon_score.py（新建 ~150 行） | R12 非喂 ML 特征（对齐 weight-as-ml-feature-is-inert）。分数是选股排序依据。guard：若分数喂回 gene_score 或 scoring.py 参与排序→检查间接进 ML（验证器 HIGH） |
| dragon_head_mod | 首板加 C2 板块共振（sector_cycle.py:165 zt_count_today≥2）+ C3 封单门槛（seal_to_float_ratio≥0.005）。接力 C1 从 zt_count_250d≥2 改 lbc≥2 | backend/strategies/impl/gene_based.py:393-430（dragon_head 改）/backend/strategies/impl/gene_based.py:85-105（consecutive_relay 改） | R2 seal 0.5% vs limitup_strategy.py:232 5%：不同口径——5% 是硬过滤（强封单稀有 top10%），0.5% 是评分门槛（品质封单 top40%），10x 差异合理。seal_to_float_ratio 从涨停池 raw merge 进 market_scan_ctx（strategy_base.py:127 已有 sector_rank 同模式），不给 gene_scores DB 加列 |
| leader_drop_reversal | 反包战法新卡。核心龙头（sector_rank≤3 or high_gene）+ T-N 大跌≥7% + T 日吞没+放量≥1.2x + MA5/10 位置 | backend/strategies/impl/leader_drop_reversal.py（新建 ~200 行） | R9 event drift §8 HIGH：edge_type=event 须 S204 R11 drift 修正（verifier.py:362 event 用 BH，base_rate=0 牛市假阳性）。S203 先建 match 逻辑，verdict 等 S204 R11 后才可靠。大涨跌阈值≥7% 标探索性须 sweep |
| regime_stratified_harness | 4 战法 × MA20 3-way regime 分层 §44 verdict。复用 gap_regime_stratified.py pattern + _s44_wire.wire_verdict | backend/tools/regime_stratified_dragon_head_lift.py（新建 ~300 行）, regime_stratified_consecutive_relay_lift.py（新建 ~300 行）, regime_stratified_leader_drop_reversal_lift.py（新建 ~350 行）, regime_stratified_reverse_package_lift.py（新建 ~300 行） | R20 K-split §8 HIGH：K=12→3 family 各 K=4≤8（决策#9 不用 BH，selection 只 Bonferroni，s44_verifier/verifier.py:299-303）。每 regime family 独立 FWER，跨 regime 探索性（决策#10 family grouping 去重等价）。gap_regime_stratified.py K=3 先例（:471 n_comparisons=3） |
| intraday_loss_breaker | 吃大面 enforce。单笔浮亏>5%→code 当日禁加仓；合计>8%→全账户禁开新仓+冷却 | backend/risk/intraday_loss_breaker.py（新建 ~200 行） | R17 零件齐（risk_rules.py+at_risk.py+drawdown_breaker.py）须从诊断升级 enforce。吃大面不依赖 baostock/S204——基于持仓浮亏。单笔>5% 禁加仓、合计>8% 禁开新仓+冷却 |
| bidding_seal_ratio | 封成比预警 seal_amount/turnover<5% 黄色预警。撤单率标降级口径不臆造 | backend/routers/bidding.py（改 ~30 行新增）/backend/bidding_monitor.py:103,133（标降级口径） | R14 封成比 Vibe 侧可做（em_get 涨停池有 seal_amount+amount）。R15 撤单率标降级口径（bidding_monitor.py:103/133 cancel_rate=0.0 硬编码，腾讯行情不含撤单率），不臆造。L2 付费须用户决策 |
| risk_rules_enforce | risk_rules.py 从诊断（report violations）升级 enforce（block new positions + cooldown） | backend/risk_rules.py:181-465（改 enforce 分支）/backend/at_risk.py（改 enforce 分支） | risk_rules.py discipline/violations 当前返 report（诊断），须加 enforce action（block+cooldown）。不破坏现有 report API——新增 enforce 路径并行 |
| qmt_templates | QMT 侧参考模板。board_hit_trigger/vwap_stop/seal_ratio_monitor/big_loss_breaker 四模板，标 BLOCKER 不进生产 | specs/S203/templates/board_hit_trigger.py（新建）, specs/S203/templates/vwap_stop.py（新建）, specs/S203/templates/seal_ratio_monitor.py（新建）, specs/S203/templates/big_loss_breaker.py（新建） | R19 标 BLOCKER 放 specs/ 不进 backend 生产。Vibe 是研究看板无 xtquant/QMT 集成，打板秒级竞争 60s 轮询延迟不可用 |
| tests | TDD 测试覆盖 80%+。先写 test 再实现（RED→GREEN→REFACTOR） | backend/tests/test_dimension_registry.py（新建）, backend/tests/test_dragon_score.py（新建）, backend/tests/test_dragon_head_seal_gate.py（新建）, backend/tests/test_consecutive_relay_lbc.py（新建）, backend/tests/test_leader_drop_reversal.py（新建）, backend/tests/test_intraday_loss_breaker.py（新建）, backend/tests/test_regime_stratified_dragon_lift.py（新建，等 S204） | §3 test files §8 HIGH：lianban_lift/first_board_layer_lift/gap_window_lift 等 baostock 依赖 harness 须等 S204 R14 pctChg 修复后才可靠——S203 不改这些 harness（改在 S204 R14），但 test 须标注 pctChg 依赖 |

## 3. 数据流

涨停池 raw（em_get 限流防封，limitup_screener/models.py:48-50 算 seal_to_float_ratio）→ market_scan_ctx dict（strategy_base.py:127，新增 seal_to_float_ratio 键，同 sector_rank 模式）→ 战法 match（gene_based.py:393 dragon_head 读 msc.sector_rank + 新增 msc.seal_to_float_ratio；consecutive_relay 读 lbc from ths_lb_cache；leader_drop_reversal 读 baostock K线 + gene_scores.high_gene）→ 命中 candidates → Dragon Score composite（dragon_score.py 读 dimension_registry.py DIMENSION_REGISTRY 归一化+加权 → 0-100 分，各维度读 sector_cycle.py/limitup_screener/pattern_scan/limitup_sti/baostock）→ 排序 gene_scores 合格池 → 风控 gate（intraday_loss_breaker + drawdown_breaker 四层乘积 final_size）→ 信号输出（Vibe 侧 generate_board_signal）→ §44 regime-stratified harness（regime_stratified_*_lift.py 按 MA20 3-way 分层 picks → day_paired_lift → wire_verdict → verdict status）→ lift_to_multiplier（evaluation.py:195 days<60 → ×0.5 provisional）→ 回写 lift_override → 下次 match 时 scoring.py:69 读 effective multiplier 降权。QMT 侧：信号+模板 specs/S203/templates/ 标 BLOCKER 不进生产。

## 4. 备选方案 + 为何不选

- **Dragon Score 替代 first_board/scoring.py 14 维系统（统一一套评分）** → 不选：scoring.py 是 production-validated 候选筛选层（S174/S180），按市场档位分层更精细；Dragon Score 是战法级 ranking composite。两者不同抽象层+不同归一化哲学。替代须弃档位分层改 flat——无证据 flat 更优，且爆炸半径大（14 个 score_dim 函数+pipeline 依赖）。KISS：叠加不替代，共享数据源不共享逻辑
- **leader_drop_reversal 改 edge_type=selection（day_paired 天然对冲 drift）** → 不选：反包本质是事件触发（龙头大跌后反包日），selection 口径（survivor vs universe per-day）会混淆反包事件的因果路径。但 drift 确实是 risk——折中：保留 event 口径+S204 R11 universe_by_day 两样本修正 drift，不逃避到 selection。verifier.py:362 event 用 BH 只需加 universe baseline 减市场均值
- **Dragon Score 用 flat 权重 25/25/20/15/15 硬编码进战法卡** → 不选：round-number flat 权重标 overfit 风险（§8 DRY lens HIGH）。用声明式 registry 让权重是 declared data 非 hardcoded logic——加新战法加 config entry 不改 framework。但 weights 值本身仍是先验 round numbers，须 sweep 后不调权重（调权重=过拟合）。标 overfit 不替代
- **seal_to_float_ratio 给 gene_scores DB 加列+回补（方案 a）** → 不选：gene_scores DB 表实测无此列（columns: date/code/name/total_score/factor_*/wilson_adjusted/qualify/high_gene/zt_count_250d），加列须 migration+回补 7466 行×46 天历史——工程成本高。方案 b 更简：涨停池 raw models.py:221 已算好 ratio，merge 进 market_scan_ctx dict（strategy_base.py:127 已有 sector_rank 同模式），零 migration
- **接力 C1 直接改 zt_count_250d→lbc 不做 blast radius grep（R5 跳过）** → 不选：zt_count_250d 被 5 处引用（gene_based.py×3 + funnel/scoring.py + strategy_base.py），直接改可能破坏 break_reseal/rebound 战法（也读 zt_count_250d）。C1 改 lbc 是 consecutive_relay 专属，但须确认其他战法不依赖 zt_count_250d>=2 作门槛。grep 先确认是安全底线
- **QMT 模板接入 backend 生产代码（Vibe 侧直连 xtquant）** → 不选：Vibe 是研究看板（60s 轮询），无 QMT/xtquant 集成无下单路由。打板秒级竞争 60s 延迟=不可用。接入须独立搭执行层=大型重构偏离定位。标 BLOCKER 放 specs/S203/templates/ 是正确边界——参考模板给用户独立搭建执行层用
- **情绪周期用 STI 5-phase 硬分三态（退潮×0.5/高潮×1.0/启动×1.2）** → 不选：实测 sti_timeline 33 日期，phase 分布冰点15/分歧12/启动6/退潮=0/高潮=0——硬分三态在退潮/高潮零数据。MVP 用连续 STI score/100 标探索性 regime 标注，积累 60+ 天后验证三态预测力（ANOVA/Kruskal-Wallis 三态间 path return 均值差异），无 edge 不加分
- **Bonferroni K=12 全局校正（3 regime×4 战法一起算）** → 不选：K=12 Bonferroni α_adj=0.00417 over-correct（决策#9 拆≤8）。按 regime 拆 3 family 各 K=4（α_adj=0.0125）更合理——每 family 独立 FWER，跨 regime 探索性。S198 precedent gap_regime_stratified K=3 先例也是 per-regime 独立

## 5. TDD 策略

TDD 严格执行 RED→GREEN→REFACTOR，80% 覆盖。先写 test 再实现，每完成一条 tasks 勾一条。

Phase 1（registry+composite，独立 S204）先写：
  test_dimension_registry.py — (1) Dimension frozen 不变性（@dataclass(frozen=True) setattr 报错）（2）weights sum=1.0（3）edge_type 必须含"待验"标注（4）applicable 战法非空
  test_dragon_score.py — (1) composite 返回 [0,100]（2）缺失维度 normalized=0 不报错（3）权重缺失维度贡献=0（4）非ML特征 guard：分数不喂回 gene_score/scoring.py

Phase 2（战法卡修正）先写：
  test_dragon_head_seal_gate.py — (1) C1 sector_rank<=3 保留（2）C2 zt_count_today>=2 命中（3）C3 seal_to_float_ratio>=0.005 命中（4）无 market_scan_ctx → data_ok=False 整战法降级（5）seal_to_float_ratio=None → 字段级 data_unavailable 非 block
  test_consecutive_relay_lbc.py — (1) C1 lbc>=2 替代 zt_count_250d>=2（2）lbc=1 不命中（3）zt_count_250d 降为 C2 辅助加分不做门槛（4）其他战法（break_reseal/rebound）仍读 zt_count_250d 不受影响（blast radius R5）
  test_leader_drop_reversal.py — (1) 大跌>=7% 检测（2）吞没 close>=前日open 且 open<=前日close（3）volume_breakout>=1.2x（4）龙头确认 sector_rank<=3 or high_gene（5）非龙头大跌不命中

Phase 3（风控 gate）先写：
  test_intraday_loss_breaker.py — (1) 单笔浮亏>5%→should_block_add=True（2）单笔浮亏<5%→False（3）合计>8%→should_block_new=True（4）冷却期内 enforce（5）四层乘积 final_size 计算

Phase 4（regime-stratified，等 S204）：
  test_regime_stratified_dragon_lift.py — (1) MA20 3-way regime 分层正确（2）K=4 per family Bonferroni（3）wire_verdict n_comparisons=4（4）cross-regime 探索性标注（5）小 n regime underpowered 不外推

pctChg 依赖标注：lianban_lift/first_board_layer_lift/gap_window_lift 等 baostock 依赖 harness 的 test 须标注 @pytest.mark.skipif("S204 R14 未落地")，或用 mock pctChg 数据。S203 不改这些 harness（修复在 S204）。

## 6. 风险

- overfit 风险（R10 §8 DRY lens HIGH）：Dragon Score 25/25/20/15/15 flat round-number 权重+社区参数（封单 0.5%/量能 1.5-2.5x/大跌 7%）标 overfit。须 sensitivity sweep 确认 edge 在≥2/4 邻近值成立，单点=overfit→block production。sweep 后不调权重（调=过拟合）
- underpowered（§44v2 rule②）：gene_scores 46 trading days<60 R6 gate→underpowered。lianban_lift 42 天<60→underpowered。STI 退潮/高潮零天数据→regime_adaptation 无数据可验。小 n regime 标 underpowered 不外推（不判'劣于随机'），provisional ×0.5
- S204 阻塞（Track B 全部）：regime_stratified harness 须 R14 pctChg（baostock cache bars 实测仅 7 key 无 pctChg/turn/isST→_is_unbuyable_next_bar 误判一字板可买→ALL baostock backtest returns 污染）+ R8 verifier 双算 + R10 Bonferroni + R11 event drift + R13 sweep harness。S203 Track A 可独立推进，Track B 须等
- event drift 假阳性（R9 §8 §44v2 lens HIGH）：leader_drop_reversal edge_type=event，牛市 base_rate=0 drift→假阳性。须 S204 R11 universe_by_day 两样本/减市场均值修正。verifier.py:362 event 用 BH 不用 Bonferroni（与 selection :299 相反），drift 修正前 verdict 标 provisional
- blast radius（R5，**L1 修正：7 文件非 5**）：zt_count_250d 被 7 文件引用（gene_based.py:91/131/248 + strategy_base.py:348/380 + funnel/scoring.py:97/105 + **routers/workflow.py:221/250**（getattr 回退）+ **scheduler/notifications.py:57**），改 consecutive_relay C1 须 grep 全 7 文件确认不破坏 break_reseal/rebound 战法（也读 zt_count_250d）。不删列只改引用
- DRY 漂移（§8 overfit lens HIGH）：Dragon Score 5 维与 scoring.py 14 维部分重叠（封单/量能），两套归一化逻辑并存（flat vs 档位分层）→维护成本+不一致风险。若未来发现 flat 优于档位分层须统一，但当前无证据→叠加不替代，标技术债
- 撤单率不可得（R15）：cancel_rate=0.0 硬编码（bidding_monitor.py:103/133），腾讯行情不含撤单率，mootdx transactions() 返回成交分笔非委托队列。用户'撤单>30%警剔'是硬约束只有 L2 付费行情能拿——标降级口径不臆造，接 L2 须用户付费决策（core-invariant 花钱须用户定）
- Tick 级机器止损无实时管道（R16）：mootdx 0.11.7 已装但实时当日分笔流未接线+未测。回测用 baostock 5min kline 近似（不用 daily OHLCV 做 VWAP 代理=look-ahead）。实时止损须独立搭 tick 管道
- STI regime conditioner 无 population edge 验证（R13）：退潮/高潮零天数据，MVP 用连续 score 不硬分三态。须先验证 STI phase 作 regime conditioner 有 population edge（三态间 path return 均值差异 ANOVA/Kruskal-Wallis 显著）才加分——无 edge 则情绪周期维度不进融合（§44v2 rule①不外推）
- K-split 多重检验（R20 §8 §44v2 lens HIGH）：K=12（3 regime×4 战法）须拆 3 family 各 K=4≤8（决策#9）。sweep 本身是多重检验——K 须含 sweep 次数（每参数 4-5 值×多维×多战法），K 冻结 pre-registration（§44v2 rule③）。跨 regime 探索性不跨 family Bonferroni-Holm（决策#10 family grouping 去重等价）
