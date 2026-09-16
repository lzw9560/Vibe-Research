# Tasks — S204 多日跟踪架构与§44v2修正

> 状态：草案→**部分实施**（2026-09-14 起草；2026-09-16 主 loop 自主推进 G1+G2，见下方实施状态）。
> 关联：[[./spec.md]]、[[./plan.md]]、[[../_shared/dragon-score-dimension-registry.md]]。

## 实施状态（2026-09-16，主 loop 自主推进；用户 asleep）

**G1 数据地基**：
- ✅ **T1 pctchg_injector**：模块+逻辑+接线全 DONE（`fc7397d`/`ccdb3fb`/`7e75465`）。`enrich_pctchg` 修 0.0/None 覆盖；`_load_kline_cache` 单点注入 + mtime memo；8 harness 接全（lianban/gap/index_ma20/derive_first_board/zt_pool_seal_time/miaoban/valuation_pe/multifactor）。real-cache 验证 580 一字涨停板/200 股修复（baostock pctChg=0.0/None 数据缺口，实测比审计估更广——审计只数 ==0.0 漏 None）。
- ⏸️ **T2 enrich_isst**：**DEFERRED 需用户决策**。实测 cache isST 91% 缺失（baostock 仅近端 ~8.8% 回填），cache-LOCF 0/139 可修（isST 观测晚于误判板，LOCF 默认 0）。需外部历史 ST 源（baostock `query_stock_basic` current-only / akshare ST history / 重 fetch with isST field）——**选源是用户决策**。ST 污染 139 板/200 股（小于 pctChg 580/200 股），pctChg 修复是更大污染源已先做。
- ✅ **T3 forward_test_backfill cron**：DONE（`39d6c39`）。cron `0 18 * * 0-4` 注册，long-running ~3 个月真实交易日积累 ≥60 天（不可臆造/加速）。

**G2 §44v2 verifier 修正**（DONE）：
- ✅ **T5** verifier 双算 + R5 查 ALL 窗口：DONE（`fb2cc65`）。
- ✅ **T5b** event_drift：DONE + wired `verifier.py:18/368`（`fb2cc65`）。
- ✅ **T6** family_grouping：DONE（`fb2cc65`，2026-09-16 核 family_grouping.py：`EQUIVALENCE_FAMILIES` 3 族 + `effective_family_count` + `split_into_subphases`（K=12→[8,4]）+ `FrozenK` dataclass 全在）。

**未做**（G3-G7）：
- ⏸️ T4 underpowered 标注（R15/R16/R17）/ T7 DIM_ARM_MAP arm-sizing（audit: evaluation.py:241 空转）/ ✅ T8 R3 enforce DONE（`012fef3`，r3_enforce scheduler 接线——per-arm 算 current days_robust + ≥60 → lift_to_multiplier + write_override，非 arm 级 frozen，cron 0 6 * * 0-4，8 test 全绿）/ ✅ T9-T12 跟踪架构接线 DONE（`45bafca` tracking router + `30e4d9b` escalation tracking_age_days + `f3beae9` T10 adapter）/ T13 sweep harness（built `06f898a` 待 G6 验）。

**配套**：
- ✅ test_e2e.py 挂起修（`3168106`，@live 标 TestRiskEndpoints 2 测试，解全量 pytest 安全网）。
- ✅ S207 spec 审计修正 9→11 + P1 非 P0（`23a5e90`，[[s44-verdict-production-link-verified]]）；≥6 lens grill 跑中（wf_e7376d78-a23）。

---

## Cross-spec 全局 phase 序（synth）

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


### P1 数据 blocker (R14 pctChg+isST / R16 回补 / R15-R17 标注)

- [ ] **T1**: R14 pctChg harness 层注入（cache 路径）— blocker #1
   - acceptance: 骨架（注入纯函数，harness 层调，不动 bar_utils.py 源码）：
