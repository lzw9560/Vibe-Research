# Spec: S145 — §44 path-dependent winrate gate（SL/TP 模拟 + 路径胜率门）

> 状态：已实现（Tier 2）2026-09-03
> 作者：Claude  日期：2026-09-03
> 关联：S144（Tier 1 §44 测量地基修复，已 done f138db0/d31cdbf）、S066（§44 recompute-paradigm）、S031（strategy_backtest SL/TP 模型）；本 spec = S144 Tier 2

## 实现备注（2026-09-03）

- **R5 escape hatch（同 Tier 1 范式）**：is_win 仍用 o2c（不切 path verdict），path 单独双报（win_rate_path + path_lift）。理由同 Tier 1：切 is_win=is_win_path 会 mixed caliber（path-settled + 近期缺 path bars fallback o2c 混在一个 winrate）= §44 不可复现。verdict 切纯 path = Tier 3（需 s_settled 改 path-based + 全窗口 path 可得）。
- **path 重算结果（31 days / 627 picks path-settled）**：
  - win_rate_path = 34.93%（vs o2c 48.17%）——path 更低（止损摩擦，-3% 触发吃盈利）。
  - random_path（universe 默认 -3%/+8%/3）= 35.71%。
  - **path_lift = 0.978x（< 1，比随机还差）**——§44 真·gate 答案：breakout 在真实出场规则下不能交易（path_lift<1<2x）。
  - 3-date 子集曾显 1.426x（小样本不代表），全 31-day 才诚实：<1。
- **顺手修 pattern_scan.py:29 str-return 脆弱**（`resolve_data_dir() / "str"` → `Path(...) / "..."`）——S145 settle-task import 链触发的预存 bug。
- 全量测试中（deselect newsradar_global_intel/s032/s040 flaky）。
- **§44 verdict 强化**：endpoint（1.008x ~随机）→ path（0.978x <1 更差）。诚实不软化（A6）。


## 1. 问题 / 目标

Tier 1（S144）修了测量地基（unbuyable 排除 + T+1 口径双报），但 verdict 仍基于 **endpoint 收益**（o2c/o2nc = 买入→卖出端点），**未建模持仓路径**（止损/止盈/最大持仓触发）。memory `grill-reframe-final-verdict` 说的"path-dependent winrate 测试"是**唯一能回答"breakout 能不能交易"的 gate，从未跑过**。

Tier 1 R6 重算结果：lift 1.008x（<2x，未 validated，endpoint 口径）。path-dependent 口径下（考虑止损触发率 30.8%/whipsaw 16.8%，memory expert 数据），verdict 可能更差——止损频繁触发吃掉盈利。

**目标**：给 forward_test 加 SL/TP/max_hold 路径模拟，算 path-dependent winrate/lift，作为 §44 真·gate（回答"breakout 在真实出场规则下能不能盈利"）。**诚实预期**：path-verdict 比 endpoint 更差（止损摩擦），但这是"能不能交易"的真答案。

## 2. 背景

- `strategy_backtest._backtest_single`（S031，S144 Tier 1 已改 T+1）已有 SL/TP/max_hold 路径模拟逻辑（loop idx+2 起检查 stop/take/max_hold）。本 spec **抽取该逻辑为共享 helper**，复用到 forward_test（DRY）。
- forward_test 现状（Tier 1 后）：return_open2close（o2c）/ return_open2next_close（o2nc）/ is_unbuyable。endpoint 口径，无路径。
- §44 recompute-paradigm（memory s088）：重算用历史 kline + DB，不读结果 cache。本 spec 的 path 重算遵循。
- 路径胜率 = 模拟持仓（买 T+1 open，T+2 起检查 stop/take，max_hold 收盘或 stop/take 提前平）→ `is_win_path = (exit via take OR exit close > entry)`。

## 3. 需求清单

- [ ] R1 抽取 path-sim helper：`kline_returns.simulate_holding(bars, signal_date, stop_pct, take_profit_pct, max_hold_days) → {won, return_pct, exit_reason, exit_date} | None`。复用 _backtest_single 逻辑（T+1 buy + T+2 起检查 + max_hold exit）。strategy_backtest 改用此 helper（DRY）。
- [ ] R2 compute_returns_for_codes 扩展：算 path 收益（用 strategy params）→ dict 加 `return_path`/`is_win_path`/`exit_reason`。需 strategy_code → params 映射（caller 传 dict，或从 STRATEGY_REGISTRY 查）。
- [ ] R3 forward_test_records 加列 `return_path REAL` + `is_win_path INTEGER` + `exit_reason TEXT`（v1 CREATE + _ensure_column ALTER）。record_actual_returns 回填。get_forward_test_summary 加 path-winrate + path-lift 双报。
- [ ] R4 universe path-baseline：universe 无 strategy，用固定默认 SL/TP/max_hold（-3%/+8%/3，first_plate 常用值）算 path-winrate。path-lift = strategy path-winrate / universe path-winrate。诚实标注默认 params 选择 + 敏感性。
- [ ] R5 verdict 切 path-dependent：is_win 判定改用 is_win_path（path-dependent），escape hatch 的 o2c 退为"endpoint 基线"双报。§44 verdict 基于 path-lift（真·gate）。s_settled 改 path-based（WHERE return_path IS NOT NULL AND is_unbuyable=0）——避 mixed caliber（缺 path bars 的近期 picks 排除，非 fallback）。
- [ ] R6 修完重算：`tools/s145_recompute_path.py` 回填 path 列，对比 path-lift vs endpoint-lift（o2c/o2nc）三口径。

