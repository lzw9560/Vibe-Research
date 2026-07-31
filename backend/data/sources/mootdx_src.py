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


def kline(code: str, category: int = 4, offset: int = 60) -> list[dict]:
    """K线：category 4=日 5=周 6=月 11=60分钟。"""
    try:
        client = _mootdx_client()
        df = client.bars(symbol=code, category=category, offset=offset)
    except (TypeError, ValueError, KeyError, AttributeError) as e:
        # mootdx 连不上/空返回裸解包（如 "not enough values to unpack"）→ 视作无数据
        logging.getLogger("astock").warning("kline(%s) mootdx 解析失败: %s", code, e)
        return []
    return df.to_dict("records") if df is not None and not df.empty else []


def finance(code: str) -> dict:
    """季报财务快照（37 字段，mootdx——数值不可靠，仅作原始快照）。"""
    try:
        client = _mootdx_client()
        df = client.finance(symbol=code)
    except (TypeError, ValueError, KeyError, AttributeError) as e:
        logging.getLogger("astock").warning("finance(%s) mootdx 解析失败: %s", code, e)
        return {}
    if df is None or (hasattr(df, "empty") and df.empty):
        return {}
    return df.to_dict("records")[0] if hasattr(df, "to_dict") else dict(df)
