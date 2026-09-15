# Spec: S207 — §44 cost 单位 100x blocker（11 harness round_trip_cost 传 pct-points，verifier 期望 ratio）

> 状态：草案（2026-09-16 审计修正：9→11 harness，补 valuation_pe_lift + zt_pool_seal_time_lift + 3 latent risks）
> 作者：lzw9560  日期：2026-09-15
> 关联：S201（cost 口径统一）、S159（§44v2 应用规约）、[[s44v2-infra-gaps-three-criticals]]（BH 那条已过时，本 spec 审计修正）、[[s44-verdict-production-link-verified]]（2026-09-16 对抗验证：bug 真但**不达生产** weight_multiplier→S207=P1 非 P0）
>
> Codebase Archaeologist drift audit（2026-09-15）发现 + 2026-09-16 reviewer 复核。§44 承重 + 数据污染，**必须 ≥6 lens grill 才能实现**。

## 1. 问题 / 目标

11 个 §44 harness 把 `round_trip_cost` 当**百分点**传（0.15 = 0.15%），但 `verifier.py:408` 期望 **ratio**（0.0015）→ **100x 单位错** → `effective_floor = max(0.003, cost*0.5)` 膨胀 100x（0.003 → 0.075）→ 正常 day_lift（0.01-0.05 量级）全被 floor 误杀 → **11 个 harness 的 §44 verdict 被静默 falsify/underpowered**。

**优先级（2026-09-16 对抗验证修正）**：S207 = **P1（研究层 verdict 腐败）非 P0（生产信号污染）**。生产 sizing 走 `get_effective_dimension`（冻结 `DIMENSION_LIFT_REGISTRY` → `lift_to_multiplier`），从不读 9 harness 写入的研究专用 recorder。11 个有 bug的 harness 里只 2 个（`platform_breakout` lift 1.0791 / `low_absorption` lift 1.0015）冻结进 registry，且 lift≈1.0 大概率不翻案。**修仍要做**（腐败 recorder verdict 误导未来 re-validation + §44v2 R3 enforce 回路），但不抢占 G1（baostock pctChg 污染是更大污染源，已修）。

目标：11 harness 传 ratio（对齐 `cost_sweep_s201b.py:118` 的 `/100` 口径），floor 回到 ~0.003，verdict 恢复真实。

## 2. 背景

S201b 把 cost 从 flat 0.70% 改成 per-trade `_cost_pct`（返**百分点**，如 0.15 = 0.15%）。但 11 harness 直接 `sum(_cost_pct(...))/len` 传给 `wire_verdict(round_trip_cost=...)`，没除 100。

verifier.py:408 `effective_floor = max(event_materiality_floor, round_trip_cost * 0.5)`，`_EVENT_MATERIALITY_FLOOR=0.003`（ratio）→ 期望 `round_trip_cost` 也是 ratio。传 0.15 → `0.15*0.5=0.075 >> 0.003` → floor=0.075 → `t_res.day_mean > 0.075` 几乎永不成立 → robust_edge 全杀。

4 个 harness 传对了（做 `/100` 或用 ratio 变量）：`gap_regime_stratified.py:472`(avg_cost_ratio)、`midline_event_harness.py:167`(avg_cost_ratio)、`cost_sweep_s201b.py:118/165`(/100)、`run_s194_f3_verdict.py:52`(/100)。

## 3. 需求清单

- [ ] R1：11 harness 传 `round_trip_cost` 前除 100（pct-points → ratio），对齐 `cost_sweep_s201b:118`
- [ ] R2：重跑这 11 个 harness 的 verdict，记录 before/after status 变化（哪些 falsified→robust_edge 翻案）
- [ ] R3：审翻案的 verdict——之前"falsified"的是 floor 误杀还是真没 edge（用 §44v2 window-sanity + day_paired 复核，禁盲信翻案）
- [ ] R4：加单位防回归测试——`round_trip_cost` 传 ratio（< 0.1）时 floor ≈ 0.003；传 pct-points（> 0.1）应 fail-fast 警告（防再写错）。**升级为 hard raise 非 warning**（per-harness 完整性依赖枚举，fail-fast 是安全网）
- [ ] R5：受影响下游同步——翻案的 verdict 若进 `DIMENSION_LIFT_REGISTRY` / `lift_to_multiplier`，对应 weight_multiplier 重算。**注：对抗验证结论是 11 harness 只 2 个冻结进 registry（platform_breakout + low_absorption，lift≈1.0 大概率不翻案）→ R5 实际影响面极小，但仍走 §44v2 复核禁盲信翻案**

## 4. 受影响文件

| 文件 | 改动 |
|---|---|
| `backend/tools/gap_window_lift.py:125` | `round(sum(...)/len, 4)` → `/100.0` |
| `backend/tools/first_board_layer_lift.py:526` | 同 |
| `backend/tools/first_plate_h2_lift.py:436` | 同 |
| `backend/tools/lianban_lift.py:132` | 同 |
| `backend/tools/index_ma20_regime_lift.py:331` | 同 |
| `backend/tools/miaoban_superset_31d_lift.py:98` | 同 |
| `backend/tools/platform_breakout_lift.py:252` | 同 |
| `backend/tools/low_absorption_c3_lift.py:238` | 同 |
| `backend/tools/block_trade_lift.py:349` | 同（`_mean_cost_pct` → `/100`） |
| `backend/tools/valuation_pe_lift.py:105` | 同（**2026-09-16 审计补漏**：`sum(o["cost"])/len` 无 /100，edge_type=selection） |
| `backend/tools/zt_pool_seal_time_lift.py:182` | 同（**2026-09-16 审计补漏**：`sum(o["cost"])/len` 无 /100，edge_type=selection） |
| `backend/s44_verifier/tests/test_round_trip_cost_unit.py` | 新增 R4 单位测试（hard raise） |

