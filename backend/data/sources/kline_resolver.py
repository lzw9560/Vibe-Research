# -*- coding: utf-8 -*-
"""S008 日K线解析器——baostock 单源（本环境唯一可用源）。

2026-09-20 彻底精简：本环境 baidu 403 Forbidden + sina/mootdx 返空 + akshare 东财
封禁，baostock 是唯一可用源（无 IP 限制免防封，qfq 前复权，singleton login +
_BS_LOCK 串行 query 防线程竞争）。pattern_scan _compute_ma 自算 MA5/10/20 from
close（strategies/pattern_scan.py:170-199，不依赖 kline 返 ma 字段），60 bars 够
（:177 len<20 check）。baidu 1023 bars 不必要——消费侧自算 MA，60 bars 60 交易日够。

保留多源框架（_SOURCES 注册表 + fetch_kline 并发 + adjust 口径）——将来其他环境
加源只改 _SOURCES + _SOURCE_ADJUST + 写 _xxx 函数，消费者零变更。

返 tuple[list[dict], str | None]：bars + 命中源名。全失败返 ([], None)——不抛、
不臆造，消费者按空决策（诚实无数据）。

字段约定（raw bar dict）：date/open/close/high/low/volume/amount/ma5/ma10/ma20，
缺字段=None（baostock 无 ma，消费侧 _compute_ma 自算）。
"""
from __future__ import annotations

import logging

log = logging.getLogger(__name__)


def _baostock(code: str) -> list[dict]:
    """baostock 日K（qfq 前复权，无 IP 限制免防封，本环境唯一可用源）。

    singleton login（baostock_src.ensure_login 进程级 + _BS_LOCK 串行 query 防线程
    竞争），adjustflag=2 qfq，返最近 60 交易日 bars（start=now-120 天容纳周末）。
    baostock 无 ma5/10/20——消费侧 _compute_ma 自算（pattern_scan:170-199）。
    """
    from datetime import datetime, timedelta
    from data.sources.baostock_src import fetch_daily_bars
    end = datetime.now().strftime("%Y-%m-%d")
    start = (datetime.now() - timedelta(days=120)).strftime("%Y-%m-%d")  # 120 天容纳周末取 60 交易日
    bars_raw = fetch_daily_bars(code, start, end)
    if not bars_raw:
        return []
    bars: list[dict] = []
    for r in bars_raw[-60:]:
        vol = r.get("volume")
        amt = r.get("amount")
        bars.append({
            "date": r.get("date"),
            "open": r.get("open"), "close": r.get("close"),
            "high": r.get("high"), "low": r.get("low"),
            "volume": int(vol) if vol else None,
            "amount": float(amt) if amt else None,
            "ma5": None, "ma10": None, "ma20": None,
        })
    return bars


# 源链注册表（策略集，按名字）。2026-09-20：只 baostock（本环境唯一可用源）。
# 加源食谱：写 _xxx(code) 函数 + 在 _SOURCES 追加名字 + _SOURCE_ADJUST 声明口径。
_SOURCES: list[str] = ["baostock"]

# 各源原生复权口径（单一事实源）。消费者传 adjust="qfq" 时只走口径匹配的源。
_SOURCE_ADJUST: dict[str, str] = {
    "baostock": "qfq",
}


def adjust_of(name: str) -> str | None:
    """某源的原生复权口径（未知源返 None）。供消费者观测/日志。"""
    return _SOURCE_ADJUST.get(name)


def _call(name: str, code: str) -> list[dict]:
    """按名查找源函数并调用（monkeypatch _<name> 即生效，便于测试）。"""
    fn = globals().get(f"_{name}")
    if fn is None:
        raise RuntimeError(f"unknown kline source: {name}")
    return fn(code)


def _chain(sources: list[str] | None, adjust: str | None) -> list[str]:
    """按 sources 子集 + adjust 口径筛选源链。两者皆 None 返全链。"""
    base = _SOURCES if sources is None else [s for s in _SOURCES if s in sources]
    if adjust is None:
        return base
    return [s for s in base if _SOURCE_ADJUST.get(s) == adjust]


def fetch_kline(code: str, sources: list[str] | None = None,
                adjust: str | None = None) -> tuple[list[dict], str | None]:
    """取日K线。返 (bars, source_name)；全失败/超时返 ([], None)。

    单源 baostock（本环境唯一可用，直接用不乱试其他源）。并发框架保留——将来
    加源时首个非空即返。timeout 8s（baostock query ~4-5s + 多股 _BS_LOCK 串行排队）。
    """
    chain = _chain(sources, adjust)
    if not chain:
        return [], None
    from concurrent.futures import ThreadPoolExecutor, wait, FIRST_COMPLETED
    TIMEOUT = 8
    with ThreadPoolExecutor(max_workers=len(chain)) as ex:
        futs = {ex.submit(_call, name, code): name for name in chain}
        try:
            done, not_done = wait(futs, timeout=TIMEOUT, return_when=FIRST_COMPLETED)
            for fut in done:
                name = futs[fut]
                try:
                    bars = fut.result()
                    if bars:
                        return bars, name
                except Exception as e:  # noqa: BLE001 — 源失败吞异常，诚实返空
                    log.warning("kline source %s failed for %s: %s", name, code, repr(e)[:200])
                    continue
            for fut in not_done:
                name = futs[fut]
                try:
                    bars = fut.result(timeout=max(0.1, TIMEOUT))
                    if bars:
                        return bars, name
                except Exception:  # noqa: BLE001 — timeout/失败
                    continue
        finally:
            ex.shutdown(wait=False, cancel_futures=True)
    log.warning("kline all sources empty/failed for %s", code)
    return [], None


def list_sources(adjust: str | None = None) -> list[str]:
    """可用源名（按链顺序）。传 adjust 只返该口径源，供诊断/配置。"""
    return _chain(None, adjust)
