# -*- coding: utf-8 -*-
"""R2 全市场活跃度（B3）。换手/量比/成交额/振幅，批次 50，经 astock 限流（AC7）。"""

from __future__ import annotations

import astock
from concurrent.futures import ThreadPoolExecutor
from data.mappers import quote_from_tencent

_BATCH = 50


def _f(v) -> float | None:
    """raw 值 → float（None/非数→None）。"""
    try:
        return float(v) if v is not None else None
    except (TypeError, ValueError):
        return None


def _is_historical_date(date: str) -> bool:
    """date < 今日（YYYY-MM-DD 字符串比较）→ 历史日（走 kline 复算路径）。"""
    from datetime import datetime
    try:
        return (date or "")[:10] < datetime.now().strftime("%Y-%m-%d")
    except Exception:
        return False


def _compute_kline_derived(bars: list[dict], idx: int, float_shares: float | None) -> dict:
    """从 K线 bars 复算战法派生字段 + 前日成交额（S081/S084 口径，历史日与盘前共用）。

    以 ``bars[idx]`` 为"当日"bar、``bars[idx-1]`` 为"前日"bar，复算：
    - ``max_high_pct`` = (high/prev_close - 1)*100（当日最高涨幅）
    - ``shadow_length_pct`` = (high/close - 1)*100（上影线长度）
    - ``ma_5_status`` = Upward/Downward/Flat（最近5日 close 均值 vs 前移一日均值）
    - ``prev_turnover_pct`` = prev.vol*10000/float_shares（前日换手率）
    - ``prev_amount_yi`` = prev.amount/1e8（前日成交额，亿）

    任一字段取不到 → 不写入返回 dict（调用方保持 None）。不臆造。
    与 ``_fetch_activity_from_kline`` 历史日路径口径一字一致（S085 A3 抽出共享，
    消除历史日与盘前 tencent 路径的计算重复）。
    """
    out: dict = {}
    if idx < 0 or idx >= len(bars):
        return out
    bar = bars[idx]
    prev = bars[idx - 1] if idx > 0 else None
    close = _f(bar.get("close"))
    high = _f(bar.get("high"))
    prev_close = _f(prev.get("close")) if prev else None
    # max_high_pct：当日最高涨幅 = (high/prev_close - 1)*100
    if high is not None and prev_close and prev_close > 0:
        out["max_high_pct"] = round((high / prev_close - 1) * 100, 2)
    # shadow_length_pct：上影线 = (high/close - 1)*100
    if high is not None and close and close > 0:
        out["shadow_length_pct"] = round((high / close - 1) * 100, 2)
    # ma_5_status：5日均线趋势（最近5日 close 均值 vs 前移一日均值）
    if idx >= 5:
        closes_5d = [_f(b.get("close")) for b in bars[idx-5:idx+1]]
        closes_5d = [c for c in closes_5d if c is not None]
        if len(closes_5d) >= 6:
            ma5_today = sum(closes_5d[-5:]) / 5
            ma5_prev = sum(closes_5d[-6:-1]) / 5
            if ma5_today > ma5_prev:
                out["ma_5_status"] = "Upward"
            elif ma5_today < ma5_prev:
                out["ma_5_status"] = "Downward"
            else:
                out["ma_5_status"] = "Flat"
    # prev_turnover_pct：前日换手率（前日 bar vol*10000/float_shares）
    if prev is not None and float_shares and float_shares > 0:
        prev_vol = _f(prev.get("vol"))
        if prev_vol is not None:
            out["prev_turnover_pct"] = round(prev_vol * 10000 / float_shares, 2)
    # prev_amount_yi：前日成交额（前日 bar amount/1e8，亿）
    if prev is not None:
        prev_amount = _f(prev.get("amount"))
        if prev_amount is not None:
            out["prev_amount_yi"] = round(prev_amount / 1e8, 4)
    return out


