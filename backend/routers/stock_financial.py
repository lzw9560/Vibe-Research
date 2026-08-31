"""
Stock financial router.
"""
from fastapi import APIRouter, HTTPException, Query
import time as _time
from typing import Any, Callable, Dict, Tuple

import astock

router = APIRouter(tags=["stock"])


# ---- Cache helpers ----
_DC_CACHE: Dict[Tuple[str, str], Tuple[float, Any]] = {}  # key=(endpoint, code) -> (ts, data)


def _cached(endpoint: str, code: str, ttl: int, fetch: Callable, valid: Callable = bool) -> Any:
    """S109：加 valid 守卫——valid(data) 判否不缓存（空不缓存），下次重试。

    复用 S103 market._cached(valid=bool) 范式：空结果/失败返空不写缓存，breaker
    恢复后下次请求重试。list 型路由用默认 bool；dict 型（dragon_tiger/lockup/
    blocks）传内容感知 lambda（失败返非空 dict，bool 漏网）。
    """
    key: Tuple[str, str] = (endpoint, code)
    hit = _DC_CACHE.get(key)
    if hit and _time.time() - hit[0] < ttl:
        return hit[1]
    data = fetch()
    if valid(data):  # ← S103 空不缓存核心
        _DC_CACHE[key] = (_time.time(), data)
    return data


# ---- Routes ----

@router.get("/api/margin")
def margin(code: str = Query(...)) -> Dict[str, Any]:
    """融资融券明细（东财，日级）。缓存 30 分钟。"""
    from routers.common import _validate
    code = _validate(code)
    try:
        return {"data": _cached("margin", code, 1800, lambda: astock.margin_trading(code))}
    except Exception as e:  # noqa: BLE001
        raise HTTPException(502, f"融资融券异常：{e}") from e


@router.get("/api/block-trade")
def block_trade(code: str = Query(...)) -> Dict[str, Any]:
    """大宗交易（东财）。缓存 30 分钟。"""
    from routers.common import _validate
    code = _validate(code)
    try:
        return {"data": _cached("block", code, 1800, lambda: astock.block_trade(code))}
    except Exception as e:  # noqa: BLE001
        raise HTTPException(502, f"大宗交易异常：{e}") from e


@router.get("/api/holders")
def holders(code: str = Query(...)) -> Dict[str, Any]:
    """股东户数变化（东财，季度级）。缓存 30 分钟。"""
    from routers.common import _validate
    code = _validate(code)
    try:
        return {"data": _cached("holders", code, 1800, lambda: astock.holder_num_change(code))}
    except Exception as e:  # noqa: BLE001
        raise HTTPException(502, f"股东户数异常：{e}") from e


@router.get("/api/dividend")
def dividend(code: str = Query(...)) -> Dict[str, Any]:
    """分红送转历史（东财）。缓存 30 分钟。"""
    from routers.common import _validate
    code = _validate(code)
    try:
        return {"data": _cached("dividend", code, 1800, lambda: astock.dividend_history(code))}
    except Exception as e:  # noqa: BLE001
        raise HTTPException(502, f"分红送转异常：{e}") from e


@router.get("/api/fund-flow")
def fund_flow(code: str = Query(...)) -> Dict[str, Any]:
    """个股资金流（东财 push2his，120 日主力净流入）。缓存 15 分钟。
    注：push2his 对部分大陆住宅 IP 有间歇风控，可能返回空（非代码问题）。"""
    from routers.common import _validate
    code = _validate(code)
    try:
        return {"data": _cached("fundflow", code, 900, lambda: astock.stock_fund_flow_120d(code))}
    except Exception as e:  # noqa: BLE001
        raise HTTPException(502, f"资金流异常：{e}") from e


@router.get("/api/dragon-tiger")
def dragon_tiger(code: str = Query(...)) -> Dict[str, Any]:
    """龙虎榜：该股近期上榜记录 + 买卖席位 + 机构净买（东财）。缓存 30 分钟。"""
    from routers.common import _validate
    code = _validate(code)
    try:
        return {"data": _cached("dt", code, 1800, lambda: astock.dragon_tiger_board(code),
                                valid=lambda v: bool(v.get("records")) if isinstance(v, dict) else bool(v))}
    except Exception as e:  # noqa: BLE001
        raise HTTPException(502, f"龙虎榜异常：{e}") from e


@router.get("/api/lockup")
def lockup(code: str = Query(...)) -> Dict[str, Any]:
    """限售解禁日历：历史解禁 + 未来 90 天待解禁（东财）。缓存 30 分钟。"""
    from routers.common import _validate
    code = _validate(code)
    try:
        return {"data": _cached("lockup", code, 1800, lambda: astock.lockup_expiry(code),
                                valid=lambda v: bool(v.get("history") or v.get("upcoming")) if isinstance(v, dict) else bool(v))}
    except Exception as e:  # noqa: BLE001
        raise HTTPException(502, f"解禁日历异常：{e}") from e


@router.get("/api/blocks")
def blocks(code: str = Query(...)) -> Dict[str, Any]:
    """个股所属板块/概念归属（东财 slist）。缓存 30 分钟。"""
    from routers.common import _validate
    code = _validate(code)
    try:
        return {"data": _cached("blocks", code, 1800, lambda: astock.concept_blocks(code, raise_on_failure=True),
                                valid=lambda v: bool(v.get("boards")) if isinstance(v, dict) else bool(v))}
    except Exception as e:  # noqa: BLE001
        raise HTTPException(502, f"板块归属异常：{e}") from e


@router.get("/api/hot-concepts")
def hot_concepts(code: str = Query(...)) -> Dict[str, Any]:
    """个股当下被市场归到哪些概念在炒（东财热门概念命中）。缓存 15 分钟。"""
    from routers.common import _validate
    code = _validate(code)
    try:
        return {"data": _cached("hotcon", code, 900, lambda: astock.hot_concepts(code))}
    except Exception as e:  # noqa: BLE001
        raise HTTPException(502, f"热门概念异常：{e}") from e


@router.get("/api/investor-qa")
def investor_qa(code: str = Query(...)) -> Dict[str, Any]:
    """互动易问答（巨潮）：投资者提问 + 公司回复。缓存 15 分钟。"""
    from routers.common import _validate
    code = _validate(code)
    try:
        return {"data": _cached("irm", code, 900, lambda: astock.investor_qa(code))}
    except Exception as e:  # noqa: BLE001
        raise HTTPException(502, f"互动易异常：{e}") from e


@router.get("/api/industry")
def industry(top: int = Query(20, ge=5, le=50)) -> Dict[str, Any]:
    """全行业涨跌幅排名（东财行业板块，板块级、零个股名单）。缓存 5 分钟。"""
    key = ("industry", str(top))
    hit = _DC_CACHE.get(key)
    if hit and _time.time() - hit[0] < 300:
        return {"data": hit[1]}
    try:
        data = astock.industry_comparison(top_n=top)
        # S109：dict 陷阱内容感知——industry_comparison 失败返非空 {"top":[],...}，
        # bool 漏网，用 if data.get("top") 守卫不缓存空排名。
        if isinstance(data, dict) and data.get("top"):
            _DC_CACHE[key] = (_time.time(), data)
        return {"data": data}
    except Exception as e:  # noqa: BLE001
        raise HTTPException(502, f"行业排名异常：{e}") from e


__all__ = ["router"]
