# -*- coding: utf-8 -*-
"""S215 通用技术指标评分——MA/MACD/RSI/量能/乖离/支撑 6 维 100 分制 + 信号映射。

按 stock-analysis skill（liusai0820 ModelScope）方法论，独立通用技术评分模块。
不碰打板 scoring.py（14 维打板专用保持）+ 不碰 §44v2/lift_for_arm（regime 守护区）。

数据源：baostock bars（OHLCV，不封 IP）——走 engine.bars_provider。
6 维从 bars 复算（可复算非臆造），缺数据标 missing 不编。
"""
from __future__ import annotations

import logging

_logger = logging.getLogger(__name__)

# 信号映射（100 分制，按 stock-analysis）
SIGNAL_STRONG_BUY = "强烈买入"
SIGNAL_BUY = "买入"
SIGNAL_HOLD = "持有"
SIGNAL_WATCH = "观望"
SIGNAL_STRONG_SELL = "强烈卖出"


def score_to_signal(score: float) -> str:
    """100 分 → 信号映射（按 stock-analysis）。"""
    if score >= 75:
        return SIGNAL_STRONG_BUY
    if score >= 60:
        return SIGNAL_BUY
    if score >= 45:
        return SIGNAL_HOLD
    if score >= 30:
        return SIGNAL_WATCH
    return SIGNAL_STRONG_SELL


# ── 辅助：MA / EMA 计算 ──────────────────────────────────────────────

def _sma(values: list[float], period: int) -> list[float | None]:
    """简单移动平均（SMA）。返 list 同 len，前 period-1 个返 None。"""
    out: list[float | None] = [None] * len(values)
    for i in range(period - 1, len(values)):
        out[i] = sum(values[i - period + 1 : i + 1]) / period
    return out


def _ema(values: list[float], period: int) -> list[float | None]:
    """指数移动平均（EMA）。"""
    out: list[float | None] = [None] * len(values)
    if not values:
        return out
    k = 2 / (period + 1)
    out[0] = values[0]
    for i in range(1, len(values)):
        out[i] = values[i] * k + (out[i - 1] or 0) * (1 - k)
    return out


# ── 维度1：MA 均线系统（多空排列）──────────────────────────────────────

def score_ma(bars: list[dict]) -> tuple[float, dict]:
    """MA5/10/20/60 多空排列评分。多头排列高分，空头低分。"""
    closes = [float(b.get("close", 0) or 0) for b in bars if b.get("close")]
    if len(closes) < 60:
        return 50.0, {"reason": f"bars {len(closes)} < 60 无法算 MA60"}
    ma5 = _sma(closes, 5)[-1]
    ma10 = _sma(closes, 10)[-1]
    ma20 = _sma(closes, 20)[-1]
    ma60 = _sma(closes, 60)[-1]
    if None in (ma5, ma10, ma20, ma60):
        return 50.0, {"reason": "MA 含 None"}
    if ma5 > ma10 > ma20 > ma60:  # 多头排列
        score = 85.0
    elif ma5 > ma10 > ma20:  # 弱多头
        score = 70.0
    elif ma5 < ma10 < ma20 < ma60:  # 空头排列
        score = 20.0
    elif ma5 < ma10 < ma20:  # 弱空头
        score = 35.0
    else:  # 交叉/震荡
        score = 50.0
    return round(score, 1), {"ma5": round(ma5, 4), "ma10": round(ma10, 4),
                             "ma20": round(ma20, 4), "ma60": round(ma60, 4)}


# ── 维度2：MACD（DIF/DEA/柱状）────────────────────────────────────────

def score_macd(bars: list[dict]) -> tuple[float, dict]:
    """MACD 趋势动能评分。金叉（DIF>DEA）+ 柱状放大高分。"""
    closes = [float(b.get("close", 0) or 0) for b in bars if b.get("close")]
    if len(closes) < 26:
        return 50.0, {"reason": f"bars {len(closes)} < 26 无法算 MACD"}
    ema12 = _ema(closes, 12)
    ema26 = _ema(closes, 26)
    dif = [(ema12[i] or 0) - (ema26[i] or 0) for i in range(len(closes))]
    dea = _ema(dif, 9)
    hist = [(dif[i] or 0) - (dea[i] or 0) for i in range(len(dif))]
    dif_last = dif[-1]
    dea_last = dea[-1] or 0
    hist_last = hist[-1]
    hist_prev = hist[-2] if len(hist) >= 2 else 0
    if dif_last > dea_last:  # 金叉
        score = 85.0 if hist_last > hist_prev else 70.0  # 柱状放大加分
    elif dif_last < dea_last:  # 死叉
        score = 20.0 if hist_last < hist_prev else 35.0
    else:
        score = 50.0
    return round(score, 1), {"dif": round(dif_last, 4), "dea": round(dea_last, 4),
                             "hist": round(hist_last, 4)}


