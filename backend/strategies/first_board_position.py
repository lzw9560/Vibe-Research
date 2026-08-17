# -*- coding: utf-8 -*-
"""S075 Phase 3 建仓 + T+1 卖出（tasks.md 043-052）。

实现范围：
- 043-045 建仓选股 + 记录建仓 + 飞书通知
- 048-050 T+1 卖出提醒 + 止盈止损判定 + 记录卖出
- 主入口 run_first_board_position 串联建仓

输入：open_confirmed（来自 first_board_confirm 的确认强势候选）+
      market_judge（来自 first_board_market_env 的 3 因素判定，含 light）

**仓位映射（spec 2.4，待回测校准）**：
- 绿灯：3-5 只等权，单股 25%（≈20-33%）
- 黄灯：最多 3 只，单股 15%
- 红灯（暴风雨）：0 仓位（硬约束）

**T+1 必卖不破例**（spec 2.5 注）：
即使 T 日收盘涨停也不持有——首板→二板晋级率约 20-30%，不赌连板。
默认 T+1 9:25 竞价/9:30 开盘卖出，盘中触及止盈/止损线则提前卖出。

阈值集中在本模块顶部 POSITION_PARAMS，**待回测校准**（30 天后用实际数据调）。

合规：本模块按用户传入的确认候选 + 市场判定返回客观建仓/卖出建议，
仓位映射是 spec 2.4 明确的灯位规则（非主观建议），T+1 必卖是 spec 2.5 硬规则。
"""
from __future__ import annotations

import logging
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from astock import tencent_quote  # noqa: E402

_logger = logging.getLogger(__name__)

# ===========================================================================
# 仓位参数（待回测校准，30 天后用实际数据调）
# ===========================================================================
# 所有阈值集中在此常量，顶部统一管理。当前值为 spec 2.4 骨架占位，**待回测校准**。
# T+1 必卖不破例（spec 2.5）：即使 T 日收盘涨停也不持有。
POSITION_PARAMS: dict = {
    "max_holdings": 5,           # 最大持仓 5 只
    "green_light_max": 5,        # 绿灯最多 5 只
    "yellow_light_max": 3,       # 黄灯最多 3 只
    "red_light_max": 0,          # 红灯 0 只（暴风暴风雨 0 仓位硬约束）
    "green_weight": 0.25,        # 绿灯单股仓位（3-5 只等权≈20-33%）
    "yellow_weight": 0.15,       # 黄灯单股仓位
    "stop_loss_pct": -0.03,      # 止损 -3%
    "take_profit_pct": 0.05,     # 止盈 +5%
    "max_hold_days": 1,          # T+1 必卖
}


# ===========================================================================
# 043-045 建仓选股 + 记录 + 通知
# ===========================================================================

