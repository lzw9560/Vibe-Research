# Spec: S197 — r3-enforce 接线（R3 task reminder→enforce + registry DB-backed 动态读）

> 状态：草案（待 6 视角对抗审 + 9-25 forward_test 30 天数据 + 用户确认破坏性 safeguard）
> 作者：Claude  日期：2026-09-13
> 分级：medium（改 scheduled executor + DIMENSION_LIFT_REGISTRY 读法，承重 + 破坏性）
> 关联：RB-8 backlog / §44 v2 P0 (c) / [[S151 R3]] / [[S180 r3 sizing]] / [[S159-§44应用规约v2]]

## 1. 问题 / 目标

**RB-8 现状（2026-09-13 调研）**：
- §44 v2 P0 (a) lift_to_multiplier 接线生产 ✅ DONE（verifier.py:12 + scoring.py:68，替代直读 frozen weight_multiplier）
- §44 v2 P0 (b) days_robust<60 provisional cap ×0.5 ✅ DONE（evaluation.py:212 gate + 219-225 分支，生产侧已 enforce）
- forward_test monitor endpoint ✅ DONE（S188 P0 #3，scheduled_tasks.py:115）
- get_forward_test_summary 评估逻辑 ✅ DONE（forward_test.py:349，算 lift/winrate/passed/buyable-only）
- **R3 task（evaluation_backtest）仍 reminder**——到点写 checkpoint + WARNING + 返 action 指引「由人/会话跑 harness」，**不自动验证**
- DIMENSION_LIFT_REGISTRY 冻结常量（evaluation.py:48，frozen_commit 锁定 2026-09-05）

**backfill 无效（真 OOS blocker，非 lazy wait）**：
- forward_test picks 依赖 live intraday seal data（gene_scores eastmoney_live），深度 backfill 被 seal_time 墙挡（东财 zt_pool 30 天滚动无深历史，S069 spec §2）
- 07-13→08-16 的 25 天 eastmoney_live gene_scores 虽存在，但 score_candidates 07-13 后改过（`27403bc fix(forward_test): score_candidates 'none' 占位过滤`）→ backfill 重算 picks 用当前逻辑 = look-ahead bias
- synthesizer 判 backfill_feasible:false + methodologically_valid:false **正确**

**目标**：让 R3 task（evaluation_backtest）从 reminder 升级为 **enforce**——到点自动跑 day_paired_lift harness + 写 evaluation_lifts.db + DIMENSION_LIFT_REGISTRY 从冻结常量→DB-backed 动态读。运行需 forward_test 30 天数据（~9-25，live OOS 积累，不可 backfill）。

## 2. 需求清单

- [ ] R1：evaluation_backtest 到点自动跑 harness
  - 30 日 + n≥100 → 自动 subprocess 调 `tools/first_board_layer_lift.py --baostock`（day_paired_lift 非池化）
  - 写 `evaluation_lifts.db`（VR_DATA_DIR，per-dimension lift/n/days_robust/CI）
  - 当前 action 是「返操作指引由人跑」→ 改「自动跑 + 写 db + 返结果」
- [ ] R2：DIMENSION_LIFT_REGISTRY DB-backed 动态读
  - 从冻结常量 dict → 读 evaluation_lifts.db（fallback 冻结值，db 缺/坏不崩）
  - `lift_for_arm`（evaluation.py:254）改读 db 动态值（非冻结）
  - 降级范式对齐 _load_cache：db 缺/坏返冻结值（memory fallback-empty-write-corrupts）
- [ ] R3：safeguard（破坏性——自动改生产 weight_multiplier）
  - 默认 dry-run：到点写 checkpoint + WARNING + 返「建议跑 harness」（现状），不自动更新 registry
  - 需 payload `enforce=True` 才真自动跑 + 写 db + registry 动态读生效
  - 60 日复验 DUE 同理（重跑 lift + 判升降级 lift≥2+CI不重叠→validated×1.0 / lift<1 robust→劣于随机×0.1）
- [ ] R4：不破坏现有 lift_to_multiplier 接线（evaluation.py:195 纯函数不动，只改 registry 读法）
- [ ] R5：mock 测（30 天数据未到，用 mock forward_test_records 测自动跑 + db 写 + registry 动态读 + safeguard）

## 3. 受影响文件

| 文件 | 改动 |
|---|---|
| `backend/scheduler/executors/backtest.py:115` | evaluation_backtest 加自动跑 harness + 写 db + enforce flag 逻辑 |
| `backend/candidate_funnel/evaluation.py:48` | DIMENSION_LIFT_REGISTRY 从冻结常量→`_load_lifts_db()` 动态读（fallback 冻结） |
| `backend/candidate_funnel/evaluation.py:254` | lift_for_arm 改读 db 动态值 |
| `backend/tests/test_r3_enforce.py` | 新建：mock 30 天数据测自动跑 + db 写 + registry 动态读 + safeguard dry-run/enforce |

## 4. 验收

- [ ] A1：evaluation_backtest 30 日 DUE + enforce=True → 自动跑 first_board_layer_lift + 写 evaluation_lifts.db（mock 数据测）
- [ ] A2：DIMENSION_LIFT_REGISTRY 读 db 动态值，db 缺/坏 fallback 冻结值不崩
- [ ] A3：safeguard——默认 dry-run 不自动更新 registry；enforce=True 才生效
- [ ] A4：lift_to_multiplier 接线不变（evaluation.py:195 纯函数 + verifier.py/scoring.py 调用不变）
- [ ] A5：pytest not live 全绿（mock 测覆盖 R1-R3）
- [ ] A6：运行评估（非测试）——等 forward_test 30 天 live 数据（~9-25），到点真跑出 lift verdict

## 5. 合规与工程底线自查

- [x] 不臆造：lift 从 first_board_layer_lift.py day_paired harness 算（非手填），days_robust 从 forward_test_records 实数
- [x] 私有数据隔离：evaluation_lifts.db 在 VR_DATA_DIR（.vibe-research/，gitignored）
- [x] 破坏性 safeguard：自动改生产 weight_multiplier 风险→ dry-run 默认 + enforce flag（用户/会话显式触发才真更新）
- [x] 降级范式：db 缺/坏 fallback 冻结值（不阻塞生产，同 _load_cache fallback-empty-write-corrupts）
- [x] backfill 无效已诚实标注（非 lazy wait，真 OOS blocker）

## 6. 关联

- [[RB-8]] backlog（r3-enforce 接线）
- §44 v2 P0 (c)：R3 enforce 非 reminder（CLAUDE.md §1.2）
- [[S151-评价层]] R3 / [[S180-r3-sizing-wiring]] / [[S159-§44应用规约v2]]
- first_board_layer_lift.py（day_paired_lift harness，已存在）
- forward_test.py get_forward_test_summary（评估逻辑，已实现）
- memory: [[backfill-historical-data-before-waiting]]（RB-8 backfill 试过无效，真 blocker）

## 7. 实现时序

- **现在（9-13）**：spec 草案 + 6 视角对抗审设计（safeguard / registry 动态读风险 / 自动 vs 半自动）
- **9-25 数据到**：forward_test 30 天 live → 实现 R1-R5 + mock 测 + 真跑首次评估
- **9-25 后**：60 天复验 DUE（reverify）→ 升降级 verdict
