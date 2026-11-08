# -*- coding: utf-8 -*-
"""S243 运维 yield 数据源——GC001 逆回购 + CB 可转债信用申购。

散户结构性 yield（非选股 alpha）：
- GC001（沪市国债逆回购 sh204001）：底仓闲置资金尾盘 sweep，零风险 2-3%/年，季末飙升 5-15%
- CB 信用申购：零成本（信用申购无市值要求），AA+ 首日 +18.7%

数据源：akshare bond_zh_hs_cov_min（GC001 实时）+ bond_zh_cov（CB 全市场）。
走东财 datacenter（非 push2his，低封禁）+ cache_response ttl + 熔断器（§1.2 防封）。
"""
from __future__ import annotations

import logging
from datetime import datetime, date
from typing import Any

from circuit_breaker import get_breaker

logger = logging.getLogger("vibe-research")

_GC001_SYMBOL = "sh204001"  # 沪市 1 日国债逆回购（GC001）
_CB_CACHE_TTL = 3600  # CB 列表 1h cache（日内不变）
_REPO_CACHE_TTL = 60  # GC001 实时 1min cache


def is_quarter_end(d: date | None = None) -> bool:
    """当日是否季末/年末月（3/6/9/12 月末交易日）——逆回购高息日。"""
    d = d or date.today()
    return d.month in (3, 6, 9, 12)


def is_month_end(d: date | None = None) -> bool:
    """当月最后交易日（近似：月末日±1）——月末逆回购利率常升。"""
    d = d or date.today()
    # 月末：当天是本月最后 7 天内（近似，盘后盘前都算）
    import calendar
    last_day = calendar.monthrange(d.year, d.month)[1]
    return d.day >= last_day - 2  # 末 3 天（含盘前盘后）


def get_gc001_rate() -> dict[str, Any]:
    """GC001 实时年化利率。返 {rate, high, low, time, quarter_end, month_end}。
    akshare bond_zh_hs_cov_min(sh204001) 返回分钟数据，取最新收盘=当前年化利率(%)。"""
    breaker = get_breaker("eastmoney")
    if not breaker.allow_request():
        logger.warning("[yield] eastmoney 熔断中，GC001 跳过")
        return {"rate": None, "error": "circuit_open"}
    try:
        import akshare as ak  # noqa: PLC0415
        df = ak.bond_zh_hs_cov_min(symbol=_GC001_SYMBOL)
        breaker.record_success()
        if df is None or len(df) == 0:
            return {"rate": None, "error": "empty"}
        last = df.iloc[-1]
        rate = float(last.get("收盘", 0) or 0)
        return {
            "symbol": _GC001_SYMBOL,
            "rate": rate,  # 年化 %
            "high": float(last.get("最高", 0) or 0),
            "low": float(last.get("最低", 0) or 0),
            "time": str(last.get("时间", "")),
            "quarter_end": is_quarter_end(),
            "month_end": is_month_end(),
            "threshold": 3.0,  # 提醒阈值：>3% 平日也提醒
        }
    except Exception as e:
        breaker.record_failure()
        logger.warning("[yield] GC001 fetch err: %s", repr(e)[:120])
        return {"rate": None, "error": str(e)[:80]}


def get_cb_list() -> list[dict[str, Any]]:
    """CB 全市场列表（bond_zh_cov）。返 [{code, name, 申购日/上市日, ...}]。
    用于信用申购日历——当日有申购的 CB。"""
    breaker = get_breaker("eastmoney")
    if not breaker.allow_request():
        return []
    try:
        import akshare as ak  # noqa: PLC0415
        df = ak.bond_zh_cov()
        breaker.record_success()
        if df is None or len(df) == 0:
            return []
        # 列名可能含：债券代码/债券简称/申购日/上市日/发行规模 等
        rows: list[dict[str, Any]] = []
        for _, r in df.iterrows():
            rows.append({
                "code": str(r.get("债券代码", r.get("代码", ""))),
                "name": str(r.get("债券简称", r.get("名称", ""))),
                "subscribe_date": str(r.get("申购日", r.get("申购日期", "")))[:10],
                "list_date": str(r.get("上市日", r.get("上市日期", "")))[:10],
            })
        return rows
    except Exception as e:
        breaker.record_failure()
        logger.warning("[yield] CB fetch err: %s", repr(e)[:120])
        return []


def get_today_cb_subscriptions() -> list[dict[str, Any]]:
    """今日申购的 CB 列表（用于 09:15 提醒）。"""
    today = date.today().isoformat()
    cbs = get_cb_list()
    return [c for c in cbs if c.get("subscribe_date") == today]


def get_today_ipos() -> list[dict[str, Any]]:
    """今日申购新股列表（stock_xgsglb_em）+ 打新筛选红线。
    筛选规则（避雷降破发损失，非选 alpha）：
    - 发行 PE vs 行业 PE：PE_ratio = 发行PE/行业PE。>1.5 标"高溢价高风险"，<1 标"折价较安全"
    - 标注中签率 + 顶格市值 + 板块（北交所流动性差标注）
    返 [{code, name, subscribe_code, price, pe, industry_pe, pe_ratio, win_rate, board, risk_flag}]。
    """
    breaker = get_breaker("eastmoney")
    if not breaker.allow_request():
        return []
    try:
        import akshare as ak  # noqa: PLC0415
        df = ak.stock_xgsglb_em()
        breaker.record_success()
        if df is None or len(df) == 0:
            return []
        today = date.today()
        rows: list[dict[str, Any]] = []
        for _, r in df.iterrows():
            sub_date = r.get("申购日期")
            # 申购日期可能是 datetime.date 或 str
            sub_str = ""
            if hasattr(sub_date, "isoformat"):
                sub_str = sub_date.isoformat()
            elif sub_date is not None:
                sub_str = str(sub_date)[:10]
            if sub_str != today.isoformat():
                continue
            code = str(r.get("股票代码", ""))
            name = str(r.get("股票简称", ""))
            try:
                pe = float(r.get("发行市盈率", 0) or 0)
            except (ValueError, TypeError):
                pe = 0
            try:
                ind_pe = float(r.get("行业市盈率", 0) or 0)
            except (ValueError, TypeError):
                ind_pe = 0
            pe_ratio = pe / ind_pe if ind_pe > 0 else None
            try:
                win_rate = float(r.get("中签率", 0) or 0)
            except (ValueError, TypeError):
                win_rate = 0
            board = str(r.get("板块", r.get("交易所", "")))
            # 风险标注
            risk_flag = ""
            if pe_ratio and pe_ratio > 1.5:
                risk_flag = "🔴高溢价(发行PE/行业PE=%.2f 破发风险)" % pe_ratio
            elif pe_ratio and pe_ratio < 1.0:
                risk_flag = "🟢折价(PE/行业=%.2f 较安全)" % pe_ratio
            if "北交所" in board or code.startswith(("8", "4", "920")):
                risk_flag = (risk_flag + " " if risk_flag else "") + "⚠北交所(流动性差)"
            rows.append({
                "code": code, "name": name,
                "subscribe_code": str(r.get("申购代码", code)),
                "price": float(r.get("发行价格", 0) or 0),
                "pe": pe, "industry_pe": ind_pe, "pe_ratio": round(pe_ratio, 2) if pe_ratio else None,
                "win_rate": win_rate, "board": board, "risk_flag": risk_flag,
                "subscribe_date": sub_str,
            })
        return rows
    except Exception as e:
        breaker.record_failure()
        logger.warning("[yield] IPO fetch err: %s", repr(e)[:120])
        return []