def select_for_entry(open_confirmed: list[dict], market_light: str) -> list[dict]:
    """建仓选股——按评分排序取前 N 只（绿灯 5/黄灯 3/红灯 0），等权分配仓位。

    Args:
        open_confirmed: 来自 first_board_confirm 的 open_confirmed（已按 total 降序）。
        market_light: 市场判定灯位 "green"/"yellow"/"red"。

    Returns:
        list[dict]，每项含：
        - code, name, total_score（来自 open_confirmed）
        - entry_price: float | None（tencent_quote 取开盘价，9:35-9:45 窗口）
        - position_pct: float（绿灯 25%/黄灯 15%/红灯 0%）
        - stop_loss: float | None（entry_price * (1 + stop_loss_pct)）
        - take_profit: float | None（entry_price * (1 + take_profit_pct)）
        - entry_rank: int（1-based，建仓优先级）
    """
    # 灯位 → 最大持仓数 + 单股仓位
    light = (market_light or "").lower()
    if light == "green":
        max_n = POSITION_PARAMS["green_light_max"]
        weight = POSITION_PARAMS["green_weight"]
    elif light == "yellow":
        max_n = POSITION_PARAMS["yellow_light_max"]
        weight = POSITION_PARAMS["yellow_weight"]
    else:  # red 或未知 → 0 仓位
        max_n = POSITION_PARAMS["red_light_max"]
        weight = 0.0

    # open_confirmed 已按 total 降序，取前 max_n 只
    selected_codes = [c.get("code", "") for c in open_confirmed[:max_n] if c.get("code")]

    # 批量取开盘价（tencent_quote 60s 缓存，一次请求）
    entry_prices: dict[str, float | None] = {}
    if selected_codes:
        try:
            quotes = tencent_quote(selected_codes)
        except Exception as e:
            _logger.warning("select_for_entry tencent_quote 失败 err=%s", e)
            quotes = {}
        for code in selected_codes:
            q = quotes.get(code) if quotes else None
            if q and isinstance(q, dict):
                entry_prices[code] = _to_float(q.get("open"))
            else:
                entry_prices[code] = None

    stop_pct = POSITION_PARAMS["stop_loss_pct"]
    tp_pct = POSITION_PARAMS["take_profit_pct"]

    out: list[dict] = []
    for rank, cand in enumerate(open_confirmed[:max_n], start=1):
        code = cand.get("code", "")
        ep = entry_prices.get(code)
        out.append({
            "code": code,
            "name": cand.get("name", ""),
            "total_score": cand.get("total"),
            "entry_price": ep,
            "position_pct": weight,
            "stop_loss": round(ep * (1 + stop_pct), 2) if ep else None,
            "take_profit": round(ep * (1 + tp_pct), 2) if ep else None,
            "entry_rank": rank,
        })
    return out


def execute_entry(selected: list[dict], entry_price: float | None = None) -> list[dict]:
    """记录建仓。

    Args:
        selected: select_for_entry 返回的选股 list[dict]。
        entry_price: 实际建仓价（人工点确认后传入）。None 时用 selected 的 entry_price。

    Returns:
        list[dict]，每项在 selected 基础上加：
        - entry_time: str（ISO 时间戳）
        - entry_price_actual: float（实际建仓价）
    """
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    out: list[dict] = []
    for s in selected:
        ep_actual = entry_price if entry_price is not None else s.get("entry_price")
        out.append({
            **s,
            "entry_time": now,
            "entry_price_actual": ep_actual,
        })
    return out


def notify_entry_ready(selected: list[dict]) -> bool:
    """建仓飞书通知——候选达 3 只推送"首板流候选已满 N 只，可建仓"。

    复用 NotificationService（与 first_board_market_env 同款）。
    候选<3 只不推送（spec 2.4：等权 3-5 只，不足 3 只不建仓）。

    Args:
        selected: select_for_entry 返回的选股 list。

    Returns:
        bool：是否推送成功（至少一个渠道成功）。渠道未配置/候选<3 → False。
    """
    if len(selected) < 3:
        _logger.info("[notify_entry_ready] 候选 %d 只 <3，不推送建仓通知", len(selected))
        return False

    codes = ", ".join(f"{s.get('code', '')} {s.get('name', '')}" for s in selected)
    pct = selected[0].get("position_pct", 0) * 100 if selected else 0
    content = (
        f"【首板流建仓提醒】候选已满 {len(selected)} 只，可建仓\n"
        f"单股仓位 {pct:.0f}%，T+1 必卖（不赌连板）\n"
        f"候选：{codes}"
    )

    try:
        from notification.notification_service import NotificationService
        ns = NotificationService()
    except Exception as e:
        _logger.warning("[notify_entry_ready] NotificationService 初始化失败 err=%s", e)
        return False

    if not ns.is_available():
        _logger.info("[notify_entry_ready] 无可用通知渠道，跳过推送")
        return False

    try:
        return bool(ns.send(content, route_type="alert", severity="info"))
    except Exception as e:
        _logger.warning("[notify_entry_ready] 推送失败 err=%s", e)
        return False


# ===========================================================================
# 048-050 T+1 卖出
# ===========================================================================

