"""S007 契约层 — baseline 回放映射函数。

把 astock fallback JSON 的真实字段名映射到 FundFlow / seat_records 契约字段。
映射本身可复算（纯字段重命名 + 单位转换），不含副作用。
"""

from __future__ import annotations


def map_capital_flow_to_fundflow(raw: dict, *, code: str, market: str) -> dict:
    """把 astock 原始 capital_flow 行映射为 FundFlow.model_validate 可接受的 dict。

    Args:
        raw: 原始 JSON 行，字段来自 fallback JSON data 数组元素。
        code: 股票代码（fallback 不含，需外部传入）。
        market: 市场类型（fallback 不含，需外部传入）。

    Returns:
        dict: 可直接传给 FundFlow.model_validate 的数据。
    """
    return {
        "code": code,
        "market": market,
        "date": raw.get("date"),
        "main_net": raw.get("main_net"),
        "super_large_net": raw.get("super_net"),
        "large_net": raw.get("large_net"),
        "medium_net": raw.get("mid_net"),
        "small_net": raw.get("small_net"),
    }


def _extract_seat_records(seats_data: dict, *, side: str) -> list[dict]:
    """从 seats.buy / seats.sell 提取统一格式的 seat_records。"""
    records: list[dict] = []
    for item in seats_data.get(side, []):
        records.append({
            "name": item.get("name"),
            "buy_amt": item.get("buy_amt"),
            "sell_amt": item.get("sell_amt"),
            "net": item.get("net"),
            "side": side,
            "hold_days": None,
        })
    return records


def map_dragon_tiger_to_seat_records(raw: list[dict] | dict) -> list[dict]:
    """把龙虎榜原始 seats 结构映射为 seat_records 列表。

    Args:
        raw: 原始 seats 结构（dict 含 buy/sell）或空列表/空 dict。

    Returns:
        list[dict]: 统一格式的 seat_records，含 name/buy_amt/sell_amt/net/side/hold_days。
    """
    if isinstance(raw, list):
        return []
    if not isinstance(raw, dict):
        return []

    result: list[dict] = []
    for side in ("buy", "sell"):
        result.extend(_extract_seat_records(raw, side=side))
    return result