```python
def enrich_pctchg(bars: list[dict]) -> list[dict]:  # immutable 返新 list
    out = []
    prev_close = None
    for b in bars:  # bars 已按 date asc
        pct = (b["close"] - prev_close) / prev_close * 100 if prev_close else 0.0
        out.append({**b, "pctChg": b.get("pctChg", round(pct, 4))})
        prev_close = b["close"]
    return out
```
验收（可测）：
1. test_pctchg_injection_fixes_one_line_board — cache bar 无 pctChg 字段（7 字段 baostock_kline_cache.json 格式）→ 不注入时 is_unbuyable_next_bar 返 False（bug：_bar_get(nb,"pctChg",0.0)=0.0 < threshold）；enrich_pctchg 注入后同一 bar is_unbuyable=True（一字板 pctChg≥9.8 被正确识别）。
2. test_pctchg_reproducible — 注入值=(close[d]-close[d-1])/close[d-1]*100 与 baostock fallback 路径 pctChg 字段一致（±0.01 容差）。
3. test_enrich_immutable — 原 bars list 不被修改（新 list 返回）。
   - test: tests/test_s144_unbuyable_t1.py
- [ ] **T2**: R14 isST 派生（不可默认 '0'）— blocker #1 配套
   - acceptance: 骨架：
```python
@dataclass(frozen=True)
class STStatus: code: str; is_st: bool; as_of: str

def fetch_st_codes(as_of: str) -> frozenset[str]: ...  # baostock query_stock_basic 或 ST 列表

def enrich_isst(bars: list[dict], code: str, st_codes: frozenset[str]) -> list[dict]:
    return [{**b, "isST": "1" if code in st_codes else "0"} for b in bars]
```
验收：
1. test_st_one_line_board_5pct_threshold — ST 股（isST='1'）一字板 pctChg=+5.0 → is_unbuyable_next_bar=True（limit_pct=5.0, threshold=4.8）；不派生 isST（缺省 0）→ is_unbuyable=False（bug，误用 10% 阈值）。
2. test_non_st_uses_board_pct — 非 ST 主板股 isST='0' → limit_pct=10.0（_limit_pct_for_code），isST='0' 不被 truthy 误判（bar_utils.py:69 int(float('0'))==1=False 已处理，验不回退）。
3. test_isst_derived_not_fabricated — st_codes 来自 baostock query_stock_basic（可复算），非硬编码全 0。
   - test: tests/test_s144_unbuyable_t1.py
- [ ] **T3**: R16 forward_test_records 回补至≥60天（决策#13 优先）
   - acceptance: 骨架（scheduler task，复用 scheduler/executors/__init__.py:55 _executors 注册模式）：
```python
# scheduler/executors/__init__.py _executors dict 加：
"forward_test_backfill": self._execute_forward_test_backfill,
# scheduler/seed.py 加 task：
task_type="forward_test_backfill", cron_expr="0 18 * * 0-4", payload={"target_days": 60}
```
验收：
1. test_backfill_reaches_60_days — 回补后 forward_test_records 唯一 exit_date 数 ≥60（当前~20 交易日的实测值，spec §1.3 核 337 行/~20 天）。
2. test_backfill_idempotent — 重复跑 backfill 不重复插入（UPSERT / INSERT OR IGNORE）。
3. test_backfill_executor_registered — scheduler/executors/__init__.py _executors dict 含 "forward_test_backfill" key。
   - test: tests/test_forward_test_records_backfill.py
- [ ] **T4**: R15 underpowered 标注 + R17 数据源诚实标注（依赖: T1, T3）
   - acceptance: 骨架（harness post-process 纯函数）：
