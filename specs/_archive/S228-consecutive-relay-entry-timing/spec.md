# Spec: S228 — consecutive_relay entry 时机 fix（D close→D+1 open 改 D+1 close→D+2 open）

> 状态：**已废弃（2026-09-24）——战法证否，fix 不再需要**
> 作者：claude  日期：2026-09-23
> 关联：S218（投研参考交付系统，daily_report 时机设计）、S211（consecutive_relay arm wire）、S207（§44 成本单位 100x blocker）、S217（chrono holdout stage-1）、[[consecutive-relay-stage-2-definitive-2026-09-20]]（×1.0 终判）
>
> **废弃原因**：S228 grill workflow（4 视角 refute-default）+ offline 量化（s203_harness_v2.py 561 days chrono）揭示 V2 真 edge = -1.66% 负 + p=1.0 + adequate power → consecutive_relay 战法 definitive falsify。fix entry 时机无意义——战法本身证否。见 [[consecutive-relay-falsified-2026-09-23]] + [[v1-fake-edge-retrospective-2026-09-24]]。当前 +1.04% verdict 是"D 涨停封板溢价"非"连板接力 edge"，已 archive（arm kill switch + evaluation.py regime_caps ×0）。

## 1. 问题 / 目标

daily_report cron 14:50（收盘前 7 分钟）fire 推的 15 可做 report，用户 09-23 19:52 看 report 发现"今天不能做"——entry 时机错位：

- report 是 "2026-09-22 信号报告"（date=prev_trade_day=昨天）
- entry_price = 09-22 close（昨天收盘价）——昨天 15:00 早过了 24 小时
- backtest `_process_consecutive_relay` 测的 edge +1.04% 是"09-22 close 买 → 09-23 open 卖"——entry 昨天，exit 今天开盘，fire 时（14:50）exit 都过了 5 小时
- 入场指引"今日 14:57-15:00 买"的"今日"=09-22（report title）——昨天

**S218 spec line 15+22 明确设计**：T 日 14:50 生成 + 用户 **T 日 14:57-15:00 收盘集合竞价买**（entry=today close）；参考价=prev_day close（today close 14:50 没出来用昨天作参考，非成交价）。**当前代码违背 spec**——entry=prev_day close（回顾），不是 today close（前瞻）。

**目标**：entry 时机对齐 spec——scan prev_day 连板股 + entry today close + exit tomorrow open，daily_report 14:50 fire 推真正"今天 14:57-15:00 买"的前瞻信号。

## 2. 背景

### 战法逻辑（S211 consecutive_relay arm）

- **signal_date** = scan 日期 = prev_trade_day（lbc≥2 连板股已收盘已定，zt_history 离线读）
- **entry_date** = signal_date + 1 = today（fire 当天）
- **entry_price** = today close（14:57-15:00 集合竞价产生；fire 14:50 时没出来，用 signal_date close 作参考价）
- **exit** = tomorrow open（signal_date + 2 open）
- **edge** = (tomorrow open - today close) / today close = overnight gap（today→tomorrow）

### 当前 bug 代码

| 位置 | 当前（bug） | spec（正确） |
|---|---|---|
| `signals.py:75` `run_date = prev_trading_date_str()` | run_date=prev_day | run_date=today（entry_date） |
| `signal_report.py:312` `scan(target_date, previous_trade_day=target_date)` | scan + entry 都用 target_date | scan previous_trade_day=prev_day, entry_date=today 分离 |
| `signal_report.py:367` `ref_price = _get_reference_price(code, target_date=prev_day)` | entry_price=prev_day close | ref_price=prev_day close（参考），entry_price=today close（成交时补） |
| `signal_report.py:419` `"date": target_date`（=prev_day） | date=prev_day | date=today（entry_date） |
| `journal_recorder.py:460` `close_d = bars[d_idx]`（d_idx=signal_date） | entry=signal_date close | entry=signal_date+1 close |
| `journal_recorder.py:478` `entry_date=target_date`（=signal_date） | entry_date=signal_date | entry_date=signal_date+1 |
| `journal_recorder.py:506` `_resolve_gap_exit(bars, d_idx)` → open[signal_date+1] | exit=signal_date+1 open | exit=signal_date+2 open |

### 根因（git 历史）

- **96d9c3e** (S218 C1) 定 cron 14:50（收盘前 7 分钟）——intent 前瞻（推 today 14:57-15:00 买信号）
- **89e6768** (P0-3, 2026-09-20) 加 `run_date=prev_trading_date_str()`——为解"盘前 fire today cache 没数据"（regime=unknown + scan today 连板股没定）。注释写"盘前 04:01 cron 用昨天"——但 cron 早是 14:50。**借用 04:01 盘前场景的 run_date=prev_day 到 14:50**，副作用：entry 跟着 run_date 跑到 prev_day（回顾）。
- 当前代码把"参考价"（prev_day close，fire 时 today close 没出来）和"成交价"（today close，14:57-15:00 集合竞价产生）混了，entry_date 跟着 run_date=prev_day 跑到昨天。

