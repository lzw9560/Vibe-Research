# Spec: S229 — §44 v3 anti-fake-edge（entry/exit 可交易性 + 窗口语义 + realizability 双向 + momentum 过滤审）

> 状态：草案
> 作者：claude  日期：2026-09-24
> 关联：S159（§44 v2 应用规约）、S228（consecutive_relay entry 时机 fix——废弃，V2 证否）、[[v1-fake-edge-retrospective-2026-09-24]]（复盘根因）、[[consecutive-relay-falsified-2026-09-23]]（V1 假 edge 证否）

## 1. 问题 / 目标

consecutive_relay V1 +1.04% 假 edge 被 S217 chrono holdout 561 days + ×1.0 unlock 验证通过，但 V2 offline 量化揭示是"D 涨停封板溢价"非"连板接力 edge"——**§44 v2 验证没抓到 V1 假 edge**。

**根因 4 条**（见 [[v1-fake-edge-retrospective-2026-09-24]]）：
1. entry=D close=涨停价（涨停封板溢价效应）——§44 没审 entry 价格语义
2. exit=D+1 open over-credit D+1 一字涨停（卖不掉）——realizability-bias 单向（只修跌停）
3. §44 v2 窗口 sanity 没审 entry/exit 可交易性 + 窗口语义（edge 是什么效应）
4. V2 过滤 D+1 一字板揭真 edge -1.66%——filter 掉的 momentum picks 是 V1 假 edge 主要贡献者

**目标**：§44 v3 改进 4 方向——防未来新 edge 验证再犯 V1 类假 edge。

## 2. 背景

§44 v2（S159）保留方法论改 5 件事（前置窗口 sanity / 重方法论只在对窗口 / §44 不每阶段参与 / 回溯模块主场 / Bonferroni 按 n 调）。但 v2 "窗口 sanity"只审窗口时机（gap vs path），没审：
- entry/exit 价格语义（涨停价 vs 市场价）
- entry/exit 可交易性（一字涨停/跌停 filter 双向）
- filter 掉的 picks 对 edge 贡献（momentum 过滤审）

consecutive_relay V1 假 edge 正是这些没审的漏网。

## 3. 需求清单

- [ ] R1：entry/exit 可交易性审——§44 verifier 加 check：entry close 是涨停价？exit open 是涨停价？一字涨停/跌停 filter 双向
- [ ] R2：窗口语义审——§44 verifier 加 edge 语义标注：涨停封板溢价 / 连板接力 / 隔夜 gap（基于 entry/exit 价格语义）
- [ ] R3：realizability-bias 双向——_resolve_gap_exit 加 D+1 一字涨停 filter（卖不掉），不只 D+1 一字跌停（买不回）
- [ ] R4：momentum picks 过滤审——§44 verifier 加 filter 前后 edge 对比：filter 掉的 picks 贡献多少 edge？若 filter 掉的 picks 贡献大部分 edge → 标"edge 是 filter 效应非剩余 picks edge"
- [ ] R5：§44 spec 模板加 v3 sanity 步骤——`specs/_template.md` §44 自查栏加 entry/exit 可交易性 + 窗口语义 + momentum 过滤审

## 4. 受影响文件

| 文件 | 改动 |
|---|---|
| `backend/s44_verifier/verifier.py` | R1+R2+R4：加 entry/exit 可交易性 check + 窗口语义标注 + filter 前后 edge 对比 |
| `backend/strategies/journal_recorder.py` | R3：_resolve_gap_exit 加 D+1 一字涨停 filter（双向 realizability） |
| `backend/engine/bar_utils.py` | R3：is_onesell_locked_next_bar 加 is_onebuy_locked_next_bar（一字涨停卖不掉） |
| `specs/_template.md` | R5：§44 自查栏加 v3 sanity 步骤 |
| `backend/candidate_funnel/evaluation.py` | R2：verdict note 加窗口语义标注 |

## 5. 设计方案

### R1：entry/exit 可交易性审（核心）

