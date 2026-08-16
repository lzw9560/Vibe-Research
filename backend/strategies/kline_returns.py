# -*- coding: utf-8 -*-
"""S069 R2：T+1 收益计算 helper——baostock kline 次日 bar → return_open2close。

复用 Phase 0a（scripts/backtest/backfill_kline_samples.py）的口径：
  return_open2close = (next_close - next_open) / next_open * 100
  return_close2close = (next_close - signal_close) / signal_close * 100
  next_pctChg = next_bar 的 pctChg

供 R2（每日 T+1 回填 forward_test picks + universe）+ retroactive backfill 共用。
诚实：缺 next_bar 标 None（不臆造）；baostock 不可用返空 dict（调用方降级）。
"""
from __future__ import annotations

import logging

logger = logging.getLogger(__name__)


def _bs_code(code: str) -> str:
    """A 股 6 位代码 → baostock 9 位代码（sh./sz. 前缀，6 开头 sh 否则 sz）。"""
    if not code or len(code) != 6:
        return ""
    return f"sh.{code}" if code.startswith("6") else f"sz.{code}"


def fetch_klines(bs_code: str, start_date: str, end_date: str) -> list[dict]:
    """baostock qfq 日K（含 next_bar，故 start..end 需覆盖 signal_date + 次日）。

    空/错时返 []（re-login 重试一次，BaoStock 长会话超时返空）。需调用方先 bs.login()。
    """
    import baostock as bs
    fields = "date,open,high,low,close,volume,amount,turn,pctChg,isST"
    try:
        rs = bs.query_history_k_data_plus(
            bs_code, fields, start_date=start_date, end_date=end_date, adjustflag="2",
        )
    except Exception:
        return []
    if rs.error_code != "0":
        return []
    bars: list[dict] = []
    while rs.error_code == "0" and rs.next():
        d = rs.get_row_data()
        try:
            bars.append({
                "date": d[0],
                "open": float(d[1]) if d[1] else 0.0,
                "high": float(d[2]) if d[2] else 0.0,
                "low": float(d[3]) if d[3] else 0.0,
                "close": float(d[4]) if d[4] else 0.0,
                "pctChg": float(d[8]) if d[8] else 0.0,
            })
        except (ValueError, IndexError):
            continue
    return bars


def _match_next_bar(bars: list[dict], signal_date: str) -> tuple[dict | None, dict | None]:
    """在 bars 找 signal_date 的 bar + 它的 next_bar（缺失返 None,None）。"""
    idx = None
    for i, b in enumerate(bars):
        if b["date"] == signal_date:
            idx = i
            break
    if idx is None:
        return None, None
    if idx + 1 >= len(bars):
        return bars[idx], None
    return bars[idx], bars[idx + 1]


def compute_returns_for_codes(
    signal_date: str, codes: list[str], lookback_days: int = 5,
) -> dict[str, dict[str, float | None]]:
    """对一批 codes 算 signal_date 的 T+1 收益（return_open2close/close2close/next_pctChg）。

    signal_date: "YYYY-MM-DD"。baostock login 在本函数内（login→fetch→logout）。
    缺 next_bar 的 code 标 None（不臆造）。baostock 不可用 → 返 {} （调用方降级）。
    """
    from datetime import datetime, timedelta

    try:
        import baostock as bs
    except ImportError:
        logger.warning("[kline_returns] baostock 未安装（prod requirements 有，dev venv 无）→ 无法算 T+1 收益")
        return {}

    if not codes:
        return {}
    try:
        lg = bs.login()
        if getattr(lg, "error_code", "0") != "0":
            logger.warning("[kline_returns] baostock login 失败: %s", getattr(lg, "error_msg", ""))
            return {}
    except Exception as e:
        logger.warning("[kline_returns] baostock login 异常: %s", e)
        return {}

    # start..end 覆盖 signal_date 前后（含 next_bar）；end 取今日（未来日有 next_bar）
    try:
        d = datetime.strptime(signal_date, "%Y-%m-%d")
    except ValueError:
        bs.logout()
        return {}
    start = (d - timedelta(days=lookback_days)).strftime("%Y-%m-%d")
    end = datetime.now().strftime("%Y-%m-%d")

    out: dict[str, dict[str, float | None]] = {}
    try:
        for code in codes:
            bsc = _bs_code(code)
            if not bsc:
                continue
            bars = fetch_klines(bsc, start, end)
            sb, nb = _match_next_bar(bars, signal_date)
            if nb is None or nb.get("open") in (None, 0, 0.0):
                out[code] = {"return_open2close": None, "return_close2close": None, "next_pctChg": None}
                continue
            next_open = nb["open"]
            next_close = nb["close"]
            sig_close = sb["close"] if sb else None
            o2c = round((next_close - next_open) / next_open * 100, 4) if next_open else None
            c2c = round((next_close - sig_close) / sig_close * 100, 4) if sig_close else None
            out[code] = {
                "return_open2close": o2c,
                "return_close2close": c2c,
                "next_pctChg": nb.get("pctChg"),
            }
    finally:
        try:
            bs.logout()
        except Exception:
            pass
    return out
