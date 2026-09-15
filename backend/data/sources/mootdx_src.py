# -*- coding: utf-8 -*-
"""S008 mootdx 惰性源（K线 / 财务快照）。

从 ``astock.py`` 迁出（Layer mootdx）。mootdx 缺失时 ``_mootdx_client`` 抛
``DependencyMissing``。取数逻辑一字不改。

注：mootdx ``finance()`` 营收/净利数值不可靠（实测放大数倍），财务摘要走
``akshare_src.financials``——故本模块只暴露 K线 与 原始财务快照。
"""

from __future__ import annotations

import logging

from ._common import DependencyMissing


def _mootdx_client():
    try:
        from mootdx.quotes import Quotes
        return Quotes.factory(market="std")
    except ImportError as e:
        raise DependencyMissing("mootdx 未安装：pip install mootdx") from e


def _get_mootdx_client():
    """动态获取，支持 astock._mootdx_client monkeypatch（测试用）。"""
    import astock as _astock
    return getattr(_astock, '_mootdx_client', _mootdx_client)


# mootdx bars frequency 映射（mootdx 用 frequency 非 category）：4=日 5=周 6=月 3=60min
# 外部 kline(category=) 透传到此映射。category 11（60min）→ frequency 3。
_CAT2FREQ: dict[int, int] = {4: 4, 5: 5, 6: 6, 11: 3}


def kline(code: str, category: int = 4, offset: int = 60) -> list[dict]:
    """K线：category 4=日 5=周 6=月 11=60分钟。

    mootdx bars 用 frequency 参数（非 category）——经 _CAT2FREQ 映射透传。
    S206: mootdx bars 接口实测返空（库/数据源问题）→ 加 baostock 日 K 回退（category=4 时）。
    baostock 日 K 数据可信（qfq 前复权），mootdx 坏时不致 cockpit 无 K 线。
    """
    try:
        client = _get_mootdx_client()()
        df = client.bars(symbol=code, frequency=_CAT2FREQ.get(category, 4), offset=offset)
    except (TypeError, ValueError, KeyError, AttributeError) as e:
        # mootdx 连不上/空返回裸解包（如 "not enough values to unpack"）→ 视作无数据
        logging.getLogger("astock").warning("kline(%s) mootdx 解析失败: %s", code, e)
        df = None
    rows = df.to_dict("records") if df is not None and not df.empty else []
    # S206: mootdx 返空 → baostock 日 K 回退（category=4 日线）
    if not rows and category == 4:
        try:
            from datetime import datetime, timedelta
            from data.sources.baostock_src import fetch_daily_bars
            end = datetime.now().strftime("%Y-%m-%d")
            start = (datetime.now() - timedelta(days=offset * 2)).strftime("%Y-%m-%d")  # offset*2 容纳周末
            bars = fetch_daily_bars(code, start, end)
            if bars:
                bars = bars[-offset:] if len(bars) > offset else bars
                logging.getLogger("astock").info("kline(%s) mootdx 空→baostock 回退 %d bars", code, len(bars))
                return bars
        except Exception as e:
            logging.getLogger("astock").warning("kline(%s) baostock 回退失败: %s", code, e)
    return rows


def finance(code: str) -> dict:
    """季报财务快照（37 字段，mootdx——数值不可靠，仅作原始快照）。"""
    try:
        client = _get_mootdx_client()()
        df = client.finance(symbol=code)
    except (TypeError, ValueError, KeyError, AttributeError) as e:
        logging.getLogger("astock").warning("finance(%s) mootdx 解析失败: %s", code, e)
        return {}
    if df is None or (hasattr(df, "empty") and df.empty):
        return {}
    return df.to_dict("records")[0] if hasattr(df, "to_dict") else dict(df)