```python
@dataclass(frozen=True)
class UnderpoweredLabel:
    source: str; days: int; label: str; reason: str

def label_underpowered(source: str, days: int, n_events: int | None = None) -> UnderpoweredLabel:
    if source == "institutional" and n_events and n_events < 10:  # 季度~4/年
        return UnderpoweredLabel(source, days, "structural_underpowered", "quarterly cadence")
    if days < 60:
        return UnderpoweredLabel(source, days, "underpowered", "days<60 §44v2 rule②")
    return UnderpoweredLabel(source, days, "adequate", "")
```
验收：
1. test_gene_scores_underpowered_label — gene_scores(~60 天) → label underpowered，harness 不输出 robust/falsified verdict（§44v2 rule② 不外推）。
2. test_seal_intraday_underpowered — seal_intraday(10 天) → underpowered。
3. test_sti_zero_days — STI 退潮/高潮(0 天) → underpowered，regime_adaptation 无数据不验。
4. test_institutional_quarterly_override — institutional(季度披露~4 事件/年) → structural_underpowered（verifier 无此机制，harness override）。
5. test_cancel_rate_honest — cancel_rate 字段标 "不可得（仅 seal_amount 阈值）"，非硬编码 0.0（bidding_monitor.py:103/133）。
6. test_mootdx_tick_blocker_label — mootdx 实时分笔标 BLOCKER，回测用 5min kline 近似（非 daily OHLCV 做 VWAP 代理=look-ahead）。
   - test: tests/test_underpowered_labeling.py

### P2 §44v2 修正 (R8 verifier 双算 / R10 Bonferroni-family-K冻结 / R9 DIM_ARM_MAP arm-sizing / R3 enforce 接线)

- [ ] **T5**: R8 verifier 双算 + R5 查 ALL 窗口（verifier-side only，决策#7 supersede harness-side）
   - acceptance: §8 HIGH：R8 双算是方法论变更，spec §5 grill 已起（w50pptu5i+wc8g37bbx），plan/tasks 阶段不再每步过 §44（§44v2 rule③）。

骨架（verifier.py 改两处）：
```python
# verifier.py:343 当前：if edge_type in _EVENT_EDGE_TYPES and ... → event_metrics
# 改为：任何 edge_type 都算 event_metrics（去掉 _EVENT_EDGE_TYPES 条件）
event_metrics = _compute_event_metrics(...)  # 无条件算
# verifier.py:251-276 R5 当前：查 edge_window（edge_type 匹配窗口）单一
# 改为：查 window_sanity ALL keys，任一窗口有优势 → 非 exploratory
```
验收（爆炸半径=破坏 5 个现有 R5/bonferroni test，须同步更新）：
1. test_verifier_dual_calc_selection_and_event — edge_type="selection" 调 wire_verdict → result.event_metrics is not None AND result.selection_lift is not None（当前 event_metrics=None 对 selection，bug）。
2. test_verifier_dual_calc_event_and_selection — edge_type="event" → 两者都 not None（当前 selection_lift 可能 None）。
3. test_r5_checks_all_windows（M3 修正：三层不混）— window_sanity={"overnight_gap":{...},"d1_intraday":{...},"path":{...}}，**R5 gate 层**：任一窗口 lift≥1.0=有优势→过 gate 进重方法论（非 exploratory）；全无优势→exploratory。**verdict 层**：exploratory=1≤lift<2 或 days<60→ship ×0.5；robust_edge=lift≥2+CI 不重叠+days≥60→×1.0。**R5 gate 过≠robust**。当前 R5 只查 edge_type 匹配单一窗口（selection→path），selection 策略 overnight_gap edge 不被测（§44v1 错窗口灾难重现）。
4. 更新 test_r5_window_sanity_no_advantage_forces_exploratory(:807) / test_r5_window_sanity_none_notes_skipped(:839) / test_r5_window_sanity_with_advantage_proceeds_normally(:853) 适配新 ALL-窗口语义。
5. pytest tests/test_s44_verifier.py 全绿。
6. test_n200_guard_folded（R12 折进 T5）— harness pre-check: total survivors<200 → 跳 wire_verdict 标 underpowered（verifier R6 只查 days<60 不查 n<200，harness 须加 guard）。
   - test: tests/test_s44_verifier.py

