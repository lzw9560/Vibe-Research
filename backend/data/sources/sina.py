# -*- coding: utf-8 -*-
"""S008 新浪日K线源（urllib 底座，不封 IP 但首次慢 ~12s 代理预热）。

作为百度源的**异构回退**：公司网对东财 push2his kline IP-封禁，对新浪/百度
不限流（2026-07-31 实测）。多源回退链 ``baidu → sina → mootdx → akshare``
保证不同网络环境（开发/家庭/VPN/远程）下至少一个源可达——不硬编码任何单源策略。

公开：
- ``fetch_raw(code, datalen=1023)``：单股票日K线，返 parsed raw bars
  ``list[dict]``，每 bar 含 ``date/open/high/low/close/volume``（无 MA，ma5/ma10/ma20=None）。
- ``_fetch_json``：薄 urllib 请求层（测试 monkeypatch 点）。

合规：只按用户传入代码返回客观数据，不预置标的、不排名、不建议。
NO-LOOK-AHEAD：日K线是已实现历史收盘，不涉及未来数据。
"""
from __future__ import annotations

import json
import urllib.request

from circuit_breaker import get_breaker

from ._common import UA
from .tencent import get_prefix

_SINA_KLINE_URL = ("https://money.finance.sina.com.cn/quotes_service/api/"
                   "json_v2.php/CN_MarketData.getKLineData")

# S134：新浪日K熔断（默认 config——kline_resolver 有 mootdx/akshare 回退，
# 降 threshold 反易误 trip 抖动；default 足够）。first-write-wins 注入。
_SINA_KLINE_BREAKER = get_breaker("sina_kline")


def _fetch_json(code: str, datalen: int = 1023) -> list[dict]:
    """新浪日K线原始 JSON（list[dict]，字段为字符串）。urllib 不封 IP；timeout 30s。"""
    prefix = get_prefix(code)
    from urllib.parse import urlencode
    params = {
        "symbol": f"{prefix}{code}",
        "scale": "240",     # 240 分钟 = 日线
        "ma": "no",
        "datalen": str(datalen),
    }
    url = _SINA_KLINE_URL + "?" + urlencode(params)
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=30) as resp:
        return json.loads(resp.read().decode("utf-8"))


def _num(v) -> float | None:
    if v is None:
        return None
    s = str(v).strip()
    if not s or s in ("-", "--"):
        return None
    try:
        return float(s)
    except ValueError:
        return None


def _parse(raw_rows: list[dict]) -> list[dict]:
    """新浪 raw list[dict]（字符串字段）→ parsed raw bars（数值字段，缺=None）。"""
    bars: list[dict] = []
    for r in raw_rows or []:
        vnum = _num(r.get("volume"))
        bars.append({
            "date": (str(r.get("day")).strip() if r.get("day") else None),
            "open": _num(r.get("open")),
            "high": _num(r.get("high")),
            "low": _num(r.get("low")),
            "close": _num(r.get("close")),
            "volume": int(vnum) if vnum is not None else None,
            "amount": None,            # 新浪日K不带成交额
            "ma5": None, "ma10": None, "ma20": None,  # 新浪不带 MA
        })
    return bars


def fetch_raw(code: str, datalen: int = 1023) -> list[dict]:
    """单股票新浪日K线 raw bars（无 MA）。

    返 ``list[dict]``，每 bar 含 ``date/open/high/low/close/volume``，
    ``amount/ma5/ma10/ma20=None``。作为 ``baidu.fetch_raw`` 的异构回退。

    S134：顶加 sina_kline 熔断——OPEN fast-fail（raise RuntimeError，被
    kline_resolver except 吞成回退下一源）；_fetch_json raise →
    record_failure + re-raise；正常返 → record_success + 返 _parse 结果。
    """
    breaker = get_breaker("sina_kline")
    if not breaker.allow_request():
        raise RuntimeError(
            f"[CircuitBreaker:sina_kline] 新浪日K线源熔断中，快速失败（{code}）"
        )
    try:
        raw_rows = _fetch_json(code, datalen)
        breaker.record_success()
    except Exception:
        breaker.record_failure()
        raise
    return _parse(raw_rows)