## 4. 受影响文件

| 文件 | 改动 |
|---|---|
| `backend/strategies/kline_returns.py` | R1：simulate_holding helper（抽取自 _backtest_single）；R2：compute_returns_for_codes 加 path 收益 |
| `backend/strategies/strategy_backtest.py` | R1：_backtest_single 改用 simulate_holding（DRY，行为不变） |
| `backend/strategies/forward_test.py` | R3：表加 path 列；record_actual_returns 回填；get_forward_test_summary path-winrate/lift 双报；R5：is_win 切 is_win_path + s_settled path-based |
| `backend/tools/s145_recompute_path.py`（新） | R6：回填 path 列 + 三口径 lift 对比 |
| `backend/tests/test_s145_path_winrate.py`（新）+ test_forward_test.py | R1-R6 测试 |

## 5. 设计方案

**path-sim 复用**（R1）：_backtest_single 的核心逻辑（idx+2 起检查、stop/take/max_hold）抽到 `simulate_holding`。strategy_backtest + forward_test 共用。bars 接口统一（dict 或 SimpleNamespace，用 getattr 兼容——strategy_backtest 用 SimpleNamespace，kline_returns 用 dict）。

**strategy params 映射**（R2）：compute_returns_for_codes 现 signal_date+codes。扩展接 `strategy_params_map: dict[code, dict]`（caller 传，{stop_pct, take_profit_pct, max_hold_days}）。每 code 用其 params 算 path。无映射的 code（universe）用默认 -3%/+8%/3。

**universe 默认 params**（R4）：universe 无 strategy。用 -3%/+8%/3（first_plate）作默认。理由：测"top-gene 选股 + 其战法出场 vs 全体涨停 + 固定出场"的 selection+exit edge。备选（不选）：每 universe code 用 match_strategies 命中战法 params——复杂 + universe 无明确命中，强制默认更诚实。标注 params 选择对 path-lift 的影响（可设 config 后调）。

**verdict 切 path + 避 mixed caliber**（R5）：s_settled = WHERE return_path IS NOT NULL AND is_unbuyable=0（path-based，近期 picks 缺 path bars 则排除——非 fallback，避 mixed caliber）。is_win = is_win_path。escape hatch 的 o2c 退双报基线（win_rate_o2c）。预期 path-verdict < endpoint-verdict（止损摩擦），但这是"能不能交易"的真答案。

**bars 可得性**：path-sim 需 T+1..T+max_hold bars。近期 picks（T+max_hold 未可得）→ return_path NULL → 排除出 path-verdict（honest，待 bars 全）。settle-lag = max_hold_days（比 o2c 的 1 天长）。

**不做的备选**：
- 不接 ATR trailing stop（position_advisor_v2._atr_trailing_stop 已存在，接线复杂；Tier 3）
- 不做 lift→仓位 gating（Tier 3，需 path-lift 先稳定）
- 不改选股逻辑（选股不变，只改 verdict 口径）
- 不做多 params 集 path-baseline（敏感性分析 Tier 3，本 spec 用固定默认）

## 6. 验收标准

- [ ] A1 simulate_holding 单测：构造 bars（T+2 hit stop / T+2 hit take / max_hold exit / T+1 buy-day stop 不触发）→ 正确 won/return_pct/exit_reason
- [ ] A2 forward_test_records 有 return_path + is_win_path + exit_reason 列（fresh DB CREATE + existing DB ALTER）
- [ ] A3 path-winrate + path-lift 双报（vs endpoint o2c/o2nc 三口径）
- [ ] A4 verdict 切 path（is_win=is_win_path + s_settled path-based）；o2c 退双报基线；近期缺 path bars 的 picks 排除（非 fallback，避 mixed caliber）
- [ ] A5 pytest 全绿（deselect newsradar_global_intel/s032/s040 flaky）
- [ ] A6 重算后 path-verdict 仍标"未 validated"（预期 path-lift <2x，止损摩擦使然，诚实不软化）

## 7. 合规与工程底线自查

- [x] 研究性（§44 raw-shadow，不投真金）
- [x] 判断可复现：path-sim 用历史 kline + 既定 SL/TP 规则可复算，禁臆造
- [x] 不涉及个股呈现 / 私有数据 / 新东财端点（baostock kline 本地）

## 8. 测试计划

- 单元：simulate_holding（stop/take/max_hold/T+1-skip 四种 exit）+ path-winrate/lift 计算
- 集成：record_actual_returns 回填 path + get_forward_test_summary 三口径双报
- 离线：`pytest -m "not live" --deselect tests/test_newsradar_global_intel.py --deselect tests/test_s032_refresh_loop.py --deselect "tests/test_s040_backfill.py::test_run_backtest_async_passes_kline_cache"`
- 重算：s145_recompute_path 回填 path + 三口径 lift 对比

## 9. 风险与回滚

- **风险**：path-verdict 比 endpoint 更差（止损摩擦）——预期（诚实），非风险
- **风险**：universe 默认 params（-3%/+8%/3）选择影响 path-lift——标注，可设 config 后调
- **风险**：path-sim 需 T+1..T+max_hold bars，近期 picks 缺 → path NULL，排除出 path-verdict（非 fallback，避 mixed caliber；verdict 窗口 lag max_hold 天）
- **回滚**：列加 DEFAULT NULL，向后兼容；is_win 切 path 若出问题可回退 endpoint（列保留）
