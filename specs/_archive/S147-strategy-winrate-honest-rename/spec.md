# Spec: S147 — strategy 信号 winrate 诚实重命名（§1.2 不臆造收口）

> 状态：已实现 2026-09-03
> 作者：Claude  日期：2026-09-03
> 关联：S144（§44 expert verdict item 3 flagged strategy_base:334 臆造 winrate；Tier0 4a9c714 只加注释未修名/contract）

## 1. 问题 / 目标

`strategy_base.py:336` 仍跑 `historical_win_rate = min(confidence * 0.8 + 0.2, 0.95)`——一个
confidence→winrate **合成映射 heuristic**，但变量/字段/API key 都叫 `historical_win_rate`
（暗示"实测历史胜率"）。§44 expert verdict（2026-09-02）定此为 §1.2「不臆造」违规
（HIGH，item 3）。Tier 0（4a9c714）只加了诚实注释，**没修字段名/contract**——字段仍叫
`historical_win_rate`、dataclass 注释仍写"历史成功率"、API 仍 emit 该 misleading key。

**目标**：诚实重命名 `historical_win_rate` → `confidence_mapped_winrate` + 加 `winrate_source`
字段显式标源。保留 heuristic 公式（可复现、作 sort fallback 合法）但诚实命名/标源，解 §1.2。
position_advisor_v2 已用真 backtest winrate 覆写，本 spec 只修 leak（字段名/API/排序/v1 label）。

## 2. 背景与 blast radius（fresh grep 2026-09-03）

`historical_win_rate` 引用 6 处 + 1 dataclass 字段：
- `limitup_strategy.py:100` StrategySignal 字段（注释"历史成功率"= 误导）
- `strategy_base.py:336` 公式 / `338` avg_return 计算 / `376` 输出字段 / `392` 排序键
- `routers/strategy.py:40` API emit `GET /api/strategy/signals/{code}`
- `strategy_matcher.py:100` 注释 / `position_advisor.py:126` v1 label（已诚实"置信度映射(非实测)"）

**无 MCP emit、无 frontend 引用、`get_top_strategy_match` 无调用方**（grep 空，排序路径近 dead）。
故可干净重命名，不需 backward-compat alias。

## 3. 需求清单

- [ ] R1 `limitup_strategy.py` StrategySignal：`historical_win_rate` → `confidence_mapped_winrate`
      + 注释改"confidence→winrate 合成映射（非实测）；见 winrate_source"；加 `winrate_source: str = "confidence_map_synthetic"` 字段。
- [ ] R2 `strategy_base.py`：local var + 公式 + `historical_avg_return` 计算 + 输出字段 + 排序键全改名；
      signal 构造时设 `winrate_source="confidence_map_synthetic"`。
- [ ] R3 `routers/strategy.py:40`：API emit `confidence_mapped_winrate` + `winrate_source`（drop 旧 key）。
- [ ] R4 `position_advisor.py:126` v1 label 字段引用改；`strategy_matcher.py:100` 注释改。
- [ ] R5 测试：signal 构造含 `confidence_mapped_winrate` + `winrate_source`；无 `historical_win_rate` 残留（grep 0）。

## 4. 受影响文件

| 文件 | 改动 |
|---|---|
| `backend/limitup_strategy.py` | R1 字段重命名 + 注释 + winrate_source 字段 |
| `backend/strategies/strategy_base.py` | R2 var/公式/输出/排序重命名 + 设 source |
| `backend/routers/strategy.py` | R3 API emit 新 key + source |
| `backend/strategies/position_advisor.py` | R4 v1 label 字段引用 |
| `backend/strategies/strategy_matcher.py` | R4 注释 |
| `backend/tests/`（strategy signal 相关） | R5 更新字段断言 |

## 5. 设计

保留 heuristic 公式 `min(confidence * 0.8 + 0.2, 0.95)`（可复现、作 sort fallback 合法）——
§1.2「不臆造」违规在**命名**（合成值叫"历史胜率"= 谎报数据来源），非公式本身。诚实命名 +
显式 `winrate_source` 解违规：consumer 不可能误读为实测。真实测 winrate 由 position_advisor_v2
的 run_strategy_backtest 覆写（不在本 spec scope）。

不接 backtest 实测 winrate 到 match_strategies（per-signal 无对应 backtest；position_advisor
已覆写）——避免 scope 蔓延 + 数据依赖。接实测属后续若需要。

## 6. 验收标准

- [ ] A1 `grep -rn "historical_win_rate" backend/` = 0（除 spec 自身 + 可能的 deprecated 注释）
- [ ] A2 StrategySignal 含 `confidence_mapped_winrate` + `winrate_source` 字段
- [ ] A3 API `/api/strategy/signals/{code}` emit `confidence_mapped_winrate` + `winrate_source`
- [ ] A4 pytest 全绿（deselect newsradar_global_intel/s032/s040 flaky）
- [ ] A5 §1.2 自查：无合成值以"历史/实测 winrate"名义呈现

## 7. 合规与工程底线自查

- [x] §1.2 不臆造：合成 heuristic 诚实命名 + 显式 source，不再以"历史胜率"呈现
- [x] 不涉及私有数据 / 新东财端点 / 交易信号（研究展示层 honesty）
- [x] 判断可复现：heuristic 公式不变，可复算

## 8. 测试计划

- 单元：strategy signal 构造 → 含新字段 + source；v1 advisor label 用新字段
- 离线：`pytest -m "not live" --deselect tests/test_newsradar_global_intel.py --deselect tests/test_s032_refresh_loop.py --deselect "tests/test_s040_backfill.py::test_run_backtest_async_passes_kline_cache"`
- grep 验收：`historical_win_rate` backend 残留 = 0

## 9. 风险与回滚

- 风险：API key 改名 breaking 旧 consumer——已 fresh grep 确认无 MCP/frontend/active consumer。
- 回滚：字段 rename，git revert；dataclass 字段加 DEFAULT 不破坏旧构造（ positional arg 兼容）。
