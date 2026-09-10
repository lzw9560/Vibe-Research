# Tasks: S181 — 趋势波段臂（B 臂，替代搁置 ash-mcp）

> spec: spec.md  plan: plan.md  状态：草案  日期：2026-09-10  分级：large
> 每条带依赖序+验收点，TDD（先 RED 后 GREEN）。grill 后对齐再实现。

## P0 — signal generator + journal_recorder 接入（最小可跑闭环）

- [ ] T1 **trend_swing_arm.py signal generator**（依赖：sector_cycle/market_scan/non_limitup_funnel 已存在）
  - [ ] T1.1 写 test：mock sector_cycle.aggregate_sectors 返 [{industry:"半导体",zt_count_today:5,zt_momentum:1.5},...] + mock classify_phase → 验 _identify_trending_sectors 筛 phase="启动"/"发酵" + fund_flow net>0 → top 5 sectors 含正确 industry（RED）
  - [ ] T1.2 写 test：mock build_non_limitup_candidates + run_non_limitup_funnel + score_candidates 返固定 candidates → 验 select_trend_candidates(date) 返 ≤5 候选带 {code,name,sector,sector_rank,pattern,strategy_score}（RED）
  - [ ] T1.3 建 backend/strategies/trend_swing_arm.py（~150 行）：
    - TREND_STOP_PCT=-6.0 / TREND_TAKE_PCT=15.0 / TREND_MAX_HOLD=10 / TREND_TOP_N=5 常量
    - `_identify_trending_sectors(date)`：aggregate_sectors + classify_phase 筛 启动/发酵 + market._sectors() fund_flow net>0 → composite rank → top 5
    - `select_trend_candidates(date)`：_identify_trending_sectors → build_non_limitup_candidates → run_non_limitup_funnel → score_candidates → [:5]
    - `trend_arm_status(journal)` / `trend_arm_report(journal)`（from trade_journal.db 汇总）（GREEN）
  - [ ] T1.4 验收 A1+A2：mock 跑通 + shape 正确

- [ ] T2 **journal_recorder _process_trend + settle_pending_trend**（依赖 T1，仿 _process_breakout 范式）
  - [ ] T2.1 写 test：(a) _process_trend mock bars（延伸到 T+2+max_hold=12）→ 产 realized（arm="trend", is_realized=1, net_pnl 非 None, cost_pct 含 5 元 min ≠0, exit_reason ∈ stop/take/max_hold）+ hold（bars 不足 path_return None）+ unbuyable（涨停 fillability_check 拒）；(b) settle_pending_trend hold → bars 增长 → INSERT OR REPLACE **同 signal_id** 更新 is_realized=1；(c) 截断 max_hold exit bars 不足完整持仓期留 hold（RED）
  - [ ] T2.2 journal_recorder.py 加常量 TREND_STOP_PCT/TREND_TAKE_PCT/TREND_MAX_HOLD（:47-49 BREAKOUT_* 旁）
  - [ ] T2.3 DEFAULT_ARMS 改 ["floor","breakout","trend"]（:44）
  - [ ] T2.4 `_process_trend(target_date)`：select_trend_candidates → per candidate Trades→Executor.execute(T1OpenFill)→path_return(TREND_*,apply_cost=True)→insert(arm="trend")；None→hold；unbuyable→exit_reason="unbuyable"（仿 :204-307 _process_breakout 结构）
  - [ ] T2.5 `settle_pending_trend()`：query is_realized=0 arm="trend" exit_reason="hold" → bars_provider 取 bars → path_return(TREND_*) → 截断检测（max_hold + bars 不足留 hold）→ INSERT OR REPLACE 同 signal_id（仿 :119-200 settle_pending_breakout）
  - [ ] T2.6 run_daily dispatch 加 `elif arm == "trend": results[arm] = self._process_trend(target_date)`（:108 trend 从 mock 分支拆出）
  - [ ] T2.7 run_daily 开头 settle_pending 调 settle_pending_trend()（settle_pending_breakout 旁加，:97）
  - [ ] T2.8 验收 A3+A4：test pass + 既有 journal_recorder 测试不破

- [ ] T3 **P0 e2e 集成验收**（依赖 T1+T2）
  - [ ] T3.1 建 tests/test_s181_e2e.py：mock sector_cycle + market + bars_provider（A股 mock bars 延伸到 T+2+12）→ run_daily(target_date=T-1, arms=["trend"]) → 断言 DB 有 trend 记录（realized net_pnl 非 None + cost_pct ≠0 + hold unrealized + unbuyable exit_reason）
  - [ ] T3.2 验收 A9：grep 确认 trend 走 path_return(apply_cost=True) 无自造成本函数
  - [ ] T3.3 验收 A7（部分）：pytest -m "not live" -k "trend" 全绿