# ── 维度3：RSI（6/12/24 超买超卖）─────────────────────────────────────

def _rsi(closes: list[float], period: int) -> float | None:
    """RSI（Wilder 简化版）。"""
    if len(closes) < period + 1:
        return None
    gains = 0.0
    losses = 0.0
    for i in range(-period, 0):
        diff = closes[i] - closes[i - 1]
        if diff > 0:
            gains += diff
        else:
            losses += -diff
    avg_gain = gains / period
    avg_loss = losses / period
    if avg_loss == 0:
        return 100.0
    rs = avg_gain / avg_loss
    return 100 - (100 / (1 + rs))


def score_rsi(bars: list[dict]) -> tuple[float, dict]:
    """RSI 6/12/24 超买超卖评分。40-60 中性高分，>70 超买低分（追高风险），<30 超卖高分（反弹）。"""
    closes = [float(b.get("close", 0) or 0) for b in bars if b.get("close")]
    rsi6 = _rsi(closes, 6)
    rsi12 = _rsi(closes, 12)
    rsi24 = _rsi(closes, 24)
    if rsi6 is None or rsi12 is None or rsi24 is None:
        return 50.0, {"reason": "bars 不足算 RSI24"}
    avg = (rsi6 + rsi12 + rsi24) / 3
    if 40 <= avg <= 60:  # 中性健康
        score = 80.0
    elif 30 <= avg < 40 or 60 < avg <= 70:  # 偏强/偏弱
        score = 65.0
    elif avg > 70:  # 超买（追高风险）
        score = 30.0
    elif avg < 30:  # 超卖（反弹机会）
        score = 75.0
    else:
        score = 50.0
    return round(score, 1), {"rsi6": round(rsi6, 2), "rsi12": round(rsi12, 2), "rsi24": round(rsi24, 2)}


# ── 维度4：量能（量比）─────────────────────────────────────────────────

def score_volume(bars: list[dict]) -> tuple[float, dict]:
    """量比评分。量比 1-2 健康放量高分，>5 异常低分，<0.5 缩量低分。"""
    vols = [float(b.get("volume", 0) or 0) for b in bars if b.get("volume") is not None]
    if len(vols) < 6:
        return 50.0, {"reason": f"bars {len(vols)} < 6 无法算量比"}
    last_vol = vols[-1]
    avg5 = sum(vols[-6:-1]) / 5  # 前 5 日均量
    if avg5 == 0:
        return 50.0, {"reason": "avg5=0"}
    vol_ratio = last_vol / avg5
    if 1.0 <= vol_ratio <= 2.0:  # 健康放量
        score = 80.0
    elif 0.5 <= vol_ratio < 1.0 or 2.0 < vol_ratio <= 5.0:  # 缩量/温和放量
        score = 60.0
    elif vol_ratio > 5.0:  # 异常放量（见顶/见底风险）
        score = 40.0
    elif vol_ratio < 0.5:  # 严重缩量
        score = 45.0
    else:
        score = 50.0
    return round(score, 1), {"vol_ratio": round(vol_ratio, 3), "last_vol": last_vol, "avg5": avg5}


# ── 维度5：乖离率（BIAS vs MA20）──────────────────────────────────────

