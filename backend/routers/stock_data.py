"""
Stock data router.
"""
import asyncio
from fastapi import APIRouter, HTTPException, Query
import time as _time
from typing import Any, Callable, Dict, Tuple

import astock

router = APIRouter(tags=["stock"])


# ---- Cache helpers ----
_PCT_CACHE: Dict[str, Tuple[float, Any]] = {}
_ANN_CACHE: Dict[str, Tuple[float, Any]] = {}
_FIN_CACHE: Dict[str, Tuple[float, Any]] = {}
_DC_CACHE: Dict[Tuple[str, str], Tuple[float, Any]] = {}  # key=(endpoint, code) -> (ts, data)


def _cached(endpoint: str, code: str, ttl: int, fetch: Callable) -> Any:
    key: Tuple[str, str] = (endpoint, code)
    hit = _DC_CACHE.get(key)
    if hit and _time.time() - hit[0] < ttl:
        return hit[1]
    data = fetch()
    _DC_CACHE[key] = (_time.time(), data)
    return data


# ---- Routes ----

@router.get("/api/indices")
def indices() -> Dict[str, Any]:
    """A股大盘指数实时行情（上证/深证成指/创业板指/沪深300）。仅标准库。"""
    try:
        return {"data": astock.index_quote()}
    except Exception as e:  # noqa: BLE001
        raise HTTPException(502, f"指数行情异常：{e}") from e


@router.get("/api/quote")
def quote(codes: str = Query(..., description="逗号分隔的 6 位代码")) -> Dict[str, Any]:
    """实时行情：现价/涨跌/PE/PB/市值/换手/涨跌停。仅标准库，永远可用。"""
    lst = [c.strip() for c in codes.split(",") if c.strip()]
    if not lst or any(not c.isdigit() or len(c) != 6 for c in lst):
        raise HTTPException(400, "codes 必须是逗号分隔的 6 位数字")
    try:
        return {"data": astock.tencent_quote(lst)}
    except Exception as e:  # noqa: BLE001 — 边界统一兜底
        raise HTTPException(502, f"行情源异常：{e}") from e


@router.get("/api/valuation/percentile")
def valuation_percentile(code: str = Query(...)) -> Dict[str, Any]:
    """PE-TTM / PB 历史分位（近5年）。全站缓存 30 分钟/代码（历史序列日频、变化慢）。"""
    from routers.common import _validate
    code = _validate(code)
    hit = _PCT_CACHE.get(code)
    if hit and _time.time() - hit[0] < 1800:
        return {"data": hit[1]}
    try:
        data = astock.valuation_percentile(code)
        _PCT_CACHE[code] = (_time.time(), data)
        return {"data": data}
    except astock.DependencyMissing as e:
        raise HTTPException(501, str(e)) from e
    except Exception as e:  # noqa: BLE001
        raise HTTPException(502, f"估值分位异常：{e}") from e


@router.get("/api/announcements")
def announcements(code: str = Query(...)) -> Dict[str, Any]:
    """个股近期公告（东财，仅 requests）。缓存 15 分钟/代码。"""
    from routers.common import _validate
    code = _validate(code)
    hit = _ANN_CACHE.get(code)
    if hit and _time.time() - hit[0] < 900:
        return {"data": hit[1]}
    try:
        data = astock.announcements(code)
        _ANN_CACHE[code] = (_time.time(), data)
        return {"data": data}
    except Exception as e:  # noqa: BLE001
        raise HTTPException(502, f"公告源异常：{e}") from e


@router.get("/api/financials")
def financials(code: str = Query(...)) -> Dict[str, Any]:
    """财务关键指标（同花顺财务摘要，最新报告期）。缓存 30 分钟/代码。"""
    from routers.common import _validate
    code = _validate(code)
    hit = _FIN_CACHE.get(code)
    if hit and _time.time() - hit[0] < 1800:
        return {"data": hit[1]}
    try:
        data = astock.financials(code)
        _FIN_CACHE[code] = (_time.time(), data)
        return {"data": data}
    except astock.DependencyMissing as e:
        raise HTTPException(501, str(e)) from e
    except Exception as e:  # noqa: BLE001
        raise HTTPException(502, f"财务摘要异常：{e}") from e