def _fetch_single_historical(c: str, today_quote: dict, target: str) -> tuple[str, dict]:
    """单只股票历史日活跃度（线程安全，无共享）。mirror fund_flow._fetch_single。

    S138：从 _fetch_activity_from_kline 串行循环抽取，供 ThreadPoolExecutor 并行调用。
    per code：quote_from_tencent + astock.kline + 找 date bar + 派生 + entry。
    任一字段取不到 → missing，不臆造。
    """
    entry: dict = {
        "name": None, "price": None, "change_pct": None, "turnover_pct": None,
        "vol_ratio": None, "amount_yi": None, "amplitude_pct": None,
        "limit_up": None, "limit_down": None, "missing": {},
        "float_market_cap": None,  # S057：八项标准①流通市值
        # S081：PRD 2 战法因子（历史日路径在下方从 K线扩展算）
        "max_high_pct": None, "shadow_length_pct": None,
        "ma_5_status": None, "prev_turnover_pct": None,
        # S084：tencent_quote 扩展 + 前日成交额（历史日路径：kline 复算 + 估值 None）
        "last_close": None, "open": None, "change_amt": None,
        "pe_ttm": None, "mcap_yi": None, "pb": None, "prev_amount_yi": None,
    }
    model = quote_from_tencent(c, today_quote.get(c, {}))
    entry["name"] = model.name
    # S057：流通市值（元）—— tencent_quote 的 float_market_cap 字段
    if model.float_market_cap:
        entry["float_market_cap"] = model.float_market_cap
    float_shares = None
    if model.float_market_cap and model.price:
        float_shares = model.float_market_cap / model.price
    try:
        bars = astock.kline(c, 4, 10) or []
    except Exception:
        bars = []
    bar = None
    prev = None
    idx = -1
    for i, b in enumerate(bars):
        if (b.get("datetime") or "")[:10] == target:
            bar = b
            prev = bars[i - 1] if i > 0 else None
            idx = i
            break
    if bar is None:
        entry["missing"]["turnover_pct"] = "历史K线未取得该日"
        return c, entry
    # S049 C2：暴露数据源日期（供 diagnose as_of 取最早）
    entry["_as_of"] = target
    close = _f(bar.get("close"))
    prev_close = _f(prev.get("close")) if prev else None
    high = _f(bar.get("high"))
    low = _f(bar.get("low"))
    vol = _f(bar.get("vol")) or 0.0
    amount = _f(bar.get("amount")) or 0.0
    entry["price"] = close
    # S084 R4.1：kline 复算路径（历史日可取）
    entry["last_close"] = prev_close  # T-2 收盘 = T-1 昨收
    entry["open"] = _f(bar.get("open"))  # T-1 开盘
    if close is not None and prev_close is not None:
        entry["change_amt"] = round(close - prev_close, 2)  # T-1 涨跌额
    if prev_close:
        entry["change_pct"] = round((close - prev_close) / prev_close * 100, 2)
        entry["amplitude_pct"] = round((high - low) / prev_close * 100, 2)
    prev_vols = [_f(b.get("vol")) or 0.0 for b in bars[max(0, idx - 5):idx]]
    if prev_vols and sum(prev_vols) > 0:
        entry["vol_ratio"] = round(vol / (sum(prev_vols) / len(prev_vols)), 2)
    entry["amount_yi"] = round(amount / 1e8, 4)
    if float_shares and float_shares > 0:
        entry["turnover_pct"] = round(vol * 10000 / float_shares, 2)
    else:
        entry["missing"]["turnover_pct"] = "流通股本近似未取得（individual_data 宕）"

    # S081/S084：战法派生字段 + 前日成交额（共享口径，见 _compute_kline_derived）
    entry.update(_compute_kline_derived(bars, idx, float_shares))

    # S084 R4.1：pe_ttm/mcap_yi/pb 历史日无源（tencent_quote 仅当日），标 missing 不臆造
    for _k in ("pe_ttm", "mcap_yi", "pb"):
        entry["missing"][_k] = "当前估值非T-1（tencent_quote 当日取，历史日路径无源）"

    for k in ("turnover_pct", "vol_ratio", "amount_yi", "amplitude_pct"):
        if entry[k] is None and k not in entry["missing"]:
            entry["missing"][k] = "K线字段未取得"
    return c, entry


