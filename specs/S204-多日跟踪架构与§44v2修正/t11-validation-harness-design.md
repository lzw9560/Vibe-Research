# T11 Escalation Threshold Validation Harness — 设计文档

> 状态：设计完成（2026-09-16，subagent a0ac95c6daf109f7c），实现 deferred（须 T10 跑 ≥60 天积累 tracking 数据后）
> 关联：[[./spec.md]] S204 T11、[[./tasks.md]] T11、escalation_engine.py、tracking_pool_repo.py

## 1. 验证问题

`MaturityCriteria`（escalation_engine.py:28-34）的 4 阈值（min_tracking_age=3 / min_gene_improvement_pct=20% / max_sector_rank=5 / decay_grace_days=5）是否**选出真跑赢的候选**？

- **promoted（watching）** vs **non-promoted（tracking，同日未过 gate）** vs **universe（同日全涨停股 baseline）**
- edge_type=**selection**（测选股力，非绝对收益事件 edge）
- 决定性指标：`day_paired_lift`（winrate lift，non-pooled，同日配对控 regime）

## 2. 方法论（复用 gap_window_lift / lianban_lift pattern）

day_paired lift（per-day survivor_winrate / control_winrate，非 pooled——pooled 会 day-cluster 膨胀，§44v2 已证 4.686x pooled→1.723x day-clustered）+ permutation p + walk-forward OOS + Bonferroni（K=2，两 arm：promoted_vs_nonpromoted + promoted_vs_universe）。

**统计栈全复用**：`stats.py:197-234` day_paired_lift / `stats.py:300-322` permutation / `stats.py:324-360` bonferroni_bh / `stats.py:374-434` walk_forward_oos / `verifier.py:172-510` verify / `_s44_wire.py:60-203` wire_verdict。

**forward return**：Option B（直接从 baostock_kline_cache 算 `simulate_holding(bars, D, -3.0, 8.0, 3)` + `_cost_pct`，mirror lianban_lift.py:59-77）——tracking pool 与 forward_test_records 分离，harness 自包含。

## 3. Harness 模块（backend/tools/escalation_threshold_validation.py，~250-300 行）

```
load_escalation_history(run_dates) → {run_date: {promoted: [...], non_promoted: [...]}}
  （读 candidate_tracking_pool + indicator_snapshots）
compute_forward_returns(tracks, kline_cache, PARAMS) → [{code, run_date, net_return, win, cost, ...}]
  （simulate_holding + _cost_pct + _is_unbuyable_next_bar 排除）
build_day_paired(promoted, control, universe) → (survivors_by_day, universe_by_day, returns, dates)
validate_thresholds(run_dates, control_type) → verdict + per-day breakdown
  （调 wire_verdict(edge_type="selection", n_comparisons=2, round_trip_cost=mean_cost, params={thresholds, arm, path, cost})）
```

两 arm：`escalation:promoted_vs_nonpromoted` + `escalation:promoted_vs_universe`，K=2 ≤8。

## 4. 数据要求（§44v2 rule②）

| 要求 | 阈值 | 当前 |
|---|---|---|
| 唯一 escalation run 日 | ≥60（verifier.py:449 R6 days_robust gate） | 0（pool 空，T10 未跑） |
| promoted picks 总数 | ≥200（S204 R12） | 0 |
| 每日最少 | ≥3 promoted + ≥3 non-promoted | N/A |

**时间线**：T10 日跑产 ~10-20 tracking/日 × ~30-50% promotion → 200 promoted 需 ~30-60 交易日；+60 日 days_robust gate → **首个非 underpowered verdict 需 T10 跑 ~3 月**。

## 5. Sensitivity Sweep（S204 R13）

4 参数 sweep：min_tracking_age [2,3,5,7] / min_gene_improvement_pct [10,15,20,30,50] / max_sector_rank [3,5,10,20] / decay_grace_days [3,5,7,10]。重跑 should_promote（不重跑 escalation）+ wire_verdict per value。K=20 拆 4 sub-phase 各 K=5 ≤8。**K 冻结 pre-registration**（§44v2 rule③）。overfit 检测：edge 仅单 v + 邻近无 → overfit block；多邻近 → robust。

## 6. Kill Criteria

| status | 条件 | 行动 |
|---|---|---|
| robust_edge | days≥60 + lift≥2.0 + p_bonf<0.05 + wf stable | 阈值验证 → 开 T11 auto-promote |
| not_validated | days≥60 + 1≤lift<2 或 p≥0.05 | 保持 disabled，manual watching，积累更多数据 |
| falsified | days≥60 + lift<1.0（promoted ≤ non-promoted/universe） | 阈值反选 → 废弃，重设 criteria |
| underpowered | days<60 或 survivors<200 | 不判，保持 disabled 等数据 |

**最强 kill**：promoted ≤ non-promoted（lift<1.0）→ 阈值反选（选了跑输的）→ falsified 废弃。

## 7. CRITICAL bug fix（2026-09-16 已修，commit 待）

**Bug**：`tracking_age_days` 默认 0（tracking_pool_repo.py:63）+ 只 promote/decay 时 update → `should_promote` age_ok (>=3) **永远 False** → 无候选 promote。

**Fix**（escalation_engine.py:escalate 加 increment loop）：每次 escalate 先对全 active tracking tracks `tracking_age_days += 1`，再 evaluate promote。test_escalate_increments_tracking_age 验证（age=0 → 3 日 escalate → age=3 → promote）。**test 之前漏了**（手动设 age=3 绕过 increment），T11 harness design subagent 发现。

## 8. Open Design Questions（待用户/后续定）

1. **audit trail**：candidate_tracking_pool.current_status 就地 mutate → 历史"date D 是否 promoted"丢失。harness 须重建决策。方案：(a) 加 escalation_log 表（轻量 audit）；(b) harness 从 indicator_snapshots 重算 should_promote（须 snapshot 完整）。**推荐 (a)**——prerequisite for harness。
2. **forward return 源**：forward_test_records（若 T10 写 strategy_code="escalation_tracking"）vs 直接 kline 算。**推荐直接 kline**（harness 自包含）。
3. **decay_grace_days 验证**：gates decay 非 promote，须单独 arm（decayed 后续收益 vs continued-watching）。**Phase 2 follow-up**。
4. **frozen_commit**：实现时 harness + sweep grid + 本设计 doc 一起 commit，SHA 作 _FROZEN_S168。后续调阈值须新 frozen commit。

## 9. 关键路径

fix tracking_age_days（已修）→ T10 pre-涨停 scanner 跑 → 60 天积累 → harness 实现 → verdict（~3 月后 T10 启动）。

**harness 设计就绪，待数据。**