@router.get("/api/valuation")
def valuation(code: str = Query(...)) -> Dict[str, Any]:
    """完整估值：行情 + 一致预期 + 前向PE/PEG/消化年数。"""
    from routers.common import _validate
    code = _validate(code)
    try:
        return {"data": astock.full_valuation(code)}
    except ValueError as e:
        raise HTTPException(404, str(e)) from e
    except Exception as e:  # noqa: BLE001
        raise HTTPException(502, f"估值计算异常：{e}") from e


@router.get("/api/reports")
def reports(code: str = Query(...), pages: int = Query(2, ge=1, le=5)) -> Dict[str, Any]:
    """个股研报列表（东财，含 PDF 链接）。仅需 requests。"""
    from routers.common import _validate
    code = _validate(code)
    try:
        rows = astock.eastmoney_reports(code, max_pages=pages)
        for r in rows:
            r["pdfUrl"] = astock.pdf_url(r.get("infoCode", "")) if r.get("infoCode") else None
        return {"data": rows}
    except Exception as e:  # noqa: BLE001
        raise HTTPException(502, f"研报源异常：{e}") from e


@router.get("/api/news")
def news(code: str = Query(...), limit: int = Query(20, ge=1, le=50)) -> Dict[str, Any]:
    """个股新闻（东财，需 akshare）。"""
    from routers.common import _validate
    code = _validate(code)
    try:
        return {"data": astock.stock_news(code, limit=limit)}
    except astock.DependencyMissing as e:
        raise HTTPException(501, str(e)) from e
    except Exception as e:  # noqa: BLE001
        raise HTTPException(502, f"新闻源异常：{e}") from e


@router.get("/api/info")
def info(code: str = Query(...)) -> Dict[str, Any]:
    """个股基本面：行业/股本/上市时间（需 akshare）。"""
    from routers.common import _validate
    code = _validate(code)
    try:
        return {"data": astock.individual_info(code)}
    except astock.DependencyMissing as e:
        raise HTTPException(501, str(e)) from e
    except Exception as e:  # noqa: BLE001
        raise HTTPException(502, f"基本面源异常：{e}") from e


@router.get("/api/disclosure")
def disclosure(code: str = Query(...)) -> Dict[str, Any]:
    """巨潮公告列表（需 akshare）。"""
    from routers.common import _validate
    code = _validate(code)
    try:
        return {"data": astock.disclosure(code)}
    except astock.DependencyMissing as e:
        raise HTTPException(501, str(e)) from e
    except Exception as e:  # noqa: BLE001
        raise HTTPException(502, f"公告源异常：{e}") from e


@router.get("/api/kline")
def kline(code: str = Query(...), category: int = Query(4), offset: int = Query(60, ge=1, le=800)) -> Dict[str, Any]:
    """K线（需 mootdx）。category 4=日 5=周 6=月 11=60分钟。"""
    from routers.common import _validate
    code = _validate(code)
    try:
        return {"data": astock.kline(code, category=category, offset=offset)}
    except astock.DependencyMissing as e:
        raise HTTPException(501, str(e)) from e
    except Exception as e:  # noqa: BLE001
        raise HTTPException(502, f"K线源异常：{e}") from e


@router.get("/api/finance")
def finance(code: str = Query(...)) -> Dict[str, Any]:
    """季报财务快照（需 mootdx）。"""
    from routers.common import _validate
    code = _validate(code)
    try:
        return {"data": astock.finance(code)}
    except astock.DependencyMissing as e:
        raise HTTPException(501, str(e)) from e
    except Exception as e:  # noqa: BLE001
        raise HTTPException(502, f"财务源异常：{e}") from e