- [ ] **T5b**: R11 event_drift.py — event edge base_rate=0 drift fix（方案①：event vs universe 两样本，保 event 语义+减 drift）
   - 依赖: T5（verifier 双算后 event_metrics 任何 edge_type 都算）
   - 骨架:
```python
# 新建 backend/s44_verifier/event_drift.py
# 当前 verifier.py:358 event path base_rate=0.0（单样本 t-test mean>0）→ 牛市 drift 假阳性
# 修方案①：event edge 也算 universe_by_day，两样本测试（event_mean vs universe_mean）
@dataclass(frozen=True)
class EventDriftResult:
    event_mean: float; universe_mean: float; drift_adjusted_mean: float
    is_drift_inflated: bool

def adjust_event_drift(event_returns, universe_returns_by_day) -> EventDriftResult:
    event_mean = mean(event_returns)
    universe_mean = mean(universe_returns_by_day)  # 同日全市场 baseline
    drift_adjusted = event_mean - universe_mean  # 减市场 drift
    is_inflated = (event_mean > 0) and (drift_adjusted <= 0)  # 漂移假阳性
    return EventDriftResult(event_mean, universe_mean, drift_adjusted, is_inflated)
# verifier._compute_event_metrics 调 adjust_event_drift，event null 从 mean>0 改 drift_adjusted>0
```
   - 验收:
1. test_event_drift_two_sample — event edge 算 universe_by_day + 两样本（event_mean vs universe_mean），非单样本 mean>0
2. test_drift_inflated_bull_market — 牛市 event_mean>0 但 drift_adjusted≤0 → is_drift_inflated=True，verdict 标 provisional 非 robust（防假阳性）
3. test_no_drift_bear_market — 熊市 drift_adjusted>0 → 真 event edge，可 robust
4. test_leader_drop_depends_r11 — S203 leader_drop_reversal edge_type=event verdict 须 T5b 修正才可靠（S203 T8 P5 硬依赖）
5. test_event_drift_immutable — EventDriftResult frozen dataclass
   - test: tests/test_event_drift.py
- [ ] **T6**: R10 Bonferroni K cap 拆≤8 + family grouping 去重 + K 冻结 pre-registration（依赖: T5）
   - acceptance: 决策#9 拆≤8 不用 BH / #10 去重等价 / K 冻结。

骨架（stats.py + 新 family 模块）：
```python
# stats.py:33 _MAX_BONFERRONI_K=8 保留（拆 phase 保严格，不放宽 cap）
def split_into_subphases(k: int, max_k: int = 8) -> list[int]:  # K=12 → [4,4,4] 或 [8,4]
    return [min(max_k, k - sum(sub))] ...  # 每子 phase ≤8

# 新建 strategies/family_grouping.py（或 stats.py 内）：
EQUIVALENCE_FAMILIES = {  # 数学等价去重
    frozenset({"bollinger", "zscore"}): "mean_reversion",
    frozenset({"triple_ma", "ema_ribbon"}): "ma_stack",
    frozenset({"macd", "rsi_momentum"}): "momentum",
}
def effective_family_count(strategy_names: list[str]) -> int:  # ~9-15 非 raw 30
    ...

# K 冻结 pre-registration（harness 首次入库冻结）
@dataclass(frozen=True)
class FrozenK: k: int; frozen_at: str; strategy_count: int
```
验收：
1. test_bonferroni_split_subphase — K=12 → split_into_subphases → 每子≤8，alpha_adj=0.05/4（按 family K=4）非 cap 到 0.05/8（当前 bug：K=12 被 min(k,8) 压成 8，声称 0.05/12 实际 0.05/8）。
2. test_family_grouping_dedup — ["bollinger","zscore"] → effective_family_count=1（数学等价去重）；["bollinger","macd","triple_ma","ema_ribbon","rsi_momentum"] → 3 families。
3. test_k_freeze_preregistration — 首次入库冻结 K=12（3 regime×4 战法）→ 第二次跑 K=15 → rejected/ignored（防后调）。
4. test_k_split_by_regime — K=12 按 regime 拆 3 family 各 K=4，跨 regime 标 "per-regime FWER 独立，跨 regime 探索性"（或 Bonferroni-Holm 层级）。
5. 更新 test_bonferroni_caps_k_at_8(:235) / test_bonferroni_correction_by_n(:222) 适配 split 语义。
6. verifier.py:299-303 selection 只 Bonferroni（p_bh=None）保留并加注释"决策#9 BH 不参与 selection status"。
   - test: tests/test_s44_verifier.py, tests/test_stats_family_grouping.py
