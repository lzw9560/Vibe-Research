# -*- coding: utf-8 -*-
"""S066 Phase 2 P2-1/P2-2 板块成分股 + 个股形态计算。

spec §8 数据源：
- 板块成分股：BaoStock query_stock_industry（5540 条，证监会行业分类，84 个行业）
- 个股形态：kline_multi（已含 ma5/ma10/ma20/amount/volume）

spec §5.5/P2-2 形态计算：
- 相对强度：个股 5 日涨幅 - 板块 5 日涨幅
- 均线多头排列：MA5 > MA10 > MA20
- 横盘形态：N 日振幅 < 阈值
- MA5 接近度：低吸龙头用
- 成交额/量比突破：平台突破用

零 em_get（BaoStock 独立源 + kline_multi 多源回退）。
"""
from __future__ import annotations

import sqlite3
import time
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

from vr_paths import resolve_data_dir

# BaoStock 行业分类缓存（5540 条，日级不变，缓存到 .vibe-research）
_INDUSTRY_CACHE_PATH = resolve_data_dir() / "baostock_industry.json"
_INDUSTRY_CACHE: dict[str, str] | None = None  # code -> industry_name
_INDUSTRY_CACHE_TS: float = 0.0
_INDUSTRY_CACHE_TTL = 86400  # 24h（日级更新）


@dataclass(frozen=True)
class PatternScan:
    """个股形态扫描结果（spec §5.5/P2-2）。

    S094 R5：升为 market_scan 唯一因子源，新增 shadow_length_pct/ma5_slope
    （PatternReversal 长上影洗盘修复形态用）。
    """
    code: str
    relative_strength: float | None     # 个股 5 日涨幅 - 板块 5 日涨幅
    ma_bullish: bool                     # MA5 > MA10 > MA20
    ma5_proximity: float | None         # |close - MA5| / MA5 * 100（低吸龙头用）
    consolidation_days: int | None     # 横盘天数（振幅 < 阈值）
    consolidation_amplitude: float | None  # N 日振幅 %
    volume_breakout_ratio: float | None  # 量比放大倍数（今量/前5日均量）
    amount_yi: float | None             # 成交额（亿）
    # S094 R5 新增（PatternReversal 长上影洗盘修复形态）
    shadow_length_pct: float | None = None   # 上影线长度 = (high/close - 1)*100
    ma5_slope: float | None = None           # MA5 斜率 = (ma5_now - ma5_prev)/ma5_prev


# ===========================================================================
# 板块成分股（P2-1，spec §8）
# ===========================================================================

def load_industry_map(force_refresh: bool = False) -> dict[str, str]:
    """加载 BaoStock 行业分类 → {code: industry_name}。

    缓存到 .vibe-research/baostock_industry.json（24h TTL，日级更新）。
    force_refresh=True → 强制重新拉取。
    """
    global _INDUSTRY_CACHE, _INDUSTRY_CACHE_TS
    now = time.time()
    if not force_refresh and _INDUSTRY_CACHE is not None and (now - _INDUSTRY_CACHE_TS) < _INDUSTRY_CACHE_TTL:
        return _INDUSTRY_CACHE

    # 尝试从磁盘缓存加载
    if not force_refresh and _INDUSTRY_CACHE_PATH.exists():
        try:
            import json
            data = json.loads(_INDUSTRY_CACHE_PATH.read_text(encoding="utf-8"))
            if data and isinstance(data, dict) and "_meta" in data:
                cache_ts = data["_meta"].get("cached_ts", 0)
                if (now - cache_ts) < _INDUSTRY_CACHE_TTL:
                    mapping = data.get("mapping", {})
                    _INDUSTRY_CACHE = mapping
                    _INDUSTRY_CACHE_TS = cache_ts
                    return mapping
        except Exception:
            pass

    # 从 BaoStock 拉取
    mapping = _fetch_industry_from_baostock()
    if mapping:
        _INDUSTRY_CACHE = mapping
        _INDUSTRY_CACHE_TS = now
        _save_industry_cache(mapping, now)
    return mapping or {}


def _fetch_industry_from_baostock() -> dict[str, str]:
    """从 BaoStock 拉取行业分类（5540 条）。"""
    try:
        import baostock as bs
        lg = bs.login()
        if lg.error_code != "0":
            return {}
        rs = bs.query_stock_industry()
        mapping: dict[str, str] = {}
        while rs.error_code == "0" and rs.next():
            row = rs.get_row_data()
            # row: [updateDate, code(sh.600000), code_name, industry, industryClassification]
            if len(row) < 4:
                continue
            bs_code = row[1]  # sh.600000
            code = bs_code.split(".")[-1] if "." in bs_code else bs_code
            industry = row[3]
            if industry and code:
                mapping[code] = industry
        bs.logout()
        return mapping
    except Exception:
        return {}