@router.get("/api/stock/{code}/deep")
async def stock_deep(code: str) -> Dict[str, Any]:
    """个股深度数据聚合：行情 + K线 + 估值 + 资金流 + 龙虎榜 + 涨停分析 + 财务 + 板块 + 概念 + 公告 + 研报。"""
    from routers.common import _validate
    code = _validate(code)

    async def _safe_call(name: str, fetch):
        try:
            return await asyncio.to_thread(fetch)
        except Exception as e:  # noqa: BLE001
            return None

    try:
        quote_task = _safe_call("quote", lambda: astock.tencent_quote([code]))
        kline_task = _safe_call("kline", lambda: astock.kline(code, category=4, offset=60))
        valuation_task = _safe_call("valuation", lambda: astock.full_valuation(code))
        percentile_task = _safe_call("percentile", lambda: astock.valuation_percentile(code))
        fund_flow_task = _safe_call("fund_flow", lambda: astock.stock_fund_flow_120d(code))
        dragon_tiger_task = _safe_call("dragon_tiger", lambda: astock.dragon_tiger_board(code))
        limitup_task = _safe_call("limitup", lambda: _limitup_analysis_sync(code))
        financials_task = _safe_call("financials", lambda: astock.financials(code))
        blocks_task = _safe_call("blocks", lambda: astock.concept_blocks(code))
        hot_concepts_task = _safe_call("hot_concepts", lambda: astock.hot_concepts(code))
        announcements_task = _safe_call("announcements", lambda: astock.announcements(code))
        reports_task = _safe_call("reports", lambda: astock.eastmoney_reports(code, max_pages=2))

        results = await asyncio.gather(
            quote_task, kline_task, valuation_task, percentile_task,
            fund_flow_task, dragon_tiger_task, limitup_task, financials_task,
            blocks_task, hot_concepts_task, announcements_task, reports_task,
            return_exceptions=True,
        )

        def _first_or_none(item):
            if isinstance(item, Exception):
                return None
            return item

        quote_data = _first_or_none(results[0])
        kline_data = _first_or_none(results[1])
        valuation_data = _first_or_none(results[2])
        percentile_data = _first_or_none(results[3])
        fund_flow_data = _first_or_none(results[4])
        dragon_tiger_data = _first_or_none(results[5])
        limitup_data = _first_or_none(results[6])
        financials_data = _first_or_none(results[7])
        blocks_data = _first_or_none(results[8])
        hot_concepts_data = _first_or_none(results[9])
        announcements_data = _first_or_none(results[10])
        reports_data = _first_or_none(results[11])

        # tencent_quote 返回 dict[str, dict]，取第一个
        if isinstance(quote_data, dict):
            quote_data = next(iter(quote_data.values()), None)

        return {
            "data": {
                "quote": quote_data,
                "kline": kline_data,
                "valuation": valuation_data,
                "percentile": percentile_data,
                "fund_flow": fund_flow_data,
                "dragon_tiger": dragon_tiger_data,
                "limitup": limitup_data,
                "financials": financials_data,
                "blocks": blocks_data,
                "hot_concepts": hot_concepts_data,
                "announcements": announcements_data,
                "reports": reports_data,
            }
        }
    except Exception as e:  # noqa: BLE001
        raise HTTPException(502, f"个股深度数据聚合异常：{e}") from e


def _limitup_analysis_sync(code: str) -> Dict[str, Any]:
    """同步包装 limitup analysis，供 asyncio.to_thread 使用。"""
    import limitup_strategy as lstrat
    from risk_models import update_one_day_risk_realtime
    import asyncio as _asyncio

    async def _run():
        risk = await update_one_day_risk_realtime(code)
        return await lstrat.get_analysis(code, None, risk=risk)

    return _asyncio.run(_run())


__all__ = ["router"]
