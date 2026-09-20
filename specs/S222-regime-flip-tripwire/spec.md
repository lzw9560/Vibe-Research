# Spec: S222 — regime-flip tripwire + hysteresis（等 bull 通知器）

> 状态：草案
> 作者：Claude（architect persona + grill synthesis） 日期：2026-09-20
> 关联：milestone-2026-09-18-pivot（最高杠杆=consecutive_relay live 验证）、S218 daily_report executor、memory `deep-think-synthesis-2026-09-20`

## 1. 问题 / 目标

consecutive_relay stage-2 ×1.0 definitive（edge 真 + adequate power），但 **live 0 tradable picks**（regime=range 非 bull，等 bull 回来自动出 tradable）。用户在等 bull——但系统**无 regime-flip 通知器**：

- bull 回来时用户不知道，错过照做 4 周真 P&L 窗口
- raw regime 数据（index_ma20_regime.json strong/weak）5497/5498 天翻转——**几乎天天翻**，直接 alert 会天天误报
- grill agent 戳破：raw 天天翻→必须加 hysteresis（N 天连续新 regime 才 alert），且不做 sticky bar（当前永远"0 可交易"是心理打击）→ 改 notification

**目标**：加 `regime_flip_notify` executor + hysteresis（3 天连续 bull 才 alert），bull 回来时飞书通知用户"regime→bull，N 个可做信号，记录成交以闭合真钱反馈"。

## 2. 背景

- `compute_regime_labels`（`tools/gap_regime_stratified.py`）返 bull/bear/range 3-way 历史（基于 close vs MA20 + MA20 slope），比 raw strong/weak 稳定
- `daily_report` executor（`scheduler/executors/signals.py:59`）已调 `get_consecutive_relay_signals` 得当日 regime
- `_send_text_notification`（`signals.py:111`）已封装飞书推送（未设 webhook 时 no-op + log）
- `scheduler/seed.py` 注册 cron（6 种内置任务，加新 task_type 在 `_executors` 加方法）

**freeze 例外判断**：milestone pivot "冻结新 spec/基建"——但 tripwire 是 consecutive_relay live 验证（milestone 最高杠杆）的 delivery 闭环支撑，非"加因子/战法/新基建"。用户确认算 freeze 例外（可做）。

## 3. 需求清单

- [ ] R1 `regime_flip_notify` executor：diff `compute_regime_labels()` 当日 vs 前 N 天 regime，连续 3 天 bull 才触发 alert
- [ ] R2 hysteresis：3 天连续 bull（非单日翻）才 alert；单日翻回 range/bear 不 alert；非 bull regime 不 alert
- [ ] R3 飞书通知内容：`regime→bull（连续 3 天），N 个可做信号，记录成交以闭合真钱反馈` + 当日 cap + edge 状态（复用 daily_report 的 regime/cap 数据）
- [ ] R4 cron seed：盘前 `10 9 * * 0-4`（9:10 检测，daily_report 04:01 之后、开盘前）
- [ ] R5 复用 `_send_text_notification`（不新造推送通道）；未设 webhook 时 no-op + log（诚实不臆造送达）
- [ ] R6 不做 sticky bar（grill 反对——当前永远"0 可交易"心理打击）；只 flip→bull 时弹 notification
- [ ] R7 幂等：同一天多次 fire 不重复 alert（用 fire_receipt 或当日已 alert flag）

## 4. 受影响文件

| 文件 | 改动 |
|---|---|
| `backend/scheduler/executors/signals.py` | 加 `regime_flip_notify(payload)` executor + `_check_regime_hysteresis(target_date, days=3)` helper |
| `backend/scheduler/seed.py` | 加 `regime_flip_notify` task_type seed（cron `10 9 * * 0-4`）+ `_executors` 注册 |
| `backend/tests/test_s222_regime_flip.py` | 新建：3 天连续 bull→alert / 单日翻→不 alert / range→不 alert |

## 5. 设计方案

### hysteresis 逻辑
```
def _check_regime_hysteresis(target_date: str, days: int = 3) -> str | None:
    """连续 N 天同 regime 才返 regime，否则 None（未稳定）。
    用 compute_regime_labels 的历史 regime 序列，取 target_date 及前 days-1 天，
    全相同才返该 regime，否则 None。
    """
    regimes = compute_regime_labels(...).regime_history  # 取最近 N 天
    if len(regimes) < days: return None  # 数据不够
    last_days = regimes[-days:]
    if all(r == last_days[0] for r in last_days):
        return last_days[0]  # 稳定 regime
    return None  # 未稳定
```

### executor
```
def regime_flip_notify(payload: dict) -> dict:
    target_date = payload.get("run_date") or prev_trading_date_str()
    stable_regime = _check_regime_hysteresis(target_date, days=3)
    if stable_regime != "bull":
        return {"skipped": f"regime={stable_regime or 'unstable'}, no bull alert"}
    # 连续 3 天 bull → 查当日可做信号数 + 通知
    signals = get_consecutive_relay_signals(target_date)
    tradable_n = len(signals.get("tradable", []))
    cap = signals.get("cap", {}).get("effective")
    text = f"regime→bull（连续 3 天），{tradable_n} 个可做信号，cap=×{cap}，记录成交以闭合真钱反馈"
    _send_text_notification(text)
    return {"alerted": "bull", "tradable": tradable_n, "cap": cap}
```

### 备选方案为何不选
- **sticky RegimeCapEdgeBar**：不选，grill 反对——当前 regime=range 永远显示"0 可交易"是心理打击，非有用信息
- **raw regime 直接 alert**：不选，raw 5497/5498 天翻→天天误报
- **每日 log regime 状态**：不选，用户不看 log，要 push 通知

## 6. 验收标准

- [ ] A1 3 天连续 bull → alert + 飞书推送（或 no-op log 若 webhook 未设）
- [ ] A2 单日 bull 后翻回 range → 不 alert
- [ ] A3 regime=range/bear → 不 alert
- [ ] A4 数据不够（<3 天历史）→ 不 alert + log "数据不够"
- [ ] A5 同一天多次 fire → 只 alert 一次（幂等）
- [ ] A6 `pytest tests/test_s222_regime_flip.py` green
- [ ] A7 full suite 0 failed

## 7. 合规与工程底线自查

- [x] 不臆造：regime 来自 compute_regime_labels（公开数据 + 既定规则可复算）
- [x] 私有数据隔离：只读 regime 历史 + 信号数，不碰 manual_trades/持仓
- [x] 防封：复用 `_send_text_notification`（飞书 webhook，非东财端点）
- [x] 判断可复现：hysteresis 3 天连续规则确定，可复算

## 8. 风险与回滚

- 风险：compute_regime_labels 历史数据不够（如刚初始化）→返 None 不 alert（A4 兜底）
- 风险：hysteresis 3 天太严→错过快速 regime 切换。备选：2 天连续。先 3 天保守，可调
- 回滚：新 executor + cron seed，git revert 一个 commit 即回
