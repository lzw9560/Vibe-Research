# S217 — consecutive_relay forward-OOS via chronological holdout

> 状态：**spec（pre-registration）**——跑测试结果前冻结 split ratio + decision rule（lens 3 要求）。
> §44-bearing：设计期 grill 已过（workflow `wb91zk9b5`，6 lens + synthesis，confidence 0.80，决议 C）。本 spec 即 lens 3 要求的"跑前 pre-register"文书。
> 分级：medium（碰 stats.py 加纯函数 + harness print，不碰 verifier.py / Verdict dataclass）。

## 问题

consecutive_relay bull regime `robust_edge` +1.5677%（in-sample），但 `walk_forward_status=None`：
机制 gap——`walk_forward_oos`（stats.py:381）是 **selection 机制**（`day_paired_lift` winrate ratio survivors/universe），event edge 不传 `survivors_by_day` → `verifier.py:294 has_lift_data=False` → walk_forward/permutation 全跳过。

6-lens grill（wb91zk9b5，已用 ACTUAL verdict day_std≈2.7% + zt_history 月分布核实）结论：
- **B（survivors=returns_by_day）= false-positive machine**——`day_paired_lift` 自比 = winrate_lift 1.0 trivially → guaranteed oos_stable。 unanimously rejected。
- **A（新 walk_forward_event_oos）now = 错**——67 bull days 太少（4 窗口 × ~10 天，power<0.5）+ `walk_forward_status` note-only 不 gate（dead code）+ 20/10/10 窗口 post-hoc 调（researcher DOF）+ freeze-violating。
- 67 bull days 严重聚簇（2025-06~08 + 2026-07~09，中间 ~10 月 backfill gap）→ walk-forward 测的是 within-cluster 一致性非时序泛化。
- 真阻塞是 **data**（10 月 gap 是 hithink backfill gap 非真无接力，S214 部分实现），不是机制。

## 目标（C: chronological holdout——最小诚实 OOS，给 milestone directional answer）

用现成 `day_clustered_t_test`（stats.py:139，one-sample 日聚簇 mean>0）跑 **pre-registered 2/3-train / 1/3-test 时序 holdout**。
- freeze-compliant：纯诊断函数 + harness print，**不碰 verifier.py / Verdict dataclass**（零 blast radius）。
- 不 gate `event_status`（gate-wiring 是 stage-2 §44 方法论变更，待 backfill 后）。
- worst case = D（inconclusive → defer + backfill），故 C dominates D in expected value。

## Pre-registration（跑结果前冻结——本节即 pre-registration）

- **split**：`train_ratio=0.667`（2/3），按 event-date 时序排，`n_train=ceil(N×0.667)`，test=rest。
  零 tunable parameter（2/3-1/3 conventional，不调不扫）。
- **test 统计**：`day_clustered_t_test`（现成，stats.py:139）on test 返回，one-sided p（mean>0）。
- **materiality floor**：`max(0.003, round_trip_cost×0.5)`（与 event_robust gate 同口径；cost=0.00961 → floor=0.004805）。
- **Decision rule**（asymmetric，偏向 cheap error，**禁止 <60 test days 翻 falsified**）：
  - `oos_supporting`：`test_day_mean > floor` AND `test_p_one_sided < 0.05` → bull ×0.5→×0.75（**NOT ×1.0**），label "provisional, within-regime only"
  - `inconclusive`：`mean>0` 但 `p≥0.05` OR `|mean|<floor` → 保持 ×0.5，追 backfill（stage 2），**不 falsify**
  - `strong_negative`：`mean<0` AND `p>0.95` → ×0.5→×0.25，flag review，**不正式 falsify** 直到 powered test
  - `insufficient`：`n_test_days<2`（算不出 t）
  - **DEFINITIVE binary（×1.0 或 STOP）= stage 2 only**：backfill 到 173 days 或 live 120+ → 重跑此 split

## 受影响文件

- `s44_verifier/stats.py`：加 `chronological_holdout_event_check()` 纯函数（~30 行，复用 `day_clustered_t_test`）
- `tools/s203_consecutive_relay_harness.py`：`main()` 调 `chronological_holdout_event_check` 打印 bull 结果
- `tests/test_s217_chronological_holdout.py`（新）：TDD

## 验收

- [ ] `chronological_holdout_event_check` 纯函数：给定 `returns+dates+cost` → 返 `{n_train_days, n_test_days, test_day_mean, test_p_one_sided, test_win_rate, train_day_mean, decision, decision_note}`
- [ ] TDD 全绿（insufficient / oos_supporting / inconclusive / strong_negative / split-ratio 五 case）
- [ ] s203 harness 跑出 bull chronological OOS directional answer
- [ ] **不碰 verifier.py / Verdict dataclass**（blast radius=0）
- [ ] split ratio + decision rule 在跑结果前已冻结（本 spec §Pre-registration）

## 合规自查（弱合规——仅工程底线）

- 不臆造：纯函数复用 `day_clustered_t_test`，不造假数字
- 私有数据隔离：不涉及（用现成 baostock cache + zt_history）
- 防封：不涉及（不调外部端点）
- §44 grill 已过（wb91zk9b5，design-期 validation）

## 关联

- [[milestone-2026-09-18-pivot]]——本 spec 是 milestone #1（consecutive_relay forward-OOS 验证）的执行载体
- [[S214-zt-history-hithink-backfill]]——stage 2 backfill（10 月 gap → 173 days）
- grill workflow `wb91zk9b5`（6 lens + synthesis，决议 C，confidence 0.80）