- [ ] **T7**: R9 DIM_ARM_MAP arm-sizing 扩展（非 gene arm lift-based sizing）（依赖: T5）
   - acceptance: 真实 gap = DIM_ARM_MAP arm-sizing 空转（evaluation.py:241 映射 arm→dimension 但非 gene arm 无 lift-based sizing）。trade_journal.py:400 是显示标签 NOT sizing 路径——DO NOT 改 trade_journal（spec §1.2 CRITICAL 修正）。

骨架（evaluation.py 扩展 lift_for_arm）：
```python
# evaluation.py:241 DIM_ARM_MAP 已有 arm→dimension 映射
# 当前 lift_for_arm 只读静态 DIMENSION_LIFT_REGISTRY，非 gene arm 返 ×1.0
# 改：非 gene arm 也走 lift_to_multiplier

def arm_multiplier(arm: str, registry: dict) -> tuple[str, float]:
    dims = DIM_ARM_MAP.get(arm)  # evaluation.py:241
    if dims is None:
        return ("探索性", 0.5)
    # 取 arm 对应 dimension 的 lift/days_robust → lift_to_multiplier
    return lift_to_multiplier(lift=..., days_robust=...)  # evaluation.py:195 纯函数

# scoring.py:85 当前：multiplier = gene_multiplier if factor in _GENE_BASED_FACTORS else 1.0
# 改：else 分支调 arm_multiplier(arm) 替代硬 1.0
```
验收：
1. test_arm_sizing_non_gene — 非 gene arm（如 bollinger）lift=1.5, days_robust=40 → multiplier=0.5（provisional cap），非 1.0（空转 fix）。
2. test_arm_sizing_days_lt60_cap — arm days_robust=30 → ×0.5（gene 因子级 DONE at scoring.py:59，扩展到 arm 级）。
3. test_arm_sizing_robust — arm days_robust=167, lift=2.1 → multiplier=1.0（validated 全权重）。
4. test_arm_sizing_exploratory — arm 无 lift 数据（lift=None）→ ×0.5 探索性。
5. test_scoring_uses_arm_multiplier — scoring.py:85 else 分支调 arm_multiplier 非 1.0（integration test）。
   - test: tests/test_evaluation_arm_sizing.py
- [ ] **T8**: R3 enforce scheduler 接线（S197 P0c：seed.py enforce key + executor + API/CLI 触发）（依赖: T7）
   - acceptance: §8 HIGH：scheduled_tasks files = scheduler/executors/__init__.py（注册）+ scheduler/seed.py（seed），NOT scheduled_tasks.py。实测 scheduler/seed.py payload 无 enforce key（grep 确认）。