def _fetch_activity_from_kline(codes: list[str], date: str) -> dict[str, dict]:
    """历史日活跃度——kline 复算（tencent_quote 仅当日，S044 R7）。

    S138：per-code kline 并行化（mirror fund_flow 范式）。mootdx kline 并行实测 80x
    加速（Quotes.factory 不缓存单 client，每股独立 TCP 连接）。批量 tencent_quote
    保留（快），per code 抽 _fetch_single_historical + ThreadPoolExecutor(max_workers=5)。
    shape 不变（下游 candidate_funnel/funnel 依赖不变）。

    对每个 code：astock.kline 取 bars → 找 date 对应 bar → 复算 amount/amplitude/change/vol_ratio；
    turnover_pct 需流通股本——individual_info 走东财 push2 当前宕，改用 tencent_quote 当日
    float_market_cap/price 作流通股本近似（短期近似，lockup 日有偏差，标 missing）。
    kline 量单位为"手"：turnover_pct = vol×100/float_shares×100 = vol×10000/float_shares。
    任一字段取不到 → missing，不臆造。
    """
    target = (date or "")[:10]
    try:
        today_quote = astock.tencent_quote(codes) or {}
    except Exception:
        today_quote = {}
    if not codes:
        return {}
    out: dict[str, dict] = {}
    with ThreadPoolExecutor(max_workers=min(5, len(codes))) as ex:
        futures = [ex.submit(_fetch_single_historical, c, today_quote, target) for c in codes]
        for fu in futures:
            try:
                c, entry = fu.result()
                out[c] = entry
            except Exception:
                pass  # per-code 异常 → 下面兜底 missing
    for c in codes:
        if c not in out:
            out[c] = {"missing": {"turnover_pct": "活跃度未取得"}}
    return out