def _save_industry_cache(mapping: dict[str, str], ts: float) -> None:
    """保存行业分类到磁盘缓存。"""
    try:
        import json
        data = {
            "_meta": {"cached_ts": ts, "count": len(mapping), "source": "baostock"},
            "mapping": mapping,
        }
        _INDUSTRY_CACHE_PATH.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    except Exception:
        pass


def get_sector_stocks(industry_name: str, industry_map: dict[str, str] | None = None) -> list[str]:
    """获取某板块的所有成分股代码（spec §8/P2-1）。

    industry_map: {code: industry_name}，不传则加载缓存。
    """
    if industry_map is None:
        industry_map = load_industry_map()
    return [code for code, ind in industry_map.items() if ind == industry_name]


def get_stock_industry(code: str, industry_map: dict[str, str] | None = None) -> str | None:
    """获取个股所属行业。"""
    if industry_map is None:
        industry_map = load_industry_map()
    return industry_map.get(code)


# ===========================================================================
# 形态计算（P2-2，spec §5.5）
# ===========================================================================

def compute_relative_strength(
    stock_bars: list[dict],
    sector_bars: list[dict] | None,
    days: int = 5,
) -> float | None:
    """相对强度：个股 N 日涨幅 - 板块 N 日涨幅（spec §5.5）。

    板块涨幅用板块成分股等权平均近似。
    """
    if not stock_bars or len(stock_bars) < days + 1:
        return None
    stock_ret = _pct_change(stock_bars, days)
    if stock_ret is None:
        return None

    if not sector_bars or len(sector_bars) < days + 1:
        return round(stock_ret, 4)  # 无板块数据，只返回个股涨幅

    sector_ret = _pct_change(sector_bars, days)
    if sector_ret is None:
        return round(stock_ret, 4)

    return round(stock_ret - sector_ret, 4)


def _pct_change(bars: list[dict], days: int) -> float | None:
    """N 日涨幅：(close[-1] - close[-1-days]) / close[-1-days] * 100。"""
    if len(bars) < days + 1:
        return None
    try:
        close_end = float(bars[-1].get("close", 0))
        close_start = float(bars[-1 - days].get("close", 0))
        if close_start <= 0:
            return None
        return (close_end - close_start) / close_start * 100
    except (ValueError, TypeError, IndexError):
        return None


def _compute_ma(bars: list[dict], n: int) -> float | None:
    """S094 R1：SMA(close[-n:]/n)，消费侧自算 MA，不依赖 cache ma5/ma10/ma20 字段。

    baostock cache FIELDS 无 ma5/ma10/ma20 → check_ma_bullish 旧实现读 last.get('ma5')
    恒 None 致恒 False。本函数从 close 序列自算修复。

    bars<20 返 None（诚实降级，不臆造）。
    """
    if not bars or len(bars) < 20:
        return None
    try:
        closes = [float(b.get("close", 0)) for b in bars[-n:]]
        if len(closes) < n or any(c <= 0 for c in closes if c is not None):
            return None
        return round(sum(closes) / n, 4)
    except (ValueError, TypeError):
        return None


def check_ma_bullish(bars: list[dict]) -> bool:
    """均线多头排列：MA5 > MA10 > MA20（spec §5.5）。

    S094 R1：改用 _compute_ma 自算（不依赖 cache ma5/ma10/ma20 字段——
    baostock cache 无此字段致旧实现恒 False 的 bug 一并修复）。
    """
    if not bars or len(bars) < 20:
        return False
    ma5 = _compute_ma(bars, 5)
    ma10 = _compute_ma(bars, 10)
    ma20 = _compute_ma(bars, 20)
    if None in (ma5, ma10, ma20):
        return False
    return ma5 > ma10 > ma20


def compute_ma5_proximity(bars: list[dict]) -> float | None:
    """MA5 接近度：|close - MA5| / MA5 * 100（spec §5.5 低吸龙头用）。

    S094 R1：MA5 改用 _compute_ma 自算（不依赖 cache ma5 字段）。
    值越小 → 股价越接近 MA5（低吸入场点）。
    """
    if not bars or len(bars) < 20:
        return None
    last = bars[-1]
    close = last.get("close")
    if close is None:
        return None
    ma5 = _compute_ma(bars, 5)
    if ma5 is None:
        return None
    try:
        close_f = float(close)
        if ma5 <= 0:
            return None
        return round(abs(close_f - ma5) / ma5 * 100, 4)
    except (ValueError, TypeError):
        return None


def compute_shadow_length_pct(bars: list[dict]) -> float | None:
    """S094 R5：上影线长度 = (high[-1] / close[-1] - 1) * 100。

    复用 candidate_funnel/sources/activity.py L112-114 同款口径。
    PatternReversal 长上影洗盘修复形态用（shadow_length_pct>=4 命中）。
    """
    if not bars:
        return None
    last = bars[-1]
    high = last.get("high")
    close = last.get("close")
    if None in (high, close):
        return None
    try:
        high_f = float(high)
        close_f = float(close)
        if close_f <= 0:
            return None
        return round((high_f / close_f - 1) * 100, 4)
    except (ValueError, TypeError):
        return None