骨架：
```python
# scheduler/executors/__init__.py:55 _executors dict 加：
"r3_enforce": self._execute_r3_enforce,

# scheduler/seed.py 加 task：
task_type="r3_enforce", cron_expr="0 6 * * 0-4",  # 盘前
payload={"enforce": True, "threshold_days": 60}

def _execute_r3_enforce(self, payload: dict) -> str:
    # 查 DIMENSION_LIFT_REGISTRY arms，days_robust 跨 60 天阈 → 调 lift_to_multiplier 降级
    # 30 天 → reminder（已有）；60 天 → enforce（新增，downgrade multiplier）
```
验收：
1. test_seed_r3_enforce_task — scheduler/seed.py 含 task_type="r3_enforce" + payload["enforce"]=True（当前无 enforce key）。
2. test_executor_r3_enforce_registered — scheduler/executors/__init__.py _executors dict 含 "r3_enforce" key。
3. test_r3_enforce_downgrades_at_60_days — arm days_robust 从 59→61 跨阈 → _execute_r3_enforce 调 lift_to_multiplier 将 multiplier 从 1.0/0.5 → 0.5/0.1（enforce 非 reminder）。
4. test_api_trigger_r3_enforce — API/CLI endpoint POST /api/scheduler/trigger {task_type:"r3_enforce"} 触发 enforce run（当前无触发路径）。
   - test: tests/test_scheduler_r3_enforce.py

### P3 多日跟踪架构 (R1 两表 / R4 early_admission / R3 escalation / R5-R6 decayed)

- [ ] **T9**: R1 两表 + 两池同步协议（candidate_tracking_pool + indicator_snapshots）
   - acceptance: 骨架（workflow_state_repo.py:49 _ensure_tables 加两表 + frozen dataclass）：
```python
@dataclass(frozen=True)
class TrackingRecord:  # immutable
    code: str; first_admit_date: str; admit_signal: str
    admit_indicators_json: str; current_status: str  # tracking 级 label
    tracking_age_days: int

@dataclass(frozen=True)
class IndicatorSnapshot:
    code: str; trade_date: str; indicators_json: str
    snapshot_source: str  # 'pre_market'/'escalation'/'early_admit'

# _ensure_tables 加（幂等 CREATE IF NOT EXISTS）:
#   candidate_tracking_pool(code,first_admit_date,admit_signal,
#     admit_indicators_json,current_status,tracking_age_days,
#     UNIQUE(code,first_admit_date))
#   indicator_snapshots(code,trade_date,indicators_json,snapshot_source,
#     UNIQUE(code,trade_date))
```
两池同步协议（spec R1 对抗审修正）：escalation run date T → 查 tracking_pool 活跃 track（current_status='tracking'）→ 对每 track 用 (code,T) 查 workflow_state（workflow_state_repo.py:180 get_state）→ 若无行 → ensure_candidate(code,T,reason='escalation from first_admit T-N',:261) 再 transition → 若盘前 run 已 insert (code,T)=filtered → escalation 跳过该 track。
验收：
1. test_tracking_pool_table_created — _ensure_tables 创建 candidate_tracking_pool 幂等（跑两次不报错）。
2. test_indicator_snapshots_upsert — 同 (code,trade_date) 插两次 → 1 行（UNIQUE + INSERT OR REPLACE）。
3. test_tracking_record_immutable — TrackingRecord frozen dataclass，setattr 报 FrozenInstanceError。
4. test_two_pool_sync_no_workflow_row — tracking_pool track first_admit=T-3, workflow_state 无 (code,T) → sync 调 ensure_candidate(code,T) 后 transition 成功。
5. test_two_pool_sync_skips_filtered — workflow_state (code,T)=filtered → sync 跳过该 track（不重复处理）。
   - test: tests/test_tracking_pool.py
- [ ] **T10**: R4 early_admission.py — pre-涨停候选识别（T-1 数据 only，pit guard）（依赖: T9）
   - acceptance: 骨架（新建 backend/early_admission.py，pit guard T-1 only）：