def score_bias(bars: list[dict]) -> tuple[float, dict]:
    """乖离率评分。BIAS 在 ±5% 内高分（无追高风险），>5% 追高低分，<-5% 超卖高分。"""
    closes = [float(b.get("close", 0) or 0) for b in bars if b.get("close")]
    if len(closes) < 20:
        return 50.0, {"reason": f"bars {len(closes)} < 20 无法算 MA20"}
    ma20 = _sma(closes, 20)[-1]
    if ma20 is None or ma20 == 0:
        return 50.0, {"reason": "MA20 None/0"}
    last_close = closes[-1]
    bias = (last_close - ma20) / ma20 * 100  # 百分比
    if -5 <= bias <= 5:  # 无追高风险
        score = 80.0
    elif 5 < bias <= 10:  # 追高
        score = 40.0
    elif bias > 10:  # 严重追高
        score = 20.0
    elif -10 <= bias < -5:  # 超卖
        score = 70.0
    elif bias < -10:  # 严重超卖
        score = 60.0
    else:
        score = 50.0
    return round(score, 1), {"bias_pct": round(bias, 2), "ma20": round(ma20, 4), "last_close": last_close}


# ── 维度6：支撑/压力位 ────────────────────────────────────────────────

def score_support(bars: list[dict]) -> tuple[float, dict]:
    """支撑/压力位评分。近支撑（+5% 内）高分，近压力（-5% 内）低分。

    支撑/压力 = 近 20 日 low/high min/max（简化）。
    """
    if len(bars) < 20:
        return 50.0, {"reason": f"bars {len(bars)} < 20 无法算支撑压力"}
    recent = bars[-20:]
    lows = [float(b.get("low", 0) or 0) for b in recent if b.get("low") is not None]
    highs = [float(b.get("high", 0) or 0) for b in recent if b.get("high") is not None]
    if not lows or not highs:
        return 50.0, {"reason": "缺 low/high"}
    support = min(lows)
    resistance = max(highs)
    last_close = float(bars[-1].get("close", 0) or 0)
    if last_close == 0:
        return 50.0, {"reason": "last_close=0"}
    dist_support_pct = (last_close - support) / support * 100 if support > 0 else 0
    dist_resist_pct = (resistance - last_close) / last_close * 100 if last_close > 0 else 0
    if dist_support_pct <= 5:  # 近支撑
        score = 80.0
    elif dist_resist_pct <= 5:  # 近压力
        score = 35.0
    elif dist_support_pct < dist_resist_pct:  # 离支撑近
        score = 65.0
    else:  # 离压力近
        score = 45.0
    return round(score, 1), {"support": support, "resistance": resistance,
                             "dist_support_pct": round(dist_support_pct, 2),
                             "dist_resist_pct": round(dist_resist_pct, 2)}


# ── 合成：100 分 + 信号 ───────────────────────────────────────────────

def compute_tech_score(bars: list[dict]) -> dict:
    """6 维合成 100 分 + 信号映射（等权，不 flat 先验权重防过拟合）。

    Args:
        bars: baostock bars list[dict]（OHLCV，按 date asc）。

    Returns:
        {total_score, signal, n_bars, dimensions: {ma/macd/rsi/volume/bias/support 各 score+raw}}
        bars < 60 → {total_score:0, signal:观望, reason}。
    """
    if not bars or len(bars) < 60:
        return {"total_score": 0.0, "signal": SIGNAL_WATCH,
                "reason": f"bars 不足（{len(bars) if bars else 0} < 60）", "n_bars": len(bars) if bars else 0}
    ma_s, ma_raw = score_ma(bars)
    macd_s, macd_raw = score_macd(bars)
    rsi_s, rsi_raw = score_rsi(bars)
    vol_s, vol_raw = score_volume(bars)
    bias_s, bias_raw = score_bias(bars)
    sup_s, sup_raw = score_support(bars)
    total = round((ma_s + macd_s + rsi_s + vol_s + bias_s + sup_s) / 6, 1)
    signal = score_to_signal(total)
    return {
        "total_score": total,
        "signal": signal,
        "n_bars": len(bars),
        "dimensions": {
            "ma": {"score": ma_s, **ma_raw},
            "macd": {"score": macd_s, **macd_raw},
            "rsi": {"score": rsi_s, **rsi_raw},
            "volume": {"score": vol_s, **vol_raw},
            "bias": {"score": bias_s, **bias_raw},
            "support": {"score": sup_s, **sup_raw},
        },
    }


__all__ = ["compute_tech_score", "score_to_signal",
           "score_ma", "score_macd", "score_rsi", "score_volume", "score_bias", "score_support",
           "SIGNAL_STRONG_BUY", "SIGNAL_BUY", "SIGNAL_HOLD", "SIGNAL_WATCH", "SIGNAL_STRONG_SELL"]
