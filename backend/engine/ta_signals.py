# -*- coding: utf-8 -*-
"""S196 · 技术分析信号源扩展——MACD 背离 + RSI 超买超卖 classify 纯函数。

跟 S193 classify_gap 同范式：regime/状态判断信号不直接触发买卖，喂 AI 研判 + 融合消融验（S194）。
P0 候选（memory ta-signal-candidates-2026-09-12）：MACD 背离 + RSI 超买超卖背离。

MACD（12/26/9 EMA）算 DIF/DEA/MACD 柱：
- 顶背离：价格创新高但 MACD 柱未同步创新高 → 反转 regime（动能衰竭）
- 底背离：价格创新低但 MACD 柱未同步创新低 → 反转 regime

RSI（14 日默认）算超买/超卖 + 背离：
- 超买 RSI>70（反转风险）+ 超卖 RSI<30（反弹机会）
- 顶背离：价格新高但 RSI 未新高 → 反转；底背离：价格新低但 RSI 未新低 → 反转

纯函数核心 `_classify_macd_divergence_from_bars(bars, target_idx)` / `_classify_rsi_from_bars(bars, target_idx)`
无 IO 可单测；外壳 `classify_macd_divergence(code, date)` / `classify_rsi(code, date)` 拉 baostock 调核心。

⚠️ A 股限制（memory ta-signal-candidates）：
- MACD 震荡市钝化（连续背离假信号）——caveat 标注
- RSI 涨跌停致钝化（连续涨停长期超买）——涨停状态过滤（close=涨停价）
"""
from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)

# 参数（§44 sweep 空间，起点非拍死）
MACD_FAST = 12          # MACD 快线 EMA 周期
MACD_SLOW = 26          # MACD 慢线 EMA 周期
MACD_SIGNAL = 9         # MACD 信号线 EMA 周期
RSI_PERIOD = 14         # RSI 周期（默认 14 日）
RSI_OVERBOUGHT = 70.0  # RSI 超买阈值
RSI_OVERSOLD = 30.0     # RSI 超卖阈值
DIVERGENCE_WINDOW = 20  # 背离判定窗口（往前看 N 日找前高/前低 + 指标前高/前低）
LIMIT_UP_RATIO = 0.095  # A 股涨停价比例（主板 10%，ST 5%，创业板/科创板 20%——默认主板）


def _bar_get(bar: dict, key: str, default: float = 0.0) -> float:
    """从 bar dict 取数值字段，容错（baostock key: date/open/high/low/close/volume）。"""
    v = bar.get(key, default)
    try:
        return float(v) if v is not None else default
    except (TypeError, ValueError):
        return default


def _bar_date(bar: dict) -> str:
    """取 bar 日期（baostock 'date' 字段，YYYY-MM-DD）。"""
    return str(bar.get("date", ""))[:10]


def _ema(values: list[float], period: int) -> list[float]:
    """算 EMA（指数移动平均）。返等长 list（前 period-1 个用 SMA 填充）。"""
    if not values:
        return []
    ema = [0.0] * len(values)
    k = 2.0 / (period + 1)
    # 第一个值直接用
    ema[0] = values[0]
    for i in range(1, len(values)):
        ema[i] = values[i] * k + ema[i - 1] * (1 - k)
    return ema


def _compute_macd(closes: list[float]) -> tuple[list[float], list[float], list[float]]:
    """算 MACD 三线：DIF（快慢线差）、DEA（信号线）、MACD 柱（DIF-DEA）。返 (dif, dea, macd_hist)。"""
    if len(closes) < MACD_SLOW + MACD_SIGNAL:
        return [], [], []
    ema_fast = _ema(closes, MACD_FAST)
    ema_slow = _ema(closes, MACD_SLOW)
    dif = [ema_fast[i] - ema_slow[i] for i in range(len(closes))]
    dea = _ema(dif, MACD_SIGNAL)
    macd_hist = [dif[i] - dea[i] for i in range(len(closes))]
    return dif, dea, macd_hist


