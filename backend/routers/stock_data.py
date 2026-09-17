"""
Stock data router.
"""
import asyncio
import logging
from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel
import time as _time
from typing import Any, Callable, Dict, Tuple

# deep 端点 TTL 缓存：12 源聚合 ~28s（kline 多源串行慢），日内数据 60s 缓存
# quote 滞后 60s 可接受（cockpit 非实时交易），K 线/财务日内不变；第一次 28s 后续秒返
_DEEP_CACHE: Dict[str, Tuple[float, dict]] = {}
_DEEP_CACHE_TTL = 60

import astock
from data import mappers
from models.quote import Quote

router = APIRouter(tags=["stock"])


class QuoteMapResponse(BaseModel):
    """``/api/quote`` 响应信封：{code -> Quote}。S008 T1 起 quote 走 S007 模型。"""
    data: dict[str, Quote]


# ---- Cache helpers ----
_PCT_CACHE: Dict[str, Tuple[float, Any]] = {}
_ANN_CACHE: Dict[str, Tuple[float, Any]] = {}
_FIN_CACHE: Dict[str, Tuple[float, Any]] = {}
# S109：删除零调用死代码 _DC_CACHE + _cached（DRY，统一走 stock_financial._cached / market._cached）。


# ---- Routes ----

@router.get("/api/indices")
def indices() -> Dict[str, Any]:
    """A股大盘指数实时行情（上证/深证成指/创业板指/沪深300）。仅标准库。"""
    try:
        return {"data": astock.index_quote()}
    except Exception as e:  # noqa: BLE001
        raise HTTPException(502, f"指数行情异常：{e}") from e


@router.get("/api/quote", response_model=QuoteMapResponse)
def quote(codes: str = Query(..., description="逗号分隔的 6 位代码")) -> QuoteMapResponse:
    """实时行情：现价/涨跌/PE/PB/市值/换手/涨跌停。仅标准库，永远可用。

    S008 T1：返 S007 ``Quote`` 模型（经 ``mappers.quote_from_tencent`` 投影）。
    字段名按模型契约：``turnover_rate``/``limit_up_price``/``limit_down_price``/``last_close``。
    """
    lst = [c.strip() for c in codes.split(",") if c.strip()]
    if not lst or any(not c.isdigit() or len(c) != 6 for c in lst):
        raise HTTPException(400, "codes 必须是逗号分隔的 6 位数字")
    try:
        raw = astock.tencent_quote(lst)
        return QuoteMapResponse(
            data={c: mappers.quote_from_tencent(c, r) for c, r in raw.items()}
        )
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
        # S109：dict 陷阱内容感知——valuation_percentile 失败返非空 {"metrics":{}}，
        # bool 漏网（truthy dict），用 if data.get("metrics") 不缓存空分位。
        if isinstance(data, dict) and data.get("metrics"):
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
        # S109：空不缓存——东财返 []（HTTP 成功但无数据）不缓存，下次重试。
        if data:
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
        # S109：空不缓存——akshare 返 {} 不缓存，下次重试。
        if data:
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


