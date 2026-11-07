# -*- coding: utf-8 -*-
"""data_extract——筹码结构/板块/历史K线缓存。

实现范围：
- 005 数据层：extract_chip_structure / _get_kline_cache
- 006 数据层：extract_sector
"""
from __future__ import annotations

import logging

from astock import concept_blocks  # noqa: E402

from strategies.first_board.universe import _to_float  # noqa: E402

_logger = logging.getLogger(__name__)

# baostock kline cache 已迁 SQLite（engine.kline_cache_store），模块级 _KLINE_CACHE 删除——
# per-code 走 get_bars(code)（~0 常驻，~2ms/查）。

# 沪深300 涨跌幅模块级缓存（date → pct%），避免 _market_drop_pct 重复 baostock login。
# baostock 查历史指数不入 kline_cache（缓存只含个股），故用 baostock 库实时查历史。
_HS300_PCT_CACHE: dict[str, float | None] = {}


def extract_chip_structure(code: str, date: str | None = None) -> dict:
    """取 T-1 日筹码结构（换手率/量比/成交额）——历史数据，无未来函数。

    数据源：baostock_kline_cache.json 历史日K线（``turn``/``amount``/``volume``）。
    - turn：换手率%（baostock 字段，直接用）
    - amount：成交额元（baostock 字段，直接用）
    - vol_ratio：量比 = 当日每分钟均量 / 5 日每分钟均量
      （当日 volume/240 ÷ 前 5 日 volume 均值/240，240 = A 股开市分钟数）

    性能：31MB JSON 模块级缓存只读一次（``_KLINE_CACHE``），后续候选复用，
    避免每只重读全文件（旧实现 2s/只 → 0ms）。

    Args:
        code: 6 位股票代码。
        date: YYYY-MM-DD（T-1 日）。None → 返空 dict（无法定位历史 bar）。

    Returns:
        dict 含：
        - turnover_pct: float | None（换手率，百分数，如 8.5 表示 8.5%）
        - vol_ratio: float | None（量比）
        - amount: float | None（成交额，元）
        数据缺失/请求失败/当日 bar 不在 cache → 空 dict {}（剔除层跳过该条件，
        不因数据缺失误剔除）。S111 R6：精确匹配 date 当日 bar（== 对齐 _bar_close），
        缺当日 bar 返 {} 不回退前一日值（旧 <= 静默返昨日值打分，已修）。

    ⚠️ 无未来函数：全部用 date 当日及之前的历史 K 线，不用 tencent_quote 实时接口。
    旧实现调 tencent_quote([code]) 返回 T 日收盘筹码，用 T 日数据评判 T-1 首板 = 未来函数。
    """
    if not date:
        return {}
    # 归一 date 为 YYYY-MM-DD（baostock 缓存用此格式）
    d = date if "-" in date else f"{date[:4]}-{date[4:6]}-{date[6:8]}"
    try:
        from engine.kline_cache_store import get_bars
        bars = get_bars(code)
        if not bars:
            return {}
        # 精确匹配 date 当日 bar（对齐 _bar_close: scheduled_tasks.py:1885 == 范式）。
        # bars 已按日期升序，从末尾往前找。
        # S111 R6：旧 <= 取"当日或之前最近 bar"，当日 bar 未入 cache（baostock
        # 16:30 kline_refresh，first_board 16:15 跑早 15min）时静默回退前一日值
        # 冒充当日 → score_dim_turnover(权重0.15)+score_dim4_chip 用过期值打分。
        # 改 == 精确匹配，缺当日 bar 返 {}（剔除/评分层降级跳过，对齐
        # score_dim_turnover 返 -1.0 不加权 / _bar_close 缺则跳过诚实范式，不臆造昨日值）。
        target_bar: dict | None = None
        target_idx = -1
        for i in range(len(bars) - 1, -1, -1):
            if bars[i].get("date", "") == d:
                target_bar = bars[i]
                target_idx = i
                break
        if target_bar is None:
            return {}

        out: dict = {}
        tp = _to_float(target_bar.get("turn"))
        out["turnover_pct"] = tp
        out["amount"] = _to_float(target_bar.get("amount"))

        # 量比 = 当日 volume / 240 ÷ 前 5 日 volume 均值 / 240
        # 240 = A 股开市分钟数（9:30-11:30 + 13:00-15:00 = 4 小时 = 240 min）
        vol_now = _to_float(target_bar.get("volume"))
        if vol_now is not None and target_idx >= 5:
            vols_prev5 = [_to_float(bars[j].get("volume")) for j in range(target_idx - 5, target_idx)]
            valid_vols = [v for v in vols_prev5 if v is not None and v > 0]
            if valid_vols:
                avg_5d = sum(valid_vols) / len(valid_vols)
                if avg_5d > 0:
                    out["vol_ratio"] = round((vol_now / 240.0) / (avg_5d / 240.0), 3)
        return out
    except Exception as e:
        _logger.warning("extract_chip_structure 历史数据失败 code=%s date=%s err=%s", code, d, e)
        return {}


def _get_kline_cache() -> dict[str, list[dict]]:
    """deprecated 全量 load（offline 兼容）；per-code 走 engine.kline_cache_store.get_bars。

    保留接口防 break 外部 import。从 SQLite 全量读（2.19GB 峰值一次性 local，非常驻）。
    """
    from engine.kline_cache_store import load_all
    return load_all()


def extract_sector(code: str) -> dict:
    """取个股板块/概念归属。

    Args:
        code: 6 位股票代码。

    Returns:
        dict 含：
        - boards: list[dict]（每项 {name, code, change_pct, lead_stock}）
        - concept_tags: list[str]（板块名列表）
        数据缺失/请求失败 → 空 dict {}。
    """
    try:
        # S131 R4：raise_on_failure=True 让源断 raise（非吞空 dict 伪装"无板块"），
        # try/except 兜底返 {}（上层 extract_sector 返空 dict，评分层降级跳过）。
        raw = concept_blocks(code, raise_on_failure=True)
    except Exception as e:
        _logger.warning("extract_sector concept_blocks 失败 code=%s err=%s", code, e)
        return {}
    if not raw or not isinstance(raw, dict):
        return {}
    boards = raw.get("boards") or []
    tags = raw.get("concept_tags") or []
    if not boards and not tags:
        return {}
    return {"boards": boards, "concept_tags": tags}
