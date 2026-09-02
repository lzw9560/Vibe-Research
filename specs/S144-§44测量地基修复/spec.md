# Spec: S144 — §44 测量地基修复（unbuyable 检测 + T+1 建模）

> 状态：草案
> 作者：Claude（专家会诊落地）  日期：2026-09-02
> 关联：S066（§44 recompute-paradigm）、S071（premarket_selection）、S069（forward_test 8因子）；本 spec = 6 HARD item 专家会诊的 Tier 1

## 1. 问题 / 目标

**§44 verdict 建在腐蚀数据上**——6 HARD item 专家会诊（4 界专家 × 6 item + 总排）确认两条 §44 工程底线违规：

1. **unbuyable 污染**（unbuyable #1, critical）：`forward_test.py:212` `is_win = 1 if o2c>0 else 0` + `kline_returns.py:122` `o2c=(next_close-next_open)/next_open`。T-1 涨停股 T 日一字板（open=close=涨停价）→ o2c=0 → is_win=0 → 计为亏损。forward_test picks 是涨停叉候选（选续涨概率最强 = T 日最可能一字板的股）→ 策略胜率被人为压低；universe_returns（随机基准）含弱涨停股（o2c 可正）→ 基准胜率相对偏高。**非对称污染**：分子压低 / 分母抬高 → lift 0.986x 部分是测量假象。全仓 grep 确认零 unbuyable/is_buyable 检测逻辑。

2. **T+0 不可实现口径**（stop-loss/T+1 #2, high）：`strategy_backtest.py:99` `range(idx+1, ...)` 从入场日起允许止损/止盈触发 = T+0 出场；`forward_test.py:212` `is_win=o2c>0` 用 T 日 intraday（T+0）。A 股 T+1 不可当日卖。数据实算：T+0 胜率 54.38% 但 T-1close→T-close 胜率仅 40.55%/均值 -0.99%——§44 的"无 edge"结论本身基于不可实现口径。

**目标**：修复测量地基让 §44 verdict 有可信统计基础。**诚实底线前置声明**：即便全修完，§44 verdict 不变（无 trapped edge 藏在执行摩擦后）——T+1 只会更差（T+0→T+1 胜率降），buyable 子集未必有 edge。修复价值在"数据地基可信"+"诚实"，非盈利。

## 2. 背景

- §44 工程底线（CLAUDE.md §1.2）：判断须可复现、禁止臆造。当前 verdict 建在腐蚀数据上 = 直接违反。
- §44 recompute-paradigm（memory `s088-recompute-paradigm-not-result-cache`）：验证用历史输入快照 + DB 重算，不读结果 cache。本 spec 的重算遵循此范式。
- forward_test 数据流：`kline_returns.py:compute_returns_for_codes` 算 o2c/c2c → `forward_test.py:record_actual_returns` 落 `forward_test_records` → `get_forward_test_summary` 算 winrate/lift（vs `universe_returns`）。
- baostock kline 已有 OHLC + pctChg，**无需新数据源**。
- Tier 0（诚实标签层，4a9c714 已 commit）已清谬论 + stale 数字，本 spec 是 Tier 1（测量逻辑修复）。

## 3. 需求清单

- [ ] R1 unbuyable 检测：`kline_returns.py:compute_returns_for_codes` 算 o2c 后加一字板检测——next_bar 满足 open≈close≈high≈low（容差 0.01）且 pctChg≈涨停幅度（`abs(pctChg)>=9.8%` 粗判覆盖 10%/20%/30% 板块）→ 返回 dict 加 `is_unbuyable=True`
- [ ] R2 forward_test 排除 unbuyable：`forward_test_records` 表加列 `is_unbuyable INTEGER DEFAULT 0`（v1 迁移完整 CREATE + `__init__` 接线，参照 `migration-stubs-fresh-db-fix`）；`record_actual_returns` 收到 is_unbuyable=True 时 `is_win=NULL`（排除而非 0）+ 写 `is_unbuyable=1`；`get_forward_test_summary` 的 s_settled/s_wins 查询加 `WHERE is_unbuyable=0`（buyable-only 样本）
- [ ] R3 universe_returns 同理排除：随机基准也剔 unbuyable（消分母偏高）
- [ ] R4 T+1 建模——backtest：`strategy_backtest.py:99` `range(idx+1, ...)` → `range(idx+2, ...)`（T+1 起才能卖，A 股 T+1 规则）
- [ ] R5 T+1 建模——forward_test：`forward_test_records` 加列 `return_open2next_close REAL`（T-open → T+1-close，可实现口径）；`record_actual_returns` 回填时拉 T+1 close 算此值；`get_forward_test_summary` 双报 o2c（当前诚实基线）+ open2next_close（T+1 可实现），`is_win` 判定改用 open2next_close（或并列标注，不改原 is_win 兼容旧数据）
- [ ] R6 修完重算 lift：对比 tradeable 口径（buyable-only + T+1）vs 原口径的 lift 变化，落 `factor_significance.json` 或 stdout 摘要

## 4. 受影响文件