@router.get("/api/valuation/market")
def market_valuation(date: str = Query(None)) -> Dict[str, Any]:
    """S191 · 市场层估值历史（指数 PE + 全市场 PB）从 datalake/stoke 读。

    stoke（daily_full_pull 沉淀）的 index_pe/market_pb 历史。date=None=最近交易日。
    返 {data: [{date, name, pe, pb}, ...]}。
    """
    import sqlite3  # noqa: PLC0415
    from data.datalake.store import month_db  # noqa: PLC0415
    from vr_paths import last_trading_date_str  # noqa: PLC0415
    from datetime import datetime as _dt  # noqa: PLC0415

    d = date or last_trading_date_str()
    try:
        dt = _dt.strptime(d, "%Y-%m-%d")
    except ValueError:
        raise HTTPException(400, f"date 格式 YYYY-MM-DD: {d}")
    db = month_db("stoke", dt)
    if not db.exists():
        return {"data": [], "note": "datalake/stoke 库未建（daily_full_pull 未跑或 stoke 未配）"}
    conn = sqlite3.connect(str(db), timeout=5)
    conn.row_factory = sqlite3.Row
    try:
        rows = conn.execute(
            "SELECT date, name, pe, pb, snapshot_at FROM pe_pb WHERE date=? ORDER BY name", (d,)
        ).fetchall()
        return {"data": [dict(r) for r in rows], "date": d}
    finally:
        conn.close()


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
async def kline(code: str = Query(...), category: int = Query(4), offset: int = Query(60, ge=1, le=800)) -> Dict[str, Any]:
    """K线（需 mootdx）。category 4=日 5=周 6=月 11=60分钟。"""
    from routers.common import _validate
    code = _validate(code)
    try:
        return {"data": await asyncio.to_thread(astock.kline, code, category=category, offset=offset)}
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
    # TTL 缓存命中：日内数据 + quote 60s 滞后可接受（避免 28s 重复聚合）
    now = _time.time()
    cached = _DEEP_CACHE.get(code)
    if cached and now - cached[0] < _DEEP_CACHE_TTL:
        return cached[1]

    async def _safe_call(name: str, fetch, timeout: float = 8.0):
        """并发跑 fetch（to_thread），8s 超时降级返 None（不拖累 deep 木桶）。

        limitup 17.8s / fund_flow 5.1s 等慢源超 8s 返 None 降级——
        cockpit 主 K 线+quote+财务 这些核心源都 <6s 正常返。
        """
        _t0 = _time.time()
        try:
            r = await asyncio.wait_for(asyncio.to_thread(fetch), timeout=timeout)
            _t1 = _time.time()
            logging.getLogger("stock_deep").info("[deep] %s done %.1fs", name, _t1 - _t0)
            return r
        except asyncio.TimeoutError:
            _t1 = _time.time()
            logging.getLogger("stock_deep").warning("[deep] %s TIMEOUT %.1fs (>%ss 降级)", name, _t1 - _t0, timeout)
            return None
        except Exception as e:  # noqa: BLE001
            _t1 = _time.time()
            logging.getLogger("stock_deep").warning("[deep] %s FAIL %.1fs: %s", name, _t1 - _t0, repr(e)[:120])
            return None

    try:
        quote_task = _safe_call("quote", lambda: astock.tencent_quote([code]))
        kline_task = _safe_call("kline", lambda: astock.kline(code, category=4, offset=60), timeout=15.0)  # kline 核心源，baostock 回退 6.4s + 并发余量，不能 8s 降级
        valuation_task = _safe_call("valuation", lambda: astock.full_valuation(code))
        percentile_task = _safe_call("percentile", lambda: astock.valuation_percentile(code))
        fund_flow_task = _safe_call("fund_flow", lambda: astock.stock_fund_flow_120d(code))
        dragon_tiger_task = _safe_call("dragon_tiger", lambda: astock.dragon_tiger_board(code))
        limitup_task = _safe_call("limitup", lambda: _limitup_analysis_sync(code))
        financials_task = _safe_call("financials", lambda: astock.financials(code))
        blocks_task = _safe_call("blocks", lambda: astock.concept_blocks(code, raise_on_failure=True))
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

        # tencent_quote 返回 dict[str, dict]，投影成 Quote 模型（S008 T1）
        if isinstance(quote_data, dict):
            raw_q = quote_data.get(code) or next(iter(quote_data.values()), None)
            quote_data = mappers.quote_from_tencent(code, raw_q) if raw_q else None

        result = {
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
        _DEEP_CACHE[code] = (_time.time(), result)
        return result
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


@router.get("/api/stock/{code}/kg-summary")
def stock_kg_summary(code: str) -> Dict[str, Any]:
    """个股知识图谱关联摘要（ora-3 §1.5 替代方案）。

    读 vault markdown，返回该股票在投研知识图谱中的关联实体数 + 关联列表 +
    Obsidian URI（前端用此 URI 做「在知识图谱中查看」外链，不做节点数徽标）。

    合规：只返回图谱客观数据（实体元数据/关系链接），无方向性研判。
    复用 backend/ai/tools/kg_tools.py 的 query_kg_relations（不依赖 Obsidian 运行）。
    """
    from routers.common import _validate

    code = _validate(code)

    # kg_tools 用相对导入（from .registry import），按 package 方式导入
    import importlib

    try:
        kg_mod = importlib.import_module("ai.tools.kg_tools")
    except ModuleNotFoundError:
        # ai 包不在 sys.path 时降级：直接读 vault markdown
        return {"data": {"code": code, "in_graph": False, "reason": "kg_tools 不可用"}}

    try:
        result = kg_mod.query_kg_relations(code, entity_type="stock")
    except Exception as e:  # noqa: BLE001
        raise HTTPException(502, f"知识图谱查询异常：{e}") from e

    if result.get("error"):
        return {
            "data": {
                "code": code,
                "in_graph": False,
                "reason": result["error"],
                "obsidian_uri": f"obsidian://search?vault=Obsidian%20Vault&query={code}",
            }
        }

    relations = result.get("relations", [])
    # 按关联类型粗分类计数（target 路径前缀）
    by_folder: Dict[str, int] = {}
    for r in relations:
        target = r.get("target", "")
        # target 形如 "stocks/600519" 或 "industries/食品饮料"
        parts = target.split("/")
        folder = parts[0] if parts else "other"
        by_folder[folder] = by_folder.get(folder, 0) + 1

    return {
        "data": {
            "code": code,
            "in_graph": True,
            "path": result.get("path"),
            "total_relations": result.get("total", 0),
            "by_folder": by_folder,
            "relations": relations,
            "obsidian_uri": (
                f"obsidian://open?vault=Obsidian%20Vault&"
                f"file=10_Reference%2Finvesting%2Fstocks%2F{code}"
            ),
        }
    }


@router.get("/api/stock/tech-score")
async def tech_score_endpoint(code: str = Query(..., description="6 位股票代码")) -> Dict[str, Any]:
    """S215 通用技术指标评分——MA/MACD/RSI/量能/乖离/支撑 6 维 100 分 + 信号映射。

    独立通用评分（不碰打板 §44 sizing），与 query_gap_regime/query_macd_divergence/query_rsi
    regime 信号互补（综合评分 vs regime 信号）。
    """
    def _build() -> dict:
        from ai.tools.ta_tools import query_tech_score
        return query_tech_score(code)
    return await asyncio.to_thread(_build)


__all__ = ["router"]