```python
@dataclass(frozen=True)
class EarlyAdmitCandidate:
    code: str; admit_date: str; signal_type: str  # 'sector_startup'/'relay_seed'
    indicators_t1: dict  # T-1 收盘指标

def scan_early_admission(run_date: str) -> list[EarlyAdmitCandidate]:
    latest = previous_trade_day(run_date)  # T-1，T 日未开盘 pit guard
    # 板块启动初期（sector_cycle zt_count 上升）+ 连板苗子（lbc≥1 前置）
    # 只读 ≤ latest 的数据（不读 T 日盘中）
    return [c for c in ... if _is_pre_limitup(c, latest)]
```
验收：
1. test_early_admission_uses_t1_only — run_date=T 调 scan_early_admission → 读数截止 T-1（不读 T 日盘中，pit guard）；mock T 日数据存在但 early_admission 不读。
2. test_early_admission_writes_tracking_pool — 识别 pre-涨停候选 → 写 candidate_tracking_pool（current_status='admit', admit_signal='early_admission'）。
3. test_early_admission_no_duplicate — 同 (code,first_admit_date) 两次 scan → 1 行（UNIQUE 约束）。
4. test_early_admission_pre_limitup_filter — 非 pre-涨停股（已涨停/无板块启动）不入池。
   - test: tests/test_early_admission.py
- [ ] **T11**: R3 escalation_engine.py + maturity 量化（§8 HIGH）+ R7 ensure_candidate 联动（依赖: T9, T10）
   - acceptance: §8 HIGH：maturity 须量化（社区阈值未验证 → 标探索性）。决策#11 只 candidate→watching 自动，watching 以上人工。

骨架（新建 backend/escalation_engine.py，复用 transition CAS 不改 _ALLOWED_TRANSITIONS）：
```python
@dataclass(frozen=True)
class MaturityCriteria:  # 探索性阈值，社区未验证
    min_tracking_age: int = 3
    min_gene_improvement_pct: float = 20.0  # vs admit-day
    max_sector_rank: int = 5
    decay_grace_days: int = 5  # watching 后 N 日无改善→decayed

def should_promote(track: TrackingRecord, snapshots: list[IndicatorSnapshot]) -> bool:
    age_ok = track.tracking_age_days >= MaturityCriteria().min_tracking_age
    gene_ok = _gene_improvement(snapshots) >= MaturityCriteria().min_gene_improvement_pct
    rank_ok = _latest_sector_rank(snapshots) <= MaturityCriteria().max_sector_rank
    return age_ok and gene_ok and rank_ok  # 全标探索性

def escalate(run_date: str) -> list[str]:
    tracks = repo.active_tracks(current_status='tracking')  # R1 两池同步
    promoted = []
    for t in tracks:
        snaps = repo.snapshots_for(t.code, up_to=run_date)
        if not workflow_state_repo.get_state(t.code, run_date):  # R7 联动
            workflow_state_repo.ensure_candidate(t.code, ..., run_date, reason='escalation')
        if should_promote(t, snaps):
            workflow_state_repo.transition(t.code, run_date, 'watching', reason='maturity_promote')
            promoted.append(t.code)
    return promoted
```
验收：
1. test_maturity_promote — track age=3, gene +25% vs admit, sector_rank=4 → escalate 调 transition(code,'watching') 成功。
2. test_maturity_not_met_age — age=2 → 不 promote（age<3）。
3. test_maturity_not_met_gene — gene +15% → 不 promote（<20%）。
4. test_ensure_candidate_linkage — pre-涨停 track 不在 workflow_state → escalate 先 ensure_candidate 再 transition（非直接 transition 失败，R7 fix）。
5. test_decay_after_5_days — watching track, 5 日 snapshots 无 gene/sector 改善 → tracking_pool.current_status='decayed' + workflow_state WATCHING→FILTERED（reason='decayed'）。
6. test_no_auto_holding — escalate 不调 transition('monitoring'/'holding')（决策#11 watching 以上人工）。
   - test: tests/test_escalation_engine.py
- [ ] **T12**: R5/R6 decayed resolution（tracking label 分离 workflow_state enum + 防振荡）（依赖: T9, T11）
   - acceptance: 骨架（tracking_pool label 枚举，workflow_state 不加态）：