### 4.1 latent cost-unit risks（2026-09-16 审计补充，非当前 bug 但须 spec 标注防回归）

| 文件 | 风险 | 处置 |
|---|---|---|
| `backend/tools/lockup_lift.py:38,418` | `COST_PCT=0.0`（当前无 bug：0.0*0.5=0.0，floor=max(0.003,0.0)=0.003），但变量名 `_PCT` 暗示百分点——若有人改非零 pct 值会静默重引入 100x bug | 注释标注「此处须 ratio；改非零须 /100」或 R4 fail-fast 覆盖 |
| `backend/tools/regime_stratified_first_board_limitup_lift.py:56,111` + `regime_stratified_reverse_package_lift.py:56,111` | `round_trip_cost:float=0.0` 参数默认 0.0，当前无生产调用方传值；未来调用方传 pct-points = 静默 bug | 参数注释标注「ratio 非 pct-points」+ R4 fail-fast |
| `backend/tools/midline_event_harness.py:160` | 显式 cost 参数路径：`avg_cost_ratio = cost if cost is not None`（as-is 不 /100）；spec 原 §2 列此为「4 正确」但未审显式 cost 调用方 | 审调用方；若调用方传 pct-points 须 /100 |

## 5. 设计方案

**主方案：11 harness 各加 `/100.0`**（pct-points → ratio），对齐 `cost_sweep_s201b:118` 已验过的口径。最小改动、显式、每 harness 自己负责传对单位。

**备选（不选）：在 verifier.py:408 内部 normalize**（`round_trip_cost = round_trip_cost/100 if round_trip_cost > 0.1 else round_trip_cost`）——不选，理由：① 让单位歧义藏进 verifier，11 harness 该传对的职责被掩盖；② 阈值 0.1 是启发式，0.1% 成本（极少）会被误判成 pct-points 多除一次；③ 违反"输入验证在边界"原则，verifier 不该猜调用方单位。

**备选（不选）：统一让 `_cost_pct` 返 ratio**——不选，理由：`_cost_pct` 返百分点是 accounting 域约定（和 `path_return` 的 gross/cost 都是百分点一致），改它会牵动 path_return/gap_net_return 等一串，爆炸半径大。在 harness 边界（传给 verifier 前）转单位更安全。

## 6. 验收标准

- [ ] A1：11 harness grep 确认 `round_trip_cost=` 表达式含 `/100.0`（或变量已是 ratio）
- [ ] A2：重跑 11 harness，`effective_floor` 回到 ~0.003（不是 ~0.075）
- [ ] A3：11 verdict before/after 表（status 变化记录，翻案的标"待 §44v2 复核"非直接采信）
- [ ] A4：R4 单位测试 `pytest -m "not live" backend/s44_verifier/tests/test_round_trip_cost_unit.py` 过（传 pct-points > 0.1 hard raise）
- [ ] A5：翻案 verdict 涉及数据的，跑 `~/tools/financial_rigor.py` 验算（禁心算）

## 7. 合规与工程底线自查

- [x] 研判属系统能力（§44 verdict 是研究性判断，非买卖指令）——输出挂轻量风险提醒
- [x] **判断须可复现**：11 harness 重跑 + financial_rigor 验算，禁臆造/心算（EB3 本身就是单位臆测的代价）
- [x] 私有数据未进 git（harness 读 .vibe-research/ 数据，已 gitignore）
- [x] em_get 防腐：不涉及东财端点
- [x] **§44v2 承重**：按 CLAUDE.md 自动复盘（2026-09-05），涉及 §44 统计方法论 + 关键验证逻辑的 spec **必须 ≥6 lens grill workflow**（solo review 不够，S150/S153 教训）。本 spec 实现前起 grill。
- [x] §44 v2 应用规约（S159）：翻案 verdict 不直接采信，走 day_paired + window-sanity 复核
- [x] **P1 非 P0 标注**（2026-09-16 对抗验证）：11 harness verdict 不达生产 weight_multiplier，修是研究层诚信非生产信号救火

## 8. 测试计划

- `pytest -m "not live" backend/s44_verifier/tests/test_round_trip_cost_unit.py`（R4 新增，hard raise）
- 11 harness 各自重跑（`python backend/tools/<harness>.py`），对比 before/after verdict
- 涉及 gap 的，跑 `~/tools/financial_rigor.py cross-validate` 验 net return 口径

## 9. 风险与回滚

**影响面**（2026-09-16 对抗验证修正）：11 harness verdict 可能翻案——但**只 2 个（platform_breakout + low_absorption）冻结进 `DIMENSION_LIFT_REGISTRY`**，且 lift≈1.0（≈null edge，大概率低于 corrected 0.003 floor → 可能不翻 status）。其余 9 个是研究专用 recorder verdict，不达生产 sizing。所以**生产 weight_multiplier 实际不受影响**（P1 非 P0）。R5 仍走 §44v2 复核禁盲信翻案。

**回滚**：11 harness 的 `/100.0` 改动是单行，`git revert` 即可。verdict 翻案若已进 registry，回滚 registry 的 lift_override（§44v2 override 表支持回滚）。

**特别风险**：EB3 可能让之前 S201b 的"falsified"结论部分失效（如 F3 -1.76% 若是 floor 误杀则需重审）。**S201b 的结论须在本 spec 实现后重审**，不能沿用。
