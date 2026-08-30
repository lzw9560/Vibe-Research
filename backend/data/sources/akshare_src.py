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

# S114：chip_distribution 自建取数走 em_get（push2his kline/get + ut=_ZTB_UT 日K token），
# 不再直调 ak.stock_cyq_em 黑盒。em_get 自带 breaker('eastmoney') + 限流 + 代理探测 + UA
# （对齐 hot_money_seats 复用 breaker('eastmoney') 范式，不臆造新 chip breaker——
# _CHIP_BREAKER_NAME/_CHIP_BREAKER_CONFIG 冗余已删，R8 精简）。计算层保真复用东财原 JS（cyq_js.CYQ_JS）。


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


def _fetch_cyq_klines(code: str) -> list[dict] | None:
    """em_get 拉东财日 K + 换手率（push2his kline/get），解析 klines 喂 CYQCalculator。

    S114 自建取数层：params 含 ut=_ZTB_UT（日 K 通用公开 token，非涨停池专属）、
    secid=f"{1 if 沪 else 0}.{code}"、fields2 含 f61=hsl 换手率、klt=101/fqt=0/lmt=210。
    em_get 自带 breaker('eastmoney') + 0.3s 限流 + 直连/代理探测 + UA + timeout=8
    （真实 socket 超时，根因消除 S094 的 daemon 8s 线程硬截断）。

    返回 list[dict]（含 open/close/high/low/hsl，数值类型对齐 akshare pd.to_numeric）
    或 None（熔断 OPEN raise / 请求异常 / 无筹码 body 空 / 解析失败 / 不足 90 条）。
    None 4 态均诚实降级（R3），chip_distribution 据此返 {} 走 diagnosis missing 标记。
    """
    from datetime import datetime  # noqa: PLC0415
    from data.transport import eastmoney_get as em_get  # noqa: PLC0415 — 防封底线
    from .eastmoney import _ZTB_UT  # noqa: PLC0415 — 日 K 通用公开 token

    params = {
        "secid": f"{1 if code.startswith('6') else 0}.{code}",
        "fields1": "f1,f2,f3,f4,f5,f6",
        "fields2": "f51,f52,f53,f54,f55,f56,f57,f58,f59,f60,f61",
        "klt": "101",
        "fqt": "0",
        "end": datetime.now().date().strftime("%Y%m%d"),
        "lmt": "210",
        "ut": _ZTB_UT,
    }
    headers = {"Referer": "https://quote.eastmoney.com/"}
    try:
        r = em_get("https://push2his.eastmoney.com/api/qt/stock/kline/get",
                   params=params, headers=headers, timeout=8)
        data = r.json()
    except Exception as e:
        # em_get 熔断 OPEN raise RuntimeError / 请求异常 / JSON 解析失败 → None
        logging.getLogger("astock").warning(
            "chip_distribution(%s) 取数失败（em_get）: %s", code, e)
        return None

    klines = (data.get("data") or {}).get("klines")
    if not klines:
        return None  # 该股无筹码（body 空 / 新股）

    def _to_float(s: str) -> float | None:
        try:
            return float(s)
        except (TypeError, ValueError):
            return None

    out: list[dict] = []
    for line in klines:
        parts = line.split(",")
        if len(parts) < 11:
            continue
        # f51-f61: date,open,close,high,low,volume,amount,振幅,涨跌幅,涨跌额,hsl
        rec = {
            "open": _to_float(parts[1]), "close": _to_float(parts[2]),
            "high": _to_float(parts[3]), "low": _to_float(parts[4]),
            "hsl": _to_float(parts[10]),
        }
        # CYQCalculator 依赖 open/close/high/low/hsl 均为数值（akshare pd.to_numeric 对齐），
        # 字符串传入会致 JS `+` 拼接而非数值相加 → avg=NaN。数值缺失行跳过。
        if any(rec[k] is None for k in ("open", "close", "high", "low", "hsl")):
            continue
        out.append(rec)
    if len(out) < 90:  # R9：push2delay 延时镜像不足 90 条不视为成功
        return None
    return out


def chip_distribution(code: str) -> dict:
    """筹码分布（东财 CYQCalculator，最新交易日）—— 获利比例 / 平均成本 / 集中度 / 90%&70%成本区间。

    S114：自建取数走 em_get（push2his kline/get + ut=_ZTB_UT 日K token），删 ak.stock_cyq_em
    黑盒 + 删 daemon 8s 线程（em_get timeout=8 真实 socket 超时，无限挂起根因消除）+ 删
    chip breaker（em_get breaker('eastmoney') 已覆盖，对齐 hot_money_seats 复用范式，R8 精简）。
    计算层保真复用东财原 JS（cyq_js.CYQ_JS + py_mini_racer，策略 A，R5 逐字搬已验保真）。

    返 {} 诚实 fallback 4 态（R3）：em_get 熔断 OPEN raise / 请求异常 / 无筹码 / 解析失败
    → 均 {}（falsy，走 diagnosis.py:230 missing 标记，不臆造值）。**不可**返
    {chip_profit_ratio: None, ...}（truthy 绕过 missing 标记，改变行为，R4）。

    返回 5 键（R6 shape 不变）：
      - chip_profit_ratio: 获利比例（0-1，benefitPart）
      - avg_cost: 平均成本
      - concentration: 90% 集中度
      - 90_cost / 70_cost: 90% / 70% 成本区间（"low-high"）
    """
    klines = _fetch_cyq_klines(code)
    if not klines:
        return {}  # R3 诚实 fallback（falsy，走 diagnosis missing 标记）
    try:
        import py_mini_racer  # noqa: PLC0415 — V8 计算依赖（akshare 已带，不新增）
        from .cyq_js import CYQ_JS  # noqa: PLC0415 — 东财原 JS（逐字搬，R5 保真）
        js = py_mini_racer.MiniRacer()
        js.eval(CYQ_JS)
        # 算最后一条 = 最新交易日筹码分布（index 0-based，klinedata 全量）
        mcode = js.call("CYQCalculator", len(klines) - 1, klines)
    except Exception as e:
        logging.getLogger("astock").warning(
            "chip_distribution(%s) CYQCalculator 计算失败: %s", code, e)
        return {}

    def g(v):
        # R7：清洗 JS 假值占位（False/"false"/""/None/"-"/"--"→None）。注 0==False，
        # benefitPart=0（全套牢）时 g(0)→None，与原 akshare g() 既有行为一致。
        return None if v in (False, "false", "", None, "-", "--") else v

    p90 = mcode["percentChips"]["90"]
    p70 = mcode["percentChips"]["70"]
    lo90, hi90 = g(p90["priceRange"][0]), g(p90["priceRange"][1])
    lo70, hi70 = g(p70["priceRange"][0]), g(p70["priceRange"][1])
    return {
        "chip_profit_ratio": g(mcode["benefitPart"]),
        "avg_cost": g(mcode["avgCost"]),
        "concentration": g(p90["concentration"]),
        "90_cost": None if (lo90 is None or hi90 is None) else f"{lo90}-{hi90}",
        "70_cost": None if (lo70 is None or hi70 is None) else f"{lo70}-{hi70}",
    }