def notify_sell_reminder(holdings: list[dict]) -> bool:
    """T+1 开盘前推送"今日卖出提醒：N 只持仓"。

    Args:
        holdings: 建仓记录 list[dict]（含 code/entry_price_actual）。

    Returns:
        bool：是否推送成功。无持仓/渠道未配置 → False。
    """
    if not holdings:
        return False

    codes = ", ".join(f"{h.get('code', '')}" for h in holdings)
    content = (
        f"【首板流卖出提醒】今日 T+1 必卖 {len(holdings)} 只持仓\n"
        f"T+1 必卖不破例（即使涨停也不持有）\n"
        f"持仓：{codes}"
    )

    try:
        from notification.notification_service import NotificationService
        ns = NotificationService()
    except Exception as e:
        _logger.warning("[notify_sell_reminder] NotificationService 初始化失败 err=%s", e)
        return False

    if not ns.is_available():
        return False

    try:
        return bool(ns.send(content, route_type="alert", severity="warning"))
    except Exception as e:
        _logger.warning("[notify_sell_reminder] 推送失败 err=%s", e)
        return False


def check_exit_signals(holding: dict, current_price: float) -> dict:
    """T+1 盘中止盈止损判定。

    Args:
        holding: 建仓记录 dict（含 entry_price_actual/stop_loss/take_profit）。
        current_price: T+1 盘中实时价。

    Returns:
        dict 含：
        - code: str
        - action: "hold" | "take_profit" | "stop_loss" | "default_sell"
        - exit_price: float（建议卖出价）
        - reason: str（人话原因）

    规则（spec 2.5，标注"待回测校准"）：
    - current_price >= entry_price * (1 + take_profit_pct) → take_profit "盘中冲高>5%止盈"
    - current_price <= entry_price * (1 + stop_loss_pct) → stop_loss "跌破-3%止损"
    - 默认（9:25 竞价/9:30 开盘）→ default_sell "T+1 必卖不贪婪"
    - T+1 必卖不破例——即使 T 日收盘涨停也不持有（spec 2.5 注）

    ⚠️ 本函数判定止盈止损线，default_sell 由调用方在 9:25/9:30 触发（不在本函数内）。
    本函数返 "hold" 表示未触及止盈止损线，继续持有至 9:25/9:30 默认卖。
    """
    code = holding.get("code", "")
    entry = holding.get("entry_price_actual") or holding.get("entry_price")
    stop_loss = holding.get("stop_loss")
    take_profit = holding.get("take_profit")

    # 数据缺失 → 降级 default_sell（无法判定止盈止损线）
    if entry is None or current_price is None:
        return {
            "code": code,
            "action": "default_sell",
            "exit_price": current_price,
            "reason": "数据缺失无法判定止盈止损，T+1 必卖",
        }

    # 止盈：current_price >= take_profit 线
    if take_profit is not None and current_price >= take_profit:
        return {
            "code": code,
            "action": "take_profit",
            "exit_price": current_price,
            "reason": f"盘中冲高>{POSITION_PARAMS['take_profit_pct']*100:.0f}%止盈",
        }

    # 止损：current_price <= stop_loss 线
    if stop_loss is not None and current_price <= stop_loss:
        return {
            "code": code,
            "action": "stop_loss",
            "exit_price": current_price,
            "reason": f"跌破{POSITION_PARAMS['stop_loss_pct']*100:.0f}%止损",
        }

    # 未触及止盈止损线 → hold（继续持有至 9:25/9:30 默认卖）
    return {
        "code": code,
        "action": "hold",
        "exit_price": current_price,
        "reason": "未触及止盈止损线，持有至 T+1 9:25/9:30 默认卖",
    }


def execute_exit(holding: dict, exit_price: float, action: str) -> dict:
    """记录卖出。

    Args:
        holding: 建仓记录 dict（含 entry_price_actual）。
        exit_price: 实际卖出价。
        action: 卖出动作 "take_profit"/"stop_loss"/"default_sell"。

    Returns:
        dict 含：
        - code, entry_price, exit_price, return_pct, action, exit_time, hold_days:1
        - return_pct = (exit_price - entry_price) / entry_price * 100
    """
    entry = holding.get("entry_price_actual") or holding.get("entry_price")
    return_pct = None
    if entry is not None and exit_price is not None and entry > 0:
        return_pct = round((exit_price - entry) / entry * 100, 2)

    return {
        "code": holding.get("code", ""),
        "name": holding.get("name", ""),
        "entry_price": entry,
        "exit_price": exit_price,
        "return_pct": return_pct,
        "action": action,
        "exit_time": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "hold_days": POSITION_PARAMS["max_hold_days"],  # T+1 必卖 = 1 天
    }