```python
# tracking_pool.current_status 值域（tracking 级 label，NOT workflow_state enum）
TRACKING_LABELS = frozenset({"admit", "tracking", "decayed", "promoted"})
# workflow_state 仍用 WorkflowStatus 7 态（workflow_state_machine.py:25 _ALLOWED_TRANSITIONS 不动）

# decay → WATCHING→FILTERED（reason='decayed'），NOT WATCHING→CANDIDATE
# workflow_state_machine.py:28 已允许 WATCHING→CANDIDATE(S049 D7)，但 escalation 用 FILTERED 避振荡
```
验收：
1. test_tracking_labels_not_in_enum — TRACKING_LABELS {admit,tracking,decayed,promoted} ∩ WorkflowStatus enum = ∅（词表分离）。
2. test_decay_uses_filtered_not_candidate — decay → workflow_state_repo.transition(code,date,'filtered',reason='decayed')，NOT transition(code,date,'candidate')（anti-flapping，避免 S049 D7 WATCHING→CANDIDATE→watching 振荡）。
3. test_no_oscillation_loop — day1 promote candidate→watching, day6 decay watching→filtered，不回 candidate（无 candidate↔watching loop）。
4. test_escalation_passes_workflow_status — escalate 调 transition 传 WorkflowStatus.WATCHING / WorkflowStatus.FILTERED 态名，tracking_pool label 是决策输入非 state machine 态。
5. test_allowed_transitions_unchanged — workflow_state_machine.py:25 _ALLOWED_TRANSITIONS 字典不改（现有 settled/filtered 重入不变，spec §4 验收）。
   - test: tests/test_escalation_engine.py, tests/test_tracking_pool.py

### P4 sensitivity_sweep harness (R13)

- [ ] **T13**: R13 sensitivity_sweep.py — sweep harness + overfit 检测（K 含 sweep 次数）（依赖: T5, T6）
   - acceptance: 实测 tools/*_lift.py grep sweep/sensitivity 全空（harness 不存在）。依赖 T5（verifier 双算）+ T6（K/family 冻结，sweep 次数计入多重比较）。

骨架（新建 backend/tools/sensitivity_sweep.py）：
```python
@dataclass(frozen=True)
class SweepResult:
    param: str; value: float; verdict: str; lift: float; n: int

@dataclass(frozen=True)
class SweepReport:
    战法: str; param: str; results: tuple[SweepResult, ...]
    overfit_flag: bool; robust_flag: bool

def sweep_param(战法_config, param: str, values: list[float]) -> SweepReport:
    results = []
    for v in values:  # 从 registry SWEEP_PARAMS 取
        verdict = wire_verdict(战法_config, param_override={param: v})  # T5 verifier 双算
        results.append(SweepResult(param, v, verdict.status, verdict.lift, verdict.n))
    overfit = _edge_only_at_single_value(results)  # 仅单 v robust+lift≥2 邻近无 edge
    robust = _edge_at_multiple_neighboring(results)
    return SweepReport(战法_config.战法, param, tuple(results), overfit, robust)

# K 冻结：sweep 总次数 = Σ(len(values) per param per 战法) 计入 Bonferroni K（T6）
```
验收（registry §5 overfit 检测规则）：
1. test_sweep_runs_verdict_per_value — sweep seal_to_float_ratio [0.003,0.005,0.007,0.010] → 4 个 SweepResult（每值一个 verdict）。
2. test_overfit_single_value_edge — edge(robust_edge,lift≥2.0) 仅在 v=0.007，邻近 0.005/0.010 无 edge → overfit_flag=True, robust_flag=False（data-snooped）。
3. test_robust_multi_value_edge — edge 在 v=0.005 + 0.007 都成立 → robust_flag=True, overfit_flag=False。
4. test_no_edge_any_value — 所有 v 无 edge → 标 no_selection_edge（不进融合，§44v2 不外推）。
5. test_sweep_k_includes_count — sweep 总次数计入 Bonferroni K（非 raw K=战法数），K 冻结 pre-registration（调 T6 split_into_subphases）。
6. test_sweep_report_immutable — SweepReport frozen dataclass。
   - test: tests/test_sensitivity_sweep.py