| 文件 | 改动 |
|---|---|
| `backend/tools/kline_returns.py` | R1：compute_returns_for_codes 加 is_unbuyable 检测 |
| `backend/forward_test.py` | R2/R5：表加 is_unbuyable + return_open2next_close 列；record_actual_returns 回填；get_forward_test_summary 双报 + WHERE 过滤 |
| `backend/db_health.py` 或迁移桩 | R2：forward_test_records v1 迁移完整 CREATE（is_unbuyable + return_open2next_close 列）+ __init__ 接线 |
| `backend/strategies/strategy_backtest.py` | R4：:99 range(idx+2) T+1 起检查止损止盈 |
| `backend/tests/test_forward_test.py` | R1-R5 测试：一字板→is_unbuyable=True + 排除；T+1 open2next_close 计算 |
| `backend/tools/factor_regression.py`（可选） | R6：重算后 port day-cluster bootstrap 到生产路径（memory `factor_regression.py:257`） |

## 5. 设计方案

**unbuyable 检测口径**（R1）：一字板 = 次日 open≈close≈high≈low（全等 = 无日内波动，封死）+ pctChg≈涨停幅度。容差 0.01（价格单位）+ `abs(pctChg)>=9.8%`（覆盖主板 10%/创业板科创板 20%/北交所 30%）。不用精确涨停幅度（需查板块属性，YAGNI）——9.8% 阈值粗判足够（误判极少：非涨停股 pctChg<9.8%，一字板必≥9.8%）。

**排除而非计 0**（R2）：is_unbuyable=True 时 `is_win=NULL`（SQL NULL，排除出 settled 分母）非 `is_win=0`（计为亏损）。关键：排除是**双向的**——策略 picks（分子）+ universe（分母）都剔 unbuyable。否则只剔分子会更压低 lift（分母仍含弱涨停股 o2c 可正）。

**T+1 范围修正**（R4）：`range(idx+1, min(idx+1+max_hold, len))` → `range(idx+2, min(idx+2+max_hold, len))`。idx=入场日（T），idx+1=T+1（次日，A 股 T+1 可卖首日）。原 `idx+1` = T 日当日 = 不可卖。改 `idx+2` 确保 T+1 起检查。

**双报口径**（R5）：不删 o2c（保留诚实基线 + 兼容旧数据），加 open2next_close 列并列。`is_win` 改用 open2next_close（T+1 可实现）。§44 verdict 基于哪个明示（get_forward_test_summary 返回字段标注）。

**不做的备选**：
- 不改选股逻辑（选未涨停=breakout 已证伪 lift 1.36x；改盘中打板=架构级替换无 edge 支撑）
- 不加 SL/TP/max_hold 模拟到 forward_test（Tier 2，依赖本 spec 先修 T+1）
- 不接 day-cluster bootstrap 到生产（Tier 2，本 spec 只 naive 重算 + 标注）

## 6. 验收标准

- [ ] A1 一字板样本（构造 fixture：open=close=high=low+涨停）→ is_unbuyable=True
- [ ] A2 forward_test_records 表有 is_unbuyable + return_open2next_close 列（fresh DB 迁移完整，参照 `migration-stubs-fresh-db-fix`）
- [ ] A3 buyable-only 口径 lift vs 原口径 lift 双报（预期 buyable-only lift 与原口径有差异，方向非预设——修完才知）
- [ ] A4 T+1 open2next_close 胜率 vs T+0 o2c 胜率双报（预期 T+1 更低，参照专家实算 T+0 54.38% vs T-1close→T-close 40.55%）
- [ ] A5 `pytest -m "not live" --deselect` 全绿（deselect newsradar/s032/s040 flaky，参照 memory）
- [ ] A6 重算后 §44 verdict 仍标"未 validated"（预期 <2x，诚实不软化）

## 7. 合规与工程底线自查

- [x] 研判属研究性（§44 raw-shadow stance，不投真金，honest_label 在位）
- [x] 判断可复现：本 spec 修复的正是"可复现"——unbuyable 检测 + T+1 口径让 verdict 有可信统计基础；重算用历史输入 + DB（§44 recompute-paradigm），禁臆造/心算
- [x] 涨停四池个股属公开榜单（本 spec 不涉及个股呈现）
- [x] 用户私有数据未进 git（forward_test_records 在 .vibe-research/gene_scores.db，已 .gitignore）
- [x] 无新东财端点（baostock kline 本地缓存）

## 8. 测试计划

- 单元：`test_forward_test.py` 加一字板 fixture + is_unbuyable 排除 + open2next_close 计算
- 集成：`forward_test.py` record_actual_returns 回填 + get_forward_test_summary 双报
- 离线：`pytest -m "not live" --deselect test_fetch_global_intel_wm_import_fails --deselect test_s032_refresh_loop --deselect "test_s040_backfill::test_run_backtest_async_passes_kline_cache"`（参照 memory flaky 集）
- 重算：跑 `forward_test` 重算 + `kline_returns` 重算，对比 lift 双口径

## 9. 风险与回滚

- **风险**：T+1 修正后 lift 变更差（T+0→T+1 胜率降），§44 verdict 更硬——这是预期（诚实），非风险
- **风险**：buyable-only 子集样本量缩（一字板占比可能 20-30%），n 降 → CI 变宽。若 n<30 天则 §44 标"样本不足待 60 日复验"
- **回滚**：列加 DEFAULT 0/NULL，向后兼容；is_win 改用 open2next_close 若出问题可临时回退用 o2c（列保留）
- **不修的依赖项**：auction_screener.py:303 一字板满分 100（评分倒挂，Tier 2/3）、strategy_base.py:334 臆造 winrate 接 win_rate_tracker（Tier 2）、forward_test 生产路径 day-cluster bootstrap（Tier 2）