§44 verifier 加 `check_entry_exit_tradability(returns, bars, picks)`：
- entry close 是涨停价？→ 标"涨停封板溢价窗口"警告
- exit open 是涨停价（一字涨停）？→ filter 或标 over-credit
- entry/exit 价格是市场价还是封板价？

### R2：窗口语义审

§44 verifier 加 `classify_edge_semantic(entry_price, exit_price, bars)`：
- 涨停封板溢价（entry=涨停价 close, exit=次日 open）
- 连板接力（entry=次日 close, exit=后日 open）
- 隔夜 gap（entry=市场价 close, exit=次日 open）
- verdict note 标窗口语义

### R3：realizability-bias 双向

`_resolve_gap_exit` 当前只 filter D+1 一字跌停（is_onesell_locked_next_bar）。加 D+1 一字涨停 filter（is_onebuy_locked_next_bar——一字涨停 open 卖不掉）。

### R4：momentum picks 过滤审

§44 verifier 加 `compare_filtered_vs_unfiltered_edge(obs, filter_fn)`：
- filter 前后 edge 对比
- filter 掉的 picks 贡献多少 edge？
- 若 filter 掉的 picks 贡献大部分 edge → 标"edge 是 filter 效应非剩余 picks edge"（V2 过滤 D+1 一字板后 edge +1.04%→-1.66% 即此例）

### R5：spec 模板 v3 sanity

`specs/_template.md` §44 自查栏加：
- entry/exit 可交易性审（涨停价？一字板 filter 双向？）
- 窗口语义审（edge 是什么效应？）
- momentum 过滤审（filter 掉的 picks 贡献？）

## 6. 验收标准

- [ ] A1：§44 verifier 加 entry/exit 可交易性 check + 窗口语义标注
- [ ] A2：_resolve_gap_exit 加 D+1 一字涨停 filter（双向 realizability）
- [ ] A3：§44 verifier 加 filter 前后 edge 对比（momentum 过滤审）
- [ ] A4：specs/_template.md §44 自查栏加 v3 sanity 步骤
- [ ] A5：用 v3 改进重审 consecutive_relay V1——验证 v3 能抓到 V1 假 edge（回归测试）
- [ ] A6：full suite pytest -m "not live" 0 failed
- [ ] A7：grill workflow ≥4 视角对抗审通过（方法论变更必起）

## 7. 合规与工程底线自查

- [x] 判断可复现——§44 verifier 改进是方法论层面，verifier 代码可复算
- [x] 不臆造——v3 改进基于 V1 假 edge 根因实证（consecutive_relay 证否）
- [x] 私有数据隔离——不涉私有数据
- [x] 防封——不涉 em_get

## 8. 测试计划

- `pytest -m "not live"` full suite（0 failed）
- 用 v3 改进重审 consecutive_relay V1——验证 v3 抓到 V1 假 edge（回归测试）
- grill workflow ≥4 视角对抗审

## 9. 风险与回滚

- R-1（中）：v3 改进可能过度过滤——entry/exit 可交易性审可能 filter 掉合理 picks（如 entry 市场价 close 非涨停价）。需审 filter 阈值。
- R-2（低）：_resolve_gap_exit 双向 filter 可能改其他 arm verdict——需审爆炸半径。
- 回滚：git revert + verifier.py 回旧逻辑。

## 10. grill 验证（方法论变更必起）

按 CLAUDE.md §1.3 + 自动复盘 2026-09-05，§44 方法论变更必起 ≥6 视角 adversarial verify workflow。本 spec 改 §44 verifier + _resolve_gap_exit——**必起 grill workflow** 验证：
1. v3 改进 4 方向是否正确（防 V1 假 edge 根因）
2. entry/exit 可交易性审 阈值（涨停价判定？）
3. realizability-bias 双向 是否改其他 arm verdict
4. momentum 过滤审 是否过度 filter
5. spec 模板 v3 sanity 步骤是否落地
6. 回归测试（v3 抓 V1 假 edge）