def compute_ma5_slope(bars: list[dict]) -> float | None:
    """S094 R5：MA5 斜率 = (ma5[-1] - ma5[-2]) / ma5[-2]。

    ma5 用 _compute_ma 自算（R1）。slope>0 即"5 日线向上"。
    PatternReversal 形态用（ma5_slope>0 命中）。
    """
    if not bars or len(bars) < 21:  # 需 [-1] 与 [-2] 各 5 根，重叠可取，但需 ≥20 根
        return None
    # 昨日截止的 5 日均线 = bars[-6:-1] 的 SMA
    try:
        closes_prev = [float(b.get("close", 0)) for b in bars[-6:-1]]
        closes_now = [float(b.get("close", 0)) for b in bars[-5:]]
        if len(closes_prev) < 5 or len(closes_now) < 5:
            return None
        ma5_prev = sum(closes_prev) / 5
        ma5_now = sum(closes_now) / 5
        if ma5_prev <= 0:
            return None
        return round((ma5_now - ma5_prev) / ma5_prev, 6)
    except (ValueError, TypeError, IndexError):
        return None


def compute_consolidation(bars: list[dict], threshold: float = 8.0, min_days: int = 5) -> tuple[int | None, float | None]:
    """横盘形态：N 日振幅 < 阈值（spec §5.5）。

    从最后一天往前找连续满足振幅 < threshold 的天数。
    返回 (横盘天数, 区间振幅%)。
    """
    if len(bars) < min_days:
        return None, None

    # 从最后一天往前找
    consolidation_days = 0
    window_start = len(bars) - 1

    while window_start >= 0:
        window = bars[max(0, window_start - min_days + 1): window_start + 1]
        if len(window) < min_days:
            break
        highs = [float(b.get("high", 0)) for b in window if b.get("high")]
        lows = [float(b.get("low", 0)) for b in window if b.get("low")]
        if not highs or not lows:
            break
        max_high = max(highs)
        min_low = min(lows)
        if min_low <= 0:
            break
        amplitude = (max_high - min_low) / min_low * 100
        if amplitude < threshold:
            consolidation_days += 1
            window_start -= 1
        else:
            break

    if consolidation_days == 0:
        return 0, None

    # 计算横盘区间振幅
    window = bars[len(bars) - consolidation_days:]
    if len(window) < 2:
        return consolidation_days, None
    highs = [float(b.get("high", 0)) for b in window if b.get("high")]
    lows = [float(b.get("low", 0)) for b in window if b.get("low")]
    if not highs or not lows or min(lows) <= 0:
        return consolidation_days, None
    amplitude = (max(highs) - min(lows)) / min(lows) * 100
    return consolidation_days, round(amplitude, 4)


def compute_volume_breakout(bars: list[dict], lookback: int = 5) -> float | None:
    """量比突破：当日成交量 / 前 N 日平均成交量（spec §5.5）。

    值 > 2 = 放量突破。
    """
    if len(bars) < lookback + 1:
        return None
    try:
        current_vol = float(bars[-1].get("volume", 0))
        prev_vols = [float(bars[i].get("volume", 0)) for i in range(-lookback - 1, -1)]
        avg_prev = sum(prev_vols) / len(prev_vols) if prev_vols else 0
        if avg_prev <= 0:
            return None
        return round(current_vol / avg_prev, 4)
    except (ValueError, TypeError, IndexError):
        return None


def compute_amount_yi(bars: list[dict]) -> float | None:
    """成交额（亿）。"""
    if not bars:
        return None
    try:
        amt = float(bars[-1].get("amount", 0))
        return round(amt / 1e8, 4)
    except (ValueError, TypeError):
        return None


def scan_patterns(code: str, bars: list[dict], sector_bars: list[dict] | None = None) -> PatternScan:
    """个股形态完整扫描（spec §5.5/P2-2）。

    bars: kline_multi 返回（含 ma5/ma10/ma20/amount/volume）
    sector_bars: 板块成分股等权平均日K（可选）
    """
    rel_str = compute_relative_strength(bars, sector_bars)
    ma_bull = check_ma_bullish(bars)
    ma5_prox = compute_ma5_proximity(bars)
    cons_days, cons_amp = compute_consolidation(bars)
    vol_breakout = compute_volume_breakout(bars)
    amt_yi = compute_amount_yi(bars)
    # S094 R5：PatternReversal 长上影洗盘修复形态因子
    shadow_pct = compute_shadow_length_pct(bars)
    ma5_slp = compute_ma5_slope(bars)

    return PatternScan(
        code=code,
        relative_strength=rel_str,
        ma_bullish=ma_bull,
        ma5_proximity=ma5_prox,
        consolidation_days=cons_days,
        consolidation_amplitude=cons_amp,
        volume_breakout_ratio=vol_breakout,
        amount_yi=amt_yi,
        shadow_length_pct=shadow_pct,
        ma5_slope=ma5_slp,
    )
