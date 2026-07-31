# -*- coding: utf-8 -*-
"""S008 百度股市通日K线源（urllib 底座，不封 IP）。

公司网对东财 ``push2his.eastmoney.com``（``ak.stock_zh_a_hist`` 端点）IP-封禁，
对新浪/百度日K线不限流（2026-07-31 工作流实测）。百度股市通是当前**唯一可靠
且不限流的个股日K线源**，直接解 S017 panel OOS 的 kline 阻塞；且自带 ma5/ma10/ma20
均价，免本地重算移动平均。

公开：
- ``fetch_raw(code, start_time="")``：单股票日K线，返 **parsed raw bars**（``list[dict]``，
  形状与 ``data.sources.mootdx_src.kline`` 一致），每 bar 含
  ``date/open/close/high/low/volume/amount/ma5/ma10/ma20``，缺字段=``None``（不臆造）。
- ``_fetch_json``：薄 urllib 请求层（测试 monkeypatch 点），返百度原始 JSON dict。

异构接口：legacy 消费者经 ``astock.baidu_kline`` 拿 raw bars（全字段，不丢）；
新消费者经 ``data.mappers.baidu_kline_from_dict(raw)`` 拿 ``KLine`` 模型。

合规：本模块只按用户传入的代码返回客观数据，不预置标的、不排名、不建议。

NO-LOOK-AHEAD：日K线是已实现的历史收盘，``date`` 为交易日；不涉及未来数据。
"""
from __future__ import annotations

import json
import urllib.request
from datetime import datetime, timezone, timedelta

from ._common import UA

# 百度股市通日K线端点
_BAIDU_KLINE_URL = "https://finance.pae.baidu.com/selfselect/getstockquotation"

# 字段名 → 归一化键（百度原始 key → 本模块 raw bar key）。
# 实测百度 schema：keys 含 ``timestamp``（unix 秒 CST）与 ``time``（YYYY-MM-DD 日期串），
# 无 ``date`` key。``time`` 实为日期串，``timestamp`` 是其秒数表示。
_KEY_MAP = {
    "timestamp": "time",     # unix 秒（CST）— date 缺失时的回退源
    "time": "date",          # YYYY-MM-DD 日期串（百度 time 字段实为日期）
    "date": "date",
    "open": "open",
    "close": "close",
    "high": "high",
    "low": "low",
    "volume": "volume",
    "amount": "amount",
    "ma5avgprice": "ma5",
    "ma10avgprice": "ma10",
    "ma20avgprice": "ma20",
}

_CST = timezone(timedelta(hours=8))


def _fetch_json(code: str, start_time: str = "") -> dict:
    """百度股市通日K线原始 JSON。urllib 不封 IP；timeout 30s（公司代理预热 ~12s 留余量）。"""
    params = {
        "all": "1", "isIndex": "false", "isBk": "false", "isBlock": "false",
        "isFutures": "false", "isStock": "true", "newFormat": "1",
        "group": "quotation_kline_ab", "finClientType": "pc",
        "code": code, "start_time": start_time, "ktype": "1",
    }
    from urllib.parse import urlencode
    url = _BAIDU_KLINE_URL + "?" + urlencode(params)
    headers = {
        "User-Agent": UA,
        "Accept": "application/vnd.finance-web.v1+json",
        "Origin": "https://gushitong.baidu.com",
        "Referer": "https://gushitong.baidu.com/",
    }
    req = urllib.request.Request(url, headers=headers)
    with urllib.request.urlopen(req, timeout=30) as resp:
        return json.loads(resp.read().decode("utf-8"))


def _num(v: str) -> float | None:
    """字符串值 → float；空/'-' → None（不臆造 0）。"""
    if v is None:
        return None
    s = v.strip()
    if not s or s in ("-", "--"):
        return None
    try:
        return float(s)
    except ValueError:
        return None


def _date_from_time(ts: str) -> str | None:
    """unix 秒（CST）→ YYYY-MM-DD。百度 time 字段是 CST 当日 00:00 的秒数。"""
    n = _num(ts)
    if n is None:
        return None
    return datetime.fromtimestamp(n, tz=_CST).strftime("%Y-%m-%d")


def _parse(keys: list[str], market_data: str) -> list[dict]:
    """keys + ';'-分隔的 marketData 串 → parsed raw bars list[dict]。

    按 key 名索引（顺序无关）：每个 ','-联接的行与 keys zip 成 dict，再按
    ``_KEY_MAP`` 归一化字段名。字段不足的行（len < len(keys)）跳过。
    date 优先取 date key，否则从 time(unix 秒) 按 CST 转 YYYY-MM-DD。
    """
    if not keys or not market_data:
        return []
    # 归一化 key → 目标 key，未知 key 保留原名供调试
    target_keys = [_KEY_MAP.get(k, k) for k in keys]
    bars: list[dict] = []
    for line in market_data.split(";"):
        line = line.strip()
        if not line:
            continue
        vals = line.split(",")
        if len(vals) < len(keys):
            continue  # 字段不足 → 跳过（不臆造）
        row = dict(zip(target_keys, vals))
        bar: dict = {}
        for k in ("open", "close", "high", "low", "amount", "ma5", "ma10", "ma20"):
            bar[k] = _num(row.get(k))
        # volume → int or None
        vnum = _num(row.get("volume"))
        bar["volume"] = int(vnum) if vnum is not None else None
        # date：优先 date key，否则从 time 转
        d = row.get("date")
        if d and d.strip():
            bar["date"] = d.strip()
        else:
            bar["date"] = _date_from_time(row.get("time"))
        bars.append(bar)
    return bars


def fetch_raw(code: str, start_time: str = "") -> list[dict]:
    """单股票百度日K线 raw bars。

    返 ``list[dict]``，每 bar 含
    ``date/open/close/high/low/volume/amount/ma5/ma10/ma20``；缺字段=``None``。
    ``astock.baidu_kline`` 门面直接返本结果；``mappers.baidu_kline_from_dict``
    从本结果投影 ``KLine`` 模型。
    """
    d = _fetch_json(code, start_time)
    result = d.get("Result", {}) or {}
    md = result.get("newMarketData", {}) or {}
    keys = md.get("keys", []) or []
    rows = md.get("marketData", "") or ""
    return _parse(keys, rows)