# ===========================================================================
# 主入口
# ===========================================================================

def run_first_board_position(
    open_confirmed: list[dict],
    market_judge: dict,
    entry_prices: dict | None = None,
) -> dict:
    """Phase 3 主入口。

    Args:
        open_confirmed: 来自 first_board_confirm 的 open_confirmed（已按 total 降序）。
        market_judge: 来自 first_board_market_env 的 3 因素判定，含 light。
        entry_prices: {code: price} 预填建仓价（人工点确认后传入）。
                      None → 用 tencent_quote 实时取开盘价。

    Returns:
        dict 含：
        - selected: list[dict]（建仓选股，含止盈止损线）
        - entered: list[dict]（已建仓记录，含 entry_time/entry_price_actual）
        - notified: bool（建仓通知是否推送）
        - holdings: list[dict]（持仓，= entered，供 T+1 卖出用）
    """
    light = market_judge.get("light", "red") if market_judge else "red"

    # 043 建仓选股
    selected = select_for_entry(open_confirmed, light)

    # 若调用方预填了 entry_prices，覆盖 tencent_quote 取的开盘价
    if entry_prices:
        for s in selected:
            code = s.get("code", "")
            if code in entry_prices:
                ep = entry_prices[code]
                s["entry_price"] = ep
                stop_pct = POSITION_PARAMS["stop_loss_pct"]
                tp_pct = POSITION_PARAMS["take_profit_pct"]
                s["stop_loss"] = round(ep * (1 + stop_pct), 2) if ep else None
                s["take_profit"] = round(ep * (1 + tp_pct), 2) if ep else None

    # 044 记录建仓
    entered = execute_entry(selected)

    # 045 建仓通知
    notified = notify_entry_ready(selected)

    return {
        "selected": selected,
        "entered": entered,
        "notified": notified,
        "holdings": entered,  # 持仓 = 已建仓记录，供 T+1 卖出用
    }


# ===========================================================================
# 辅助函数
# ===========================================================================

def _to_float(v) -> float | None:
    """raw 字段归一 float 或 None。"""
    if v is None:
        return None
    if isinstance(v, bool):
        return None
    if isinstance(v, (int, float)):
        return float(v)
    s = str(v).strip()
    if not s or s == "-":
        return None
    try:
        return float(s)
    except ValueError:
        return None


if __name__ == "__main__":
    # 骨架自测：python -m strategies.first_board_position
    confirmed = [
        {"code": "001358", "name": "兴欣新材", "total": 63.4},
        {"code": "600127", "name": "金健米业", "total": 60.0},
    ]
    judge = {"light": "green", "position_advice": "绿灯：可建仓 3-5 只等权"}
    prices = {"001358": 10.21, "600127": 5.30}
    r = run_first_board_position(confirmed, judge, prices)
    print(f"选股: {len(r['selected'])}")
    print(f"建仓: {len(r['entered'])}")
    for e in r["entered"]:
        print(f"  {e['code']} entry={e['entry_price_actual']} "
              f"stop={e['stop_loss']} tp={e['take_profit']} "
              f"pct={e['position_pct']*100:.0f}%")
    print(f"持仓: {len(r['holdings'])}")

    # 测试止盈止损
    hold = r["holdings"][0]
    ep = hold["entry_price_actual"]
    print(f"\n止盈测试 (price={ep*1.06}):", check_exit_signals(hold, ep * 1.06))
    print(f"止损测试 (price={ep*0.96}):", check_exit_signals(hold, ep * 0.96))
    print(f"默认卖测试 (price={ep*1.01}):", check_exit_signals(hold, ep * 1.01))

    # 测试卖出记录
    exit_r = execute_exit(hold, ep * 1.06, "take_profit")
    print(f"\n卖出记录:", exit_r)