def _compute_rsi(closes: list[float], period: int = RSI_PERIOD) -> list[float]:
    """算 RSI（相对强弱指数）。返等长 list（前 period 个用 50 填充）。"""
    if len(closes) < period + 1:
        return [50.0] * len(closes)
    rsi = [50.0] * len(closes)
    gains = []
    losses = []
    for i in range(1, len(closes)):
        diff = closes[i] - closes[i - 1]
        gains.append(max(0, diff))
        losses.append(max(0, -diff))
    # 初始 avg_gain/avg_loss 用前 period 个的 SMA
    avg_gain = sum(gains[:period]) / period if len(gains) >= period else 0.0
    avg_loss = sum(losses[:period]) / period if len(losses) >= period else 0.0
    for i in range(period, len(closes)):
        if i > period:
            avg_gain = (avg_gain * (period - 1) + gains[i - 1]) / period
            avg_loss = (avg_loss * (period - 1) + losses[i - 1]) / period
        if avg_loss == 0:
            rsi[i] = 100.0
        else:
            rs = avg_gain / avg_loss
            rsi[i] = 100.0 - 100.0 / (1.0 + rs)
    return rsi


def _is_limit_up(bar: dict, prev_close: float) -> bool:
    """A 股涨停判定（close ≈ prev_close × (1 + LIMIT_UP_RATIO)）。"""
    close = _bar_get(bar, "close")
    if prev_close <= 0:
        return False
    limit_price = prev_close * (1 + LIMIT_UP_RATIO)
    return abs(close - limit_price) / limit_price < 0.002  # 0.2% 容差


def _find_prev_extreme(values: list[float], idx: int, window: int, find_high: bool = True) -> tuple[int, float]:
    """找 idx 前 window 内极值（高/低）。返 (extreme_idx, extreme_val)。"""
    start = max(0, idx - window)
    segment = values[start:idx]
    if not segment:
        return -1, 0.0
    if find_high:
        ext_val = max(segment)
    else:
        ext_val = min(segment)
    ext_idx = start + segment.index(ext_val)
    return ext_idx, ext_val


def _classify_macd_divergence_from_bars(bars: list[dict], target_idx: int) -> dict:
    """纯函数核心：从日 K 列表 + 目标日 idx 算 MACD 背离。无 IO，可单测。

    返 {type: 顶背离/底背离/无, regime: 反转/噪声, confidence: 0-1,
        params: {dif, dea, macd_hist, price_high, macd_high}}
    """
    result = {
        "type": "无背离", "regime": "噪声", "confidence": 0.0,
        "params": {},
    }
    if target_idx < 0 or target_idx >= len(bars):
        result["params"] = {"error": "target_idx 越界"}
        return result

    closes = [_bar_get(b, "close") for b in bars]
    if len(closes) < MACD_SLOW + MACD_SIGNAL + DIVERGENCE_WINDOW:
        result["params"] = {"error": f"数据不足（需 {MACD_SLOW + MACD_SIGNAL + DIVERGENCE_WINDOW} 日，实际 {len(closes)} 日）"}
        return result

    dif, dea, macd_hist = _compute_macd(closes)
    if not dif:
        result["params"] = {"error": "MACD 计算失败"}
        return result

    # 当前价格 + MACD 柱
    curr_close = closes[target_idx]
    curr_macd = macd_hist[target_idx]

    # 找前 DIVERGENCE_WINDOW 内价格高/低 + MACD 柱高/低
    price_prev_high_idx, price_prev_high = _find_prev_extreme(closes, target_idx, DIVERGENCE_WINDOW, find_high=True)
    price_prev_low_idx, price_prev_low = _find_prev_extreme(closes, target_idx, DIVERGENCE_WINDOW, find_high=False)
    macd_prev_high_idx, macd_prev_high = _find_prev_extreme(macd_hist, target_idx, DIVERGENCE_WINDOW, find_high=True)
    macd_prev_low_idx, macd_prev_low = _find_prev_extreme(macd_hist, target_idx, DIVERGENCE_WINDOW, find_high=False)

    params = {
        "dif": round(dif[target_idx], 4),
        "dea": round(dea[target_idx], 4),
        "macd_hist": round(curr_macd, 4),
        "price_prev_high": round(price_prev_high, 4),
        "macd_prev_high": round(macd_prev_high, 4),
        "price_prev_low": round(price_prev_low, 4),
        "macd_prev_low": round(macd_prev_low, 4),
    }

    # 顶背离：当前价格创新高（> 前高）但 MACD 柱未创新高（< 前高）
    if curr_close > price_prev_high and curr_macd < macd_prev_high:
        return {
            "type": "顶背离", "regime": "反转", "confidence": 0.7,
            "params": params,
        }
    # 底背离：当前价格创新低（< 前低）但 MACD 柱未创新低（> 前低，即更不低）
    if curr_close < price_prev_low and curr_macd > macd_prev_low:
        return {
            "type": "底背离", "regime": "反转", "confidence": 0.7,
            "params": params,
        }

    result["params"] = params
    return result


