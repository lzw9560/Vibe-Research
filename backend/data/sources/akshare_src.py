# -*- coding: utf-8 -*-
"""S008 akshare 惰性源（一致预期 / 新闻 / 公告 / 基本面 / 估值分位）。

从 ``astock.py`` 迁出（Layer 3/4/5）。akshare 缺失时 ``_akshare`` 抛
``DependencyMissing``，前端据此提示安装。取数逻辑一字不改。

注意：``disclosure`` 走 akshare 的 cninfo 包装（巨潮公告全文）；``financials``
走同花顺财务摘要；``valuation_percentile`` 走百度股市通。
"""

from __future__ import annotations

import logging

from ._common import DependencyMissing


def _akshare():
    try:
        import akshare as ak
        return ak
    except ImportError as e:
        raise DependencyMissing("akshare 未安装：pip install akshare") from e


def profit_forecast(code: str) -> list[dict]:
    """机构一致预期 EPS（同花顺）。"""
    ak = _akshare()
    df = ak.stock_profit_forecast_ths(symbol=code, indicator="预测年报每股收益")
    return df.to_dict("records") if df is not None and not df.empty else []


def stock_news(code: str, limit: int = 20) -> list[dict]:
    """个股新闻（东财）。"""
    ak = _akshare()
    df = ak.stock_news_em(symbol=code)
    return df.head(limit).to_dict("records") if df is not None and not df.empty else []


def individual_info(code: str) -> dict:
    """个股基本面（东财）：行业 / 总股本 / 上市时间等。"""
    ak = _akshare()
    df = ak.stock_individual_info_em(symbol=code)
    if df is None or df.empty:
        return {}
    return {str(row["item"]): row["value"] for _, row in df.iterrows()}


def disclosure(code: str) -> list[dict]:
    """巨潮公告全文列表（akshare cninfo，本环境不稳，保留作备用）。"""
    ak = _akshare()
    market = "沪市" if code.startswith("6") else ("北交所" if code.startswith("8") else "深市")
    try:
        df = ak.stock_zh_a_disclosure_report_cninfo(symbol=code, market=market)
    except (TypeError, ValueError, KeyError, AttributeError) as e:
        # akshare 对异常返回裸解包（如 "string indices must be integers"）→ 视作无数据
        logging.getLogger("astock").warning("disclosure(%s) akshare 解析失败: %s", code, e)
        return []
    return df.head(30).to_dict("records") if df is not None and not df.empty else []


def financials(code: str) -> dict:
    """财务关键指标（同花顺财务摘要，最新报告期）—— 干净可靠的营收/净利/ROE/毛利率等。

    注：mootdx finance() 的营收/净利数值不可靠(实测放大数倍)，故财务摘要走此源。
    """
    ak = _akshare()
    df = ak.stock_financial_abstract_ths(symbol=code, indicator="按报告期")
    if df is None or df.empty:
        return {}
    row = df.iloc[-1].to_dict()  # 最新报告期（按报告期升序，取末行）

    def g(k):
        v = row.get(k)
        return None if v in (False, "false", "", None) else v

    return {
        "period": g("报告期"),
        "revenue": g("营业总收入"), "revenue_yoy": g("营业总收入同比增长率"),
        "net_profit": g("净利润"), "net_profit_yoy": g("净利润同比增长率"),
        "eps": g("基本每股收益"), "bvps": g("每股净资产"),
        "roe": g("净资产收益率"), "gross_margin": g("销售毛利率"), "net_margin": g("销售净利率"),
        "op_cf_ps": g("每股经营现金流"),
    }


def valuation_percentile(code: str, period: str = "近五年") -> dict:
    """历史估值分位（百度股市通）：PE-TTM / PB 的当前值 + 历史 20/50/80 分位带 + 所处分位。

    只表达"处于历史什么位置"，不划买卖线（理杏仁式中立呈现）。
    """
    ak = _akshare()

    def _q(vals: list, p: float) -> float:
        if not vals:
            return 0.0
        idx = p * (len(vals) - 1)
        lo = int(idx)
        if lo + 1 >= len(vals):
            return vals[-1]
        frac = idx - lo
        return vals[lo] * (1 - frac) + vals[lo + 1] * frac

    metrics = {}
    for key, ind in (("pe_ttm", "市盈率(TTM)"), ("pb", "市净率")):
        try:
            df = ak.stock_zh_valuation_baidu(symbol=code, indicator=ind, period=period)
            raw = df.iloc[:, 1].dropna().astype(float).tolist()
            if not raw:
                continue
            cur = float(raw[-1])
            s = sorted(raw)
            below = sum(1 for x in s if x < cur)
            metrics[key] = {
                "current": round(cur, 2),
                "percentile": round(below / max(len(s) - 1, 1) * 100, 1),
                "min": round(s[0], 2), "max": round(s[-1], 2),
                "p20": round(_q(s, 0.2), 2), "p50": round(_q(s, 0.5), 2), "p80": round(_q(s, 0.8), 2),
                "n": len(s),
            }
        except Exception:
            continue
    return {"period": "近5年", "metrics": metrics}


def chip_distribution(code: str) -> dict:
    """筹码分布（东财 stock_cyq_em，最新交易日）—— 获利比例 / 平均成本 / 集中度 / 90%&70%成本。

    S085 D3：接通 IndicatorSet.chip_profit_ratio（此前恒 None）。
    返回字段映射：
      - chip_profit_ratio: 获利比例（0-100）
      - avg_cost: 平均成本
      - concentration: 集中度
      - 90_cost / 70_cost: 90%成本-70%成本区间上下沿
    akshare 缺失抛 DependencyMissing；取数异常返回空 dict {}（不臆造，遵循项目红线 AC6）。
    """
    ak = _akshare()
    try:
        df = ak.stock_cyq_em(symbol=code)
    except Exception as e:
        logging.getLogger("astock").warning("chip_distribution(%s) akshare 取数失败: %s", code, e)
        return {}
    if df is None or df.empty:
        return {}
    row = df.iloc[-1].to_dict()

    def g(k):
        v = row.get(k)
        return None if v in (False, "false", "", None, "-", "--") else v

    return {
        "chip_profit_ratio": g("获利比例"),
        "avg_cost": g("平均成本"),
        "concentration": g("集中度"),
        "90_cost": g("90成本-70成本"),
        "70_cost": g("70成本-90成本"),
    }