### 数据现状

- trade_journal consecutive_relay 记录：49 条（entry_date 09-18~09-22，最近 5 天 paper 闭环）
- verdict（+1.04% p=0.0054）硬编码在 `evaluation.py:94`（冻结 registry），源自 S217 chrono holdout 561 days 跑出
- chrono holdout script：`backend/tools/s203_consecutive_relay_harness.py`

## 3. 需求清单

- [ ] R1：`daily_report` `run_date=today`（entry_date）+ `signal_date=prev_trading_date`（scan 日期分离）
- [ ] R2：`get_consecutive_relay_signals` 分离 `entry_date` + `signal_date` 参数——scan previous_trade_day=signal_date, regime=entry_date, ref_price=signal_date close, return date=entry_date
- [ ] R3：`_process_consecutive_relay` entry/exit 后移一天——d_idx=signal_date bar, entry_idx=d_idx+1, entry_price=bars[entry_idx].close, entry_date=bars[entry_idx].date, exit=_resolve_gap_exit(bars, entry_idx)（signal_date+2 open）
- [ ] R4：`_process_consecutive_relay` unbuyable filter 改判 entry_idx bar（D+1 一字板，entry day 买不到）而非 d_idx bar（D 日一字板）
- [ ] R5：render `signal_report.py:563` "今日 14:57-15:00" 明确 today 日期（用 entry_date 插值）
- [ ] R6：`routers/signals.py:169,175` API + `signals.py:287,454,624` keypoint_notify run_date=today
- [ ] R7：backtest 重跑——`s203_consecutive_relay_harness.py` 用新 _process_consecutive_relay 跑 chrono holdout 561 days 生成新 verdict
- [ ] R8：`evaluation.py:94` verdict 数字更新（新 edge + p + n_test）
- [ ] R9：trade_journal 49 条 consecutive_relay 记录重算（entry/exit 后移）

## 4. 受影响文件

| 文件 | 改动 |
|---|---|
| `backend/scheduler/executors/signals.py` | daily_report + keypoint_notify run_date=today, signal_date 分离传参 |
| `backend/tools/signal_report.py` | get_consecutive_relay_signals 分离 entry_date + signal_date, render "今日"=entry_date |
| `backend/strategies/journal_recorder.py` | _process_consecutive_relay entry/exit 后移一天 + unbuyable 改判 entry_idx |
| `backend/routers/signals.py` | API /signals/status run_date=today |
| `backend/candidate_funnel/evaluation.py` | verdict 数字更新（R7 重跑后） |
| `backend/tools/s203_consecutive_relay_harness.py` | 重跑 chrono holdout（可能需适配新 entry/exit） |
| `.vibe-research/trade_journal.db` | 49 条 consecutive_relay 记录重算 |

## 5. 设计方案

### 分离 signal_date + entry_date（核心）

当前 `target_date` 一个参数既当 scan 日期又当 entry 日期——混淆。fix 分离：
- `signal_date` = scan 日期 = prev_trade_day（lbc≥2 连板股已定）
- `entry_date` = entry 日期 = today（fire 当天，14:57-15:00 集合竞价买）

### daily_report（前瞻信号）

```python
# signals.py daily_report
run_date = payload.get("run_date") or datetime.now().strftime("%Y-%m-%d")  # today=entry_date
signal_date = payload.get("signal_date") or prev_trading_date_str()  # prev_day=scan 日期
signals = get_consecutive_relay_signals(entry_date=run_date, signal_date=signal_date)
```

### get_consecutive_relay_signals

```python
def get_consecutive_relay_signals(entry_date: str, signal_date: str) -> dict:
    raw_signals = scan_consecutive_relay(signal_date, previous_trade_day=signal_date)  # scan prev_day 连板股
    current_regime = regime_map.get(entry_date, None)  # today 的 regime
    ref_price, price_source = _get_reference_price(code, signal_date)  # prev_day close 参考价
    # unbuyable: 用 signal_date bar 判（保守估计，prev_day 一字板 → today 大概率一字板；today bar 14:50 没出来）
    return {"date": entry_date, ...}  # date=today
```

### _process_consecutive_relay（backtest）

```python
def _process_consecutive_relay(self, target_date: str) -> dict:  # target_date=signal_date
    candidates = scan_consecutive_relay(target_date, previous_trade_day=target_date)
    for cand in candidates:
        bars = self._bars_provider(code)
        d_idx = bars 找 signal_date bar  # D=连板日
        entry_idx = d_idx + 1  # D+1=entry day
        close_entry = bars[entry_idx].close  # D+1 close
        # unbuyable: 判 entry_idx bar（D+1 一字板，entry day 买不到）
        if _is_unbuyable_next_bar(bars[entry_idx], code=code): → unbuyable
        exit_price, exit_date, info = self._resolve_gap_exit(bars, entry_idx)  # D+2 open
        # edge = (exit_price - close_entry) / close_entry = (D+2 open - D+1 close) / D+1 close
```

### unbuyable 时机差异（daily_report vs backtest）

