# S201b2 — Carry-Logic Optimism-Leak Fix (承重)

> 状态：**已实现**（2026-09-14 草案，b1d5e77 落地）。归档核于 2026-09-19。
> 落地证据：`backend/engine/accounting.py:123` `_is_sellable_bar` + `:183-218` `pending_stop` 状态机（locked-below-stop bar 触发 stop pending → 下个 tradeable bar 填 open），grep 核实。S201b stage 2 (99fe2b6) 的 stop carry 逻辑 follow-up。
> 归档至 `specs/_archive/`（reversible git mv）。

## 问题

S201b stage 2 引入 `_is_sellable_bar` carry 逻辑：一字跌停 bar（`high==low` 且 `≤ stop_level`）→ `_is_sellable_bar` 返回 False → **整个 stop-trigger 检查被跳过** → carry 到下 bar 重新评估 trigger。

**bug（adversarial-skeptic lens 复现，6-视角对抗审）**：若 locked-below-stop bar 后跟 **recovery bar**（`open>stop, low>stop`），stop **永不触发** → 持仓到 max_hold exit → **乐观泄露**（与 §8 verdict "falsify exit-optimism" 目标相反）。

复现场景：`entry=10.5 stop=10.185`，T+2 一字跌停 9.0（below stop），T+3 recovery open=10.5 low=10.2（above stop）→ 代码 `exit_reason=max_hold gross=+1.9%`（持仓幸存）；应 `stop` 触发 pending，T+3 open fill=10.5，`gross≈0%`。

根因：`_is_sellable_bar` 把「能不能在此 bar 成交」与「stop 是否触发」混为一谈。locked bar 价格已穿 stop → stop **触发**了（pending market sell），只是无法在此 bar 成交，须 pending 到下个 tradeable bar 填 open。

## 目标

分离 stop **TRIGGER**（price ≤ stop，不论 locked）与 **FILL**（pending market sell 填下个 tradeable bar 的 open）。

## 需求

1. locked bar（`high==low`）且 `high ≤ stop_level` → stop 触发，`pending_stop=True`（**非丢 trigger**，也非立刻 fill）。
2. `pending_stop=True` 时，下个 tradeable bar（`_is_sellable_bar True`）→ `fill=open`（pending market sell 填集合竞价 open）。
3. pending 期间若持续 locked（连续一字跌停）→ 继续 carry `pending_stop`，首个 tradeable bar 填 open。
4. take-side 不碰（§8 CRITICAL 3 不变；take 仍 `gross=float(take_profit_pct)`，limit sell）。
5. normal-touch / gap-through（非 locked）逻辑不变——4 个 stale test 的 `-3.1 / 10.174815`（stop×(1-eps)）值不变。

## 受影响文件

- `backend/engine/accounting.py` — `path_return` stop 分支（`pending_stop` 状态机；`_is_sellable_bar` 语义不变）。
- `backend/tests/test_accounting.py` — 新增 recovery test + 更新 `test_stop_locked_down_bar_carries_to_next_bar` 的 fill 语义（pending 填 open 而非 stop×(1-eps)）。

## 验收

- 新 `test_stop_locked_below_then_recovery_triggers_pending_fill`：T+2 locked below stop + T+3 recovery above stop → `exit_reason="stop"`（非 max_hold），`fill=T+3 open=10.2`，`gross=+2.0%`。
- `test_stop_locked_down_bar_carries_to_next_bar` 更新：`fill=T+3 open=9.8`（非 `stop×(1-eps)=9.5904`），`gross=-2.0%`（pending 填 recovery open，比 stop×(1-eps) 略好——overnight recovery 后 pending sell 填 recovered open 是诚实的）。
- `test_stop_gap_through` / `test_stop_normal_touch` / `test_take_profit_unchanged` 不变。
- 全 `pytest -m "not live"` 绿（16 failures 清零，含 stale test 更新）。
- 承重：不影响 take-side、cost 0.15、journal version preserve。

## 合规自查

- 工程底线：不臆造（pending fill 基于真实 bar open）；私有数据隔离（无涉）；防封（无 em_get）。✓
- §44v2：pending 修减少乐观泄露 → §44 net 更诚实（right direction，falsify optimism）。✓
- §44 不每阶段参与：此为承重 bug fix 非 methodology 变更，spec 自查轻 sanity 即可。✓
