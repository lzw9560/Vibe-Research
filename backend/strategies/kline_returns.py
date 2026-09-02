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

# S144 R1：unbuyable（一字板涨停封死）检测口径。
# 一字板 = next_bar 四价相等（open≈close≈high≈low，无日内区间）+ 涨停幅度。
# 容差 0.01 元（float 噪声；覆盖 ¥5-50 涨停股，高价股更宽松不误判）。
# 涨停阈值 9.8% 粗判覆盖主板 10%/创业板科创板 20%/北交所 30%。
# 注：只覆盖涨停方向（做多策略只有涨停封死不可买；一字跌停对做多可买，有人抛、买家成交）。
UNBUYABLE_PRICE_TOL: float = 0.01
UNBUYABLE_PCT_THRESHOLD: float = 9.8


def _is_unbuyable_next_bar(nb: dict) -> bool:
    """检测 next_bar（T+1）是否一字板涨停封死（不可买）。

    四价相等（high≈low≈open≈close）+ pctChg≥9.8% → 一字板涨停 → 不可买。
    正常上涨/有区间/跌停均返 False（可买）。
    """
    nb_open = nb.get("open") or 0.0
    nb_high = nb.get("high") or 0.0
    nb_low = nb.get("low") or 0.0
    nb_close = nb.get("close") or 0.0
    nb_pct = nb.get("pctChg") or 0.0
    return (
        abs(nb_high - nb_low) <= UNBUYABLE_PRICE_TOL
        and abs(nb_open - nb_close) <= UNBUYABLE_PRICE_TOL
        and nb_pct >= UNBUYABLE_PCT_THRESHOLD  # 涨停方向（非 abs：跌停一字板对做多可买）
    )


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


def _match_next_bar(bars: list[dict], signal_date: str) -> tuple[dict | None, dict | None, dict | None]:
    """在 bars 找 signal_date 的 bar + 它的 next_bar（T+1）+ next_next_bar（T+2）。

    返 (sb, nb, nnb)，缺失返 None。T+2（nnb）用于 S144 R5 可实现口径（卖 T+2 收盘）。
    """
    idx = None
    for i, b in enumerate(bars):
        if b["date"] == signal_date:
            idx = i
            break
    if idx is None:
        return None, None, None
    sb = bars[idx]
    nb = bars[idx + 1] if idx + 1 < len(bars) else None
    nnb = bars[idx + 2] if idx + 2 < len(bars) else None
    return sb, nb, nnb


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
            sb, nb, nnb = _match_next_bar(bars, signal_date)
            if nb is None or nb.get("open") in (None, 0, 0.0):
                out[code] = {
                    "return_open2close": None, "return_close2close": None,
                    "next_pctChg": None, "return_open2next_close": None,
                    "is_unbuyable": False,
                }
                continue
            next_open = nb["open"]      # T+1 开盘 = 买入价（信号 T 盘后知，买 T+1 开盘）
            next_close = nb["close"]     # T+1 收盘
            sig_close = sb["close"] if sb else None
            o2c = round((next_close - next_open) / next_open * 100, 4) if next_open else None
            c2c = round((next_close - sig_close) / sig_close * 100, 4) if sig_close else None
            # S144 R5：return_open2next_close = (T+2 close - T+1 open)/T+1 open*100
            # 可实现 T+1 口径：买 T+1 开盘（nb.open），A 股 T+1 买入日不可卖，卖 T+2 收盘（nnb.close）。
            # 需 nnb（T+2 bar）；近期 picks（T+2 未可得）→ None，is_win fallback o2c（T+0 基线）。
            # 注：o2c（T+1 intraday）非策略收益（策略买 T+1 open 非 T+1 intraday）；
            #    o2nc 才是策略可实现收益。is_win 优先 o2nc，fallback o2c 兼容旧数据。
            nnb_close = nnb["close"] if nnb and nnb.get("close") else None
            o2nc = round((nnb_close - next_open) / next_open * 100, 4) if (nnb_close is not None and next_open) else None
            # S144 R1：一字板涨停封死（T+1=买入日 不可买）检测
            is_unbuyable = _is_unbuyable_next_bar(nb)
            out[code] = {
                "return_open2close": o2c,
                "return_close2close": c2c,
                "next_pctChg": nb.get("pctChg"),
                "return_open2next_close": o2nc,
                "is_unbuyable": is_unbuyable,
            }
    finally:
        try:
            bs.logout()
        except Exception:
            pass
    return out