- **daily_report 14:50**：today bar 没出来（15:00 收盘）→ 用 signal_date=prev_day bar 判（保守估计：prev_day 一字板 → today 大概率一字板买不到）
- **backtest**：历史数据 D+1 bar 已有 → 判 entry_idx=D+1 bar 一字板（实际）
- 两者保守度不同——daily_report 保守估计可能多过滤（prev_day 一字板但 today 打开的 picks 被误判 unbuyable）。**接受这个差异**——daily_report 是前瞻保守，backtest 是历史实际，edge 测的是 backtest 口径。

### 备选方案（不选）

- **A. 只改 daily_report 不动 backtest**：daily_report 推 today close 买，backtest 测 prev_day close 买——edge 不一致，+1.04% 是错战法。**不选**（edge 时机不匹配）。
- **B. 改 cron 到 15:05 盘后**：盘后 fire 推 today close 信号——但 today close 15:00 才出来，entry 14:57-15:00 集合竞价已过。盘后 fire 推的是"今天已买的回顾"不是"今天买"信号。**不选**（违背 spec 前瞻设计）。
- **C. intraday lbc≥2 检测**（spec line 33）：14:50 时 today 涨停池 live 查 today 连板股——但需 em_get 实时数据 + intraday 检测复杂。**defer**（spec 说先做 EOD/offline 简化，intraday 是后续）。

## 6. 验收标准

- [ ] A1：daily_report 14:50 cron fire 推的 report date=today（fire 当天），entry_price 标 today close（参考价 prev_day close），"今日"=today 明确
- [ ] A2：`_process_consecutive_relay` entry=bars[signal_date+1].close, exit=open[signal_date+2]，edge=(D+2 open - D+1 close) / D+1 close
- [ ] A3：chrono holdout 561 days 重跑——新 verdict 数字（edge + p + n_test），evaluation.py 更新
- [ ] A4：trade_journal 49 条 consecutive_relay 记录重算（entry/exit 后移一天）
- [ ] A5：full suite pytest -m "not live" 0 failed
- [ ] A6：grill workflow ≥6 视角对抗审通过（方法论变更必起）

## 7. 合规与工程底线自查（逐条确认）

- [x] 研判/推荐/买卖时机属系统能力（2026-07-30 新口径）——daily_report 推今天买信号，用户最终决策
- [x] 判断可复现——edge 重跑 chrono holdout 561 days（`s203_consecutive_relay_harness.py`），禁臆造/心算，verdict 数字从重跑出
- [x] 涨停四池/连板股榜个股属公开榜单——consecutive_relay 连板股 code/name 公开
- [x] 用户私有数据未进 git——trade_journal.db 在 .vibe-research/（gitignored）
- [x] 新增东财端点走 em_get——本 fix 不新增东财端点（offline scan zt_history + kline cache）

## 8. 测试计划

- `pytest -m "not live"` full suite（0 failed）
- chrono holdout 重跑：`cd backend && .venv/bin/python tools/s203_consecutive_relay_harness.py`（561 days，几小时）
- daily_report manual trigger：`POST /api/scheduled-tasks/44/run` 验 report date=today + entry_price=today close
- 手动验收：明天 09-24 14:50 cron fire，report 应 date=09-24（today）+ entry 09-24 close

## 9. 风险与回滚

### 风险

- **R-1（高）**：fix 后 edge 可能消失或变负——当前 +1.04% 测"D close→D+1 open"，fix 后测"D+1 close→D+2 open"。连板股 D+1 可能继续涨停（一字板买不到），unbuyable filter 过滤后样本变 + edge 变。**若 edge 消失 → consecutive_relay 战法证否**（当前 +1.04% 是错战法测出来的）。
- **R-2（中）**：unbuyable 时机差异（daily_report 保守判 prev_day 一字板 vs backtest 实际判 D+1 一字板）——daily_report 可能多过滤 picks（prev_day 一字板但 today 打开的被误判）。接受——daily_report 前瞻保守。
- **R-3（中）**：backtest 重跑几小时——chrono holdout 561 days。
- **R-4（低）**：verdict 数字更新后 cap 可能变——若新 edge < 旧 edge，cap 可能降（×1.0→×0.75）。

### 回滚

- git revert fix commit + evaluation.py verdict 回滚旧数字
- trade_journal.db 49 条记录可重算回滚（entry/exit 回 D close→D+1 open）

## 10. grill 验证（方法论变更必起）

按 CLAUDE.md §1.3 + 自动复盘 2026-09-05，涉及统计方法论/edge 定义变更的 spec 必起 ≥6 视角 adversarial verify workflow。本 spec 改 edge 定义（D close→D+1 open 改 D+1 close→D+2 open）——**必起 grill workflow** 验证：
1. fix 方案对不对（entry/exit 时机是否 spec 本意）
2. backtest 重跑风险（edge 消失概率）
3. unbuyable 时机差异合理性
4. daily_report 14:50 fire today close 没出来的处理（参考价 vs 成交价分离）
5. verdict 重跑 + evaluation.py 更新流程
6. 回滚预案