def _classify_rsi_from_bars(bars: list[dict], target_idx: int, period: int = RSI_PERIOD) -> dict:
    """纯函数核心：从日 K 列表 + 目标日 idx 算 RSI 超买超卖 + 背离。无 IO，可单测。

    返 {rsi, state: 超买/超卖/中性, divergence: 顶背离/底背离/无,
        regime: 反转/状态确认/噪声, confidence: 0-1,
        params: {rsi, price_prev_high, rsi_prev_high, ...}}
    """
    result = {
        "rsi": 50.0, "state": "中性", "divergence": "无背离",
        "regime": "噪声", "confidence": 0.0, "params": {},
    }
    if target_idx < 0 or target_idx >= len(bars):
        result["params"] = {"error": "target_idx 越界"}
        return result

    closes = [_bar_get(b, "close") for b in bars]
    if len(closes) < period + DIVERGENCE_WINDOW:
        result["params"] = {"error": f"数据不足（需 {period + DIVERGENCE_WINDOW} 日，实际 {len(closes)} 日）"}
        return result

    rsi_vals = _compute_rsi(closes, period)
    curr_rsi = rsi_vals[target_idx]
    curr_close = closes[target_idx]

    # 涨停过滤（A 股涨跌停致 RSI 钝化）
    prev_close = closes[target_idx - 1] if target_idx > 0 else 0.0
    is_limit_up = _is_limit_up(bars[target_idx], prev_close)

    # 超买/超卖判定
    if curr_rsi >= RSI_OVERBOUGHT:
        state = "超买"
    elif curr_rsi <= RSI_OVERSOLD:
        state = "超卖"
    else:
        state = "中性"

    # 背离判定
    price_prev_high_idx, price_prev_high = _find_prev_extreme(closes, target_idx, DIVERGENCE_WINDOW, find_high=True)
    price_prev_low_idx, price_prev_low = _find_prev_extreme(closes, target_idx, DIVERGENCE_WINDOW, find_high=False)
    rsi_prev_high_idx, rsi_prev_high = _find_prev_extreme(rsi_vals, target_idx, DIVERGENCE_WINDOW, find_high=True)
    rsi_prev_low_idx, rsi_prev_low = _find_prev_extreme(rsi_vals, target_idx, DIVERGENCE_WINDOW, find_high=False)

    divergence = "无背离"
    regime = "噪声"
    confidence = 0.3

    # 顶背离：价格新高但 RSI 未新高
    if curr_close > price_prev_high and curr_rsi < rsi_prev_high:
        divergence = "顶背离"
        regime = "反转"
        confidence = 0.7
    # 底背离：价格新低但 RSI 未新低
    elif curr_close < price_prev_low and curr_rsi > rsi_prev_low:
        divergence = "底背离"
        regime = "反转"
        confidence = 0.7
    elif state == "超买":
        regime = "状态确认"
        confidence = 0.5
    elif state == "超卖":
        regime = "状态确认"
        confidence = 0.5

    # 涨停 caveat（连续涨停 RSI 长期超买，信号不可靠）
    if is_limit_up and state == "超买":
        confidence *= 0.5  # 涨停 RSI 钝化降置信度
        regime = "噪声"
        divergence = "无背离（涨停钝化）"

    params = {
        "rsi": round(curr_rsi, 4),
        "price_prev_high": round(price_prev_high, 4),
        "rsi_prev_high": round(rsi_prev_high, 4),
        "price_prev_low": round(price_prev_low, 4),
        "rsi_prev_low": round(rsi_prev_low, 4),
        "涨停": is_limit_up,
    }

    return {
        "rsi": round(curr_rsi, 4), "state": state, "divergence": divergence,
        "regime": regime, "confidence": round(confidence, 3), "params": params,
    }


