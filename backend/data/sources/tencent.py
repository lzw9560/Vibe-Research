# -*- coding: utf-8 -*-
"""S008 腾讯行情源（urllib 底座，不封 IP）。

从 ``astock.py`` 迁出（Layer 1）。取数与解析逻辑一字不改，仅换文件组织。

公开：
- ``fetch_raw(codes)``：批量个股实时行情，返**全字段 raw dict**（含
  ``last_close/open/high/low/vol_ratio/pe_static`` 等）——单一事实源，不丢字段。
- ``index_raw()``：A股大盘指数实时行情。

异构接口：legacy 消费者经 ``astock.tencent_quote`` 拿 raw（全字段）；
新消费者经 ``data.mappers.quote_from_tencent(raw)`` 拿 ``Quote`` 模型。
两条投影都从本模块的 raw 直接派生，**不互相往返**（避免有损字段丢失）。
"""

from __future__ import annotations

import urllib.request

from ._common import UA


def get_prefix(code: str) -> str:
    """6 位代码 → 交易所前缀。5 开头是沪市基金/ETF（51/56/58 等），深市基金 15/16 开头走默认 sz。"""
    if code.startswith(("6", "9", "5")):
        return "sh"
    if code.startswith("8"):
        return "bj"
    return "sz"


def _fetch_gtimg(prefixed_codes: list[str]) -> str:
    url = "https://qt.gtimg.cn/q=" + ",".join(prefixed_codes)
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=10) as resp:
        return resp.read().decode("gbk")


def _parse_gtimg(data: str) -> dict[str, dict]:
    result: dict[str, dict] = {}
    for line in data.strip().split(";"):
        if not line.strip() or "=" not in line or '"' not in line:
            continue
        key = line.split("=")[0].split("_")[-1]
        vals = line.split('"')[1].split("~")
        if len(vals) < 53:
            continue
        code = key[2:]

        def num(i: int) -> float:
            try:
                return float(vals[i]) if vals[i] else 0.0
            except (ValueError, IndexError):
                return 0.0

        result[code] = {
            "name": vals[1],
            "price": num(3),
            "last_close": num(4),
            "open": num(5),
            "change_amt": num(31),
            "change_pct": num(32),
            "high": num(33),
            "low": num(34),
            "amount_wan": num(37),
            "turnover_pct": num(38),
            "pe_ttm": num(39),
            "amplitude_pct": num(43),
            "mcap_yi": num(44),
            "float_mcap_yi": num(45),
            "pb": num(46),
            "limit_up": num(47),
            "limit_down": num(48),
            "vol_ratio": num(49),
            "pe_static": num(52),
        }
    return result


def fetch_raw(codes: list[str]) -> dict[str, dict]:
    """批量个股实时行情：现价 / 涨跌 / PE / PB / 市值 / 换手 / 涨跌停 / 量比。

    返全字段 raw dict（单一事实源）。``astock.tencent_quote`` 门面直接返本结果，
    28 个消费者不改；``mappers.quote_from_tencent`` 从本结果投影 ``Quote`` 模型。
    """
    prefixed = [f"{get_prefix(c)}{c}" for c in codes]
    return _parse_gtimg(_fetch_gtimg(prefixed))


# A股大盘指数（前缀规则与个股不同，固定带前缀代码）
A_INDICES = ["sh000001", "sz399001", "sz399006", "sh000300"]


def index_raw() -> list[dict]:
    """A股大盘指数实时行情（上证/深证成指/创业板指/沪深300）。"""
    parsed = _parse_gtimg(_fetch_gtimg(A_INDICES))
    out = []
    for full in A_INDICES:
        q = parsed.get(full[2:])
        if q:
            out.append({"name": q["name"], "price": q["price"], "change_pct": q["change_pct"], "change_amt": q["change_amt"]})
    return out