def _fetch_single_realtime(c: str, raw: dict, as_of: str) -> tuple[str, dict]:
    """单只股票当日活跃度（线程安全，无共享）。mirror fund_flow._fetch_single。

    S138：从 fetch_activity 当日路径串行循环抽取，供 ThreadPoolExecutor 并行调用。
    per code：quote_from_tencent + entry + astock.kline 派生 + missing。
    """
    model = quote_from_tencent(c, raw.get(c, {}))
    # turnover 为元，换算成亿元；不用 `or` 兜底以免吞掉 0.0
    turnover = model.turnover
    amount_yi = round(turnover / 1e8, 4) if turnover is not None else None
    entry = {
        "name": model.name,
        "price": model.price,
        "change_pct": model.change_pct,
        "turnover_pct": model.turnover_rate,
        "vol_ratio": model.vol_ratio,
        "amount_yi": amount_yi,
        "amplitude_pct": model.amplitude,
        "limit_up": model.limit_up_price,
        "limit_down": model.limit_down_price,
        # S049 C2：当日行情数据源日期=as_of（tencent_quote 仅当日）
        "_as_of": as_of,
         # S057：流通市值（元）—— 供八项标准①判定
         "float_market_cap": model.float_market_cap,
         # S081/S085 A3：战法派生字段——盘前 tencent 无当日 K线，
         # 改从 K线 T-1 bar 复算（下方注入），取不到保持 None
         "max_high_pct": None,
         "shadow_length_pct": None,
         "ma_5_status": None,
         "prev_turnover_pct": None,
         # S084 R4.1：tencent_quote 扩展（当日路径直接读 Quote 模型字段）
         "last_close": model.last_close,
         "open": model.open,
         "change_amt": model.change_amount,  # Quote 字段 change_amount → entry key change_amt
         "pe_ttm": model.pe_ttm,
         "mcap_yi": model.market_cap_yi,  # Quote property（亿）
         "pb": model.pb,
         # S085 A3：前日成交额——从 K线 T-2 bar 取（下方注入），取不到保持 None
         "prev_amount_yi": None,
     }
    # S085 A3：盘前 tencent 路径补 K线派生字段（max_high_pct/shadow/ma5/
    # prev_turnover_pct/prev_amount_yi）。tencent 盘前取不到这5项，从
    # K线 T-1 bar 复算（口径与 _fetch_activity_from_kline 完全一致，经
    # _compute_kline_derived 共享）。失败保持 None + missing，不降级 tencent 字段。
    derived: dict = {}
    try:
        bars = astock.kline(c, 4, 10) or []
    except Exception:
        bars = []
    if bars:
        # T-1 bar：今日无 K线 → bars[-1]；今日已有一根 → bars[-2]
        idx_t1 = len(bars) - 2 if len(bars) >= 2 and \
            (bars[-1].get("datetime") or bars[-1].get("date") or "")[:10] >= \
            as_of[:10] else len(bars) - 1
        if idx_t1 >= 0:
            # float_shares：从 tencent 流通市值/价格近似（与历史日路径一致）
            float_shares = None
            if model.float_market_cap and model.price:
                float_shares = model.float_market_cap / model.price
            derived = _compute_kline_derived(bars, idx_t1, float_shares)
            for _k, _v in derived.items():
                entry[_k] = _v
    missing: dict[str, str] = {}
    for k in ("turnover_pct", "vol_ratio", "amount_yi", "amplitude_pct"):
        if entry[k] is None:
            missing[k] = "行情字段未取得"
    # S085 A3：K线派生取不到标 missing（盘前非交易时段 K线可能为空，诚实标注）
    if not derived:
        missing["kline_derived"] = "盘前K线未取得"
    elif entry["prev_amount_yi"] is None:
        missing["prev_amount_yi"] = "当日路径无前日 K线（需历史日 kline 复算）"
    if missing:
        entry["missing"] = missing
    return c, entry


def fetch_activity(codes: list[str], as_of: str) -> dict[str, dict]:
    """返回 {code: {name, price, change_pct, turnover_pct, vol_ratio, amount_yi,
    amplitude_pct, limit_up, limit_down, missing?}}。

    S138：per-code kline 并行化（mirror fund_flow 范式）。mootdx kline 并行实测 80x
    加速。批量 tencent_quote 保留（快），per code 抽 _fetch_single_realtime +
    ThreadPoolExecutor(max_workers=5)。shape 不变。

    读侧经 ``quote_from_tencent`` 拿 Quote 模型（单位已统一、字段 rename 已集中），
    输出 dict shape 保持不变以兼容下游 candidate_funnel/funnel（本轮不迁下游）。
    """
    if not codes:
        return {}
    if _is_historical_date(as_of):
        return _fetch_activity_from_kline(codes, as_of)
    out: dict[str, dict] = {}
    for i in range(0, len(codes), _BATCH):
        batch = codes[i : i + _BATCH]
        try:
            raw = astock.tencent_quote(batch) or {}
        except Exception:
            for c in batch:
                out[c] = {"missing": {"turnover_pct": "行情未取得"}}
            continue
        with ThreadPoolExecutor(max_workers=min(5, len(batch))) as ex:
            futures = [ex.submit(_fetch_single_realtime, c, raw, as_of) for c in batch]
            for fu in futures:
                try:
                    c, entry = fu.result()
                    out[c] = entry
                except Exception:
                    pass  # per-code 异常 → 下面兜底 missing
        for c in batch:
            if c not in out:
                out[c] = {"missing": {"turnover_pct": "行情未取得"}}
    return out