def classify_macd_divergence(code: str, date: str) -> dict:
    """外壳：拉 baostock 日 K 调纯函数核心。返 MACD 背离分类。

    数据源：baostock query_history_k_data_plus（date/open/high/low/close/volume）。
    拉 60 日（覆盖 MACD 26+9 + 20 日背离窗口）。
    """
    try:
        from baostock.util import bs  # noqa: PLC0415
    except ImportError:
        return {"type": "无背离", "regime": "噪声", "confidence": 0.0,
                "params": {"error": "baostock 未装"}}

    bars = _fetch_baostock_bars(code, date, count=60)
    if not bars:
        return {"type": "无背离", "regime": "噪声", "confidence": 0.0,
                "params": {"error": f"baostock 无数据 {code} {date}"}}

    target_idx = -1
    for i, b in enumerate(bars):
        if _bar_date(b) == date:
            target_idx = i
            break
    if target_idx < 0:
        return {"type": "无背离", "regime": "噪声", "confidence": 0.0,
                "params": {"error": f"target_date {date} 不在 bars"}}

    return _classify_macd_divergence_from_bars(bars, target_idx)


def classify_rsi(code: str, date: str, period: int = RSI_PERIOD) -> dict:
    """外壳：拉 baostock 日 K 调纯函数核心。返 RSI 超买超卖 + 背离分类。

    数据源：baostock query_history_k_data_plus（date/open/high/low/close/volume）。
    拉 60 日（覆盖 RSI 14 + 20 日背离窗口）。
    """
    try:
        from baostock.util import bs  # noqa: PLC0415
    except ImportError:
        return {"rsi": 50.0, "state": "中性", "divergence": "无背离",
                "regime": "噪声", "confidence": 0.0,
                "params": {"error": "baostock 未装"}}

    bars = _fetch_baostock_bars(code, date, count=60)
    if not bars:
        return {"rsi": 50.0, "state": "中性", "divergence": "无背离",
                "regime": "噪声", "confidence": 0.0,
                "params": {"error": f"baostock 无数据 {code} {date}"}}

    target_idx = -1
    for i, b in enumerate(bars):
        if _bar_date(b) == date:
            target_idx = i
            break
    if target_idx < 0:
        return {"rsi": 50.0, "state": "中性", "divergence": "无背离",
                "regime": "噪声", "confidence": 0.0,
                "params": {"error": f"target_date {date} 不在 bars"}}

    return _classify_rsi_from_bars(bars, target_idx, period)


def _fetch_baostock_bars(code: str, end_date: str, count: int = 60) -> list[dict]:
    """baostock 拉日 K（复用 engine.bars_provider 的 _baostock_a_share_hist）。"""
    try:
        from engine.bars_provider import _baostock_a_share_hist  # noqa: PLC0415
        from datetime import datetime, timedelta
        end = datetime.strptime(end_date, "%Y-%m-%d")
        start = (end - timedelta(days=count * 2)).strftime("%Y-%m-%d")
        bars = _baostock_a_share_hist(code, start, end_date)
        return bars or []
    except Exception as e:  # noqa: BLE001
        logger.warning("ta_signals baostock 拉 %s %s 失败: %s", code, end_date, e)
        return []


__all__ = [
    "classify_macd_divergence", "_classify_macd_divergence_from_bars",
    "classify_rsi", "_classify_rsi_from_bars",
    "_compute_macd", "_compute_rsi", "_ema", "_is_limit_up",
    "MACD_FAST", "MACD_SLOW", "MACD_SIGNAL", "RSI_PERIOD",
    "RSI_OVERBOUGHT", "RSI_OVERSOLD", "DIVERGENCE_WINDOW",
]