## P1 — 多臂推荐 + honest_label + lift/sizing 接线

- [ ] T4 **ArmHonestLabel EXPLORATORY + recommendation_engine trend 分支**（依赖 T3）
  - [ ] T4.1 写 test：get_multi_arm_recommendations() 返 trend=EXPLORATORY action_type="paper_track"（非 mock_not_ready）含 coverage_rate + days_tracked（from tj.aggregate_by_arm）+ note 含"§44 未验证"（RED）
  - [ ] T4.2 recommendation_engine.py ArmHonestLabel 加 `EXPLORATORY = "exploratory"`（:210 旁）
  - [ ] T4.3 trend 从 mock loop（:293-299）拆出独立分支：EXPLORATORY + paper_track + tj.aggregate_by_arm("trend") stats；limitup 留 mock loop
  - [ ] T4.4 验收 A5：返 trend EXPLORATORY paper_track 非 mock

- [ ] T5 **DIM_ARM_MAP + DIMENSION_LIFT_REGISTRY trend_swing 维度**（依赖 T4，无独立 test——lift_for_arm 已有测试覆盖）
  - [ ] T5.1 evaluation.py DIM_ARM_MAP "trend": None → ["trend_swing"]（:200）
  - [ ] T5.2 DIMENSION_LIFT_REGISTRY 加 "trend_swing" DimensionValidation（lift=1.0, n=0, days_robust=0, status="探索性", multiplier=0.5）
  - [ ] T5.3 验收 A6：lift_for_arm("trend") 返 (0.5, ...)（provisional cap 咬合，非 1.0）；PaperPortfolio.final_size("trend", ...) × 0.5

- [ ] T6 **前端 MultiArmPanel verdictCls/Text 加 exploratory**（依赖 T4，无后端依赖）
  - [ ] T6.1 MultiArmPanel.tsx verdictCls 加 `if (label === "exploratory") return "bg-yellow-500/15 text-yellow-600"`（:22-28）
  - [ ] T6.2 verdictText 加 `if (label === "exploratory") return "探索性·未验证"`（:30-36）
  - [ ] T6.3 验收 A8：trend 卡显黄色 badge + paper_track 渲染分支（已有 :100-103）
  - [ ] T6.4 验收 A7（前端）：npx tsc --noEmit 零错误

## P2 — 报告 + 可选 cron 接线（后续 plan 决定）

- [ ] T7 **trend_arm_status + trend_arm_report**（依赖 T3，已在 T1.3 建 stub）
  - [ ] T7.1 写 test：mock trade_journal query_records(arm="trend") → trend_arm_status 返 {n_open, n_realized, avg_pnl, coverage_rate}；trend_arm_report 返 {positions, summary, risk_disclaimer}
  - [ ] T7.2 实现 trend_arm_status(journal) + trend_arm_report(journal)（from trade_journal.db 汇总，仿 hold_status/weekly_report 范式）
  - [ ] T7.3 验收：report 含 risk_disclaimer="历史统计特征，市场有风险"

- [ ] T8 **可选：scheduler cron 接线**（deferred，本 spec 不强制）
  - [ ] T8.1 scheduler/executors/journal.py DEFAULT_ARMS 含 trend（run_daily arms 参数透传，已含）
  - [ ] T8.2 验收：POST /api/scheduler/run task_type=trade_journal_daily 返 trend stats（非 unknown_arm）
  - [ ] T8.3 注：cron 接线 deferred——本 spec 只建工具，接线在后续 plan 决定（仿 S172 R5 周报先手动跑）

## 验收总表（spec §6 对齐）

- [ ] A1 select_trend_candidates 返 ≤5 候选正确 shape（T1.4）
- [ ] A2 _identify_trending_sectors 返 启动/发酵 sectors（T1.4）
- [ ] A3 _process_trend 产 trade_journal 记录（T2.8）
- [ ] A4 settle_pending_trend 重算 hold（T2.8）
- [ ] A5 trend=EXPLORATORY paper_track（T4.4）
- [ ] A6 lift_for_arm("trend")=0.5（T5.3）
- [ ] A7 pytest 全绿 + tsc 零错误（T3.3+T6.4）
- [ ] A8 前端显黄色 badge（T6.3）
- [ ] A9 成本走 path_return(apply_cost=True)（T3.2）