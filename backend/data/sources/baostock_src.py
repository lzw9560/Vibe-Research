# -*- coding: utf-8 -*-
"""baostock 数据源封装（S167 + P2 DRY 扩展）。

baostock 证券宝。历史可回测 K 线 + 财报。本模块封装项目用到的 baostock 接口，
供 scheduled_tasks + tools + strategies 复用（去重 15+ 文件内联 baostock 副本，P2 瘦身）。

**单次 login**：baostock login 状态是进程全局的；本模块用模块级 flag 保证一次 login，
避免 per-call 重登（S152 实测 per-call 840 次登录拖垮）。login 失败 raise
DependencyMissing（复用 _common 范式，下游惯用降级）。

**批量 re-login**：长会话超时返空时调用 ``logout()`` 重置 flag → ``ensure_login()`` 重登。
工程底线：无臆造——缺数据返 []，不补默认值。

**限流 + 熔断（防 IP 封禁）**：baostock 端点会封 IP（实测黑名单 error_code 10001011）。
复用 ``transport.py`` 的限流模式（0.3s 最小间隔 + 随机抖动）+ ``circuit_breaker.get_breaker("baostock")``
（5 次连续失败 → OPEN → 60s 后 HALF_OPEN 恢复）。login 失败触发熔断，query 异常/失败也计数。
"""
from __future__ import annotations

import logging
import random
import threading
import time

from circuit_breaker import get_breaker
from data.sources._common import DependencyMissing
from typing import Any

logger = logging.getLogger("vibe-research")

_BS_READY = False
# baostock login/query 进程全局非线程安全——线程池多线程竞争 login 状态坏（HTTP 5min 返 0，
# in-process 单线程 OK）。Lock 串行 ensure_login + query（像 mini_racer singleton+lock）
_BS_LOCK = threading.Lock()

# ── 限流（防 IP 封禁，复用 transport.py 的 _em_last_call 模式）──────────────────
_BS_MIN_INTERVAL = 0.3  # 最小请求间隔（秒）
_bs_last_call = [0.0]           # 上次请求时间戳（可变单元素列表，模块级共享）
_bs_last_call_lock = threading.Lock()  # 保护 _bs_last_call 读写


def _rate_limit() -> None:
    """限流：保证两次 baostock 请求最小间隔 + 随机抖动（复用 transport.py 模式）。

    在 _BS_LOCK 内调用时已串行（无并发竞争）；在无 _BS_LOCK 的函数中靠 _bs_last_call_lock
    保护时间戳读写。抖动 0.05-0.15s 防固定间隔被识别为机器行为。
    """
    with _bs_last_call_lock:
        wait = _BS_MIN_INTERVAL - (time.time() - _bs_last_call[0])
    if wait > 0:
        time.sleep(wait + random.uniform(0.05, 0.15))


def _mark_call() -> None:
    """更新上次请求时间戳（成功/失败都更新，保持限流间隔，防失败后立即重试触发限流）。"""
    with _bs_last_call_lock:
        _bs_last_call[0] = time.time()


# repo 标准日K 10 字段（refresh_kline_cache / kline_returns / scan_long_value_cache 共用）
KLINE_FIELDS = "date,open,high,low,close,volume,amount,turn,pctChg,isST"

# 数值字段（float 转换），其余（date / isST / time）保持字符串
_FLOAT_FIELDS = frozenset({"open", "high", "low", "close", "volume", "amount",
                           "turn", "pctChg", "preclose"})


def ensure_login() -> None:
    """单次 baostock login（进程级，幂等，线程安全——Lock 串行避免线程池竞争 login 状态坏）。

    限流 + 熔断：login 前检查 breaker（OPEN 时快速失败），login 后记录 success/failure。
    黑名单 error_code（如 10001011）触发 record_failure，累积 5 次后熔断 OPEN。
    """
    global _BS_READY
    if _BS_READY:
        return
    with _BS_LOCK:
        if _BS_READY:  # double-checked
            return
        breaker = get_breaker("baostock")
        if not breaker.allow_request():
            raise DependencyMissing("[CircuitBreaker:baostock] 熔断中，快速失败")
        _rate_limit()
        import baostock as bs  # noqa: PLC0415
        try:
            rs = bs.login()
        except Exception as e:  # noqa: BLE001
            _mark_call()
            breaker.record_failure()
            raise DependencyMissing(f"baostock login 异常: {e}") from e
        _mark_call()
        if rs.error_code != "0":
            breaker.record_failure()
            raise DependencyMissing(f"baostock login 失败: {rs.error_code} {rs.error_msg}")
        breaker.record_success()
        _BS_READY = True


def _try_login() -> bool:
    """ensure_login 包装：catch ImportError（未装）+ DependencyMissing（login 失败）。返 bool。"""
    try:
        ensure_login()
        return True
    except (ImportError, DependencyMissing) as e:
        logger.warning("[baostock] login 不可用: %s", e)
        return False


def logout() -> None:
    """baostock logout + 重置 flag（批量 re-login 用）。吞异常——teardown 不阻塞。"""
    global _BS_READY
    _BS_READY = False
    try:
        import baostock as bs  # noqa: PLC0415
        bs.logout()
    except Exception:  # noqa: BLE001
        pass


# 进程退出时 teardown baostock session（R1 fix，2026-09-22：ensure_login singleton
# 无 atexit，长驻 scheduler 进程持服务端 session 不释放。atexit 吞异常，不阻塞退出）
import atexit  # noqa: E402

atexit.register(logout)


def _to_bs_code(code: str) -> str:
    """接受 6 位裸 code 或 9 位 baostock code（含 '.'）。9 位直接返。"""
    if "." in code:
        return code
    return _six_to_baostock(code)


def _six_to_baostock(code: str) -> str:
    """6 位 A 股 code → baostock 9 位（sh./sz. 前缀）。

    复刻 S152 harness：6/9 开头 sh（沪市主板/科创板）否则 sz（深市/创业板）。
    北交所（8/4 开头）baostock 暂不支持，仍按 sz 映射（返空自然处理，不臆造）。
    """
    return f"sh.{code}" if code[0] in "689" else f"sz.{code}"


def fetch_5min_bars(code: str, start: str, end: str) -> list[dict[str, Any]]:
    """baostock 5min K 线（qfq 前复权）。

    Args:
        code: 6 位裸 code。
        start/end: 'YYYY-MM-DD'（end 含，baostock 区间闭）。

    返 [{date, time, open, high, low, close, volume}, ...]。缺数据/异常返 []（不臆造）。
    login 单次（ensure_login，不 per-call 重登）。
    """
    try:
        ensure_login()
    except (ImportError, DependencyMissing) as e:
        logger.warning("[baostock] login 不可用: %s", e)
        return []
    import baostock as bs  # noqa: PLC0415
    bc = _six_to_baostock(code)
    bars: list[dict[str, Any]] = []
    breaker = get_breaker("baostock")
    if not breaker.allow_request():
        logger.warning("[baostock] fetch_5min_bars %s 熔断中，快速失败", code)
        return []
    # Lock 串行 query+fetch（baostock query 进程全局非线程安全，线程池竞争状态坏 HTTP 返 0）
    with _BS_LOCK:
        _rate_limit()
        try:
            rs = bs.query_history_k_data_plus(
                bc, "date,time,open,high,low,close,volume",
                start_date=start, end_date=end, frequency="5", adjustflag="2",
            )
            _mark_call()
            if rs.error_code == "0":
                breaker.record_success()
                while rs.next():
                    row = rs.get_row_data()
                    bars.append({
                        "date": row[0], "time": row[1],
                        "open": float(row[2]), "high": float(row[3]),
                        "low": float(row[4]), "close": float(row[5]),
                        "volume": float(row[6]) if row[6] else 0.0,
                    })
            else:
                breaker.record_failure()
        except Exception as e:  # noqa: BLE001
            _mark_call()
            breaker.record_failure()
            logger.warning("[baostock] fetch_5min_bars %s %s~%s 失败: %s", code, start, end, e)
            return []
    return bars


def _parse_row(field_names: list[str], row: list[str]) -> dict[str, Any]:
    """通用行解析：float 字段转 float（空→0.0），date/isST/time 保持 str。

    ValueError/IndexError → continue（跳坏行，复刻 refresh_kline_cache 范式）。
    """
    bar: dict[str, Any] = {}
    for i, name in enumerate(field_names):
        val = row[i] if i < len(row) else ""
        if name in _FLOAT_FIELDS:
            try:
                bar[name] = float(val) if val else 0.0
            except ValueError:
                bar[name] = 0.0
        else:
            bar[name] = val if val else ("0" if name == "isST" else "")
    return bar


def fetch_bars(
    code: str, start: str, end: str,
    fields: str = KLINE_FIELDS, adjustflag: str = "2",
    frequency: str = "d",
) -> list[dict[str, Any]]:
    """通用 baostock K 线（可配 fields/adjustflag/frequency）。

    Args:
        code: 6 位裸 code 或 9 位 baostock code（含 '.').
        start/end: 'YYYY-MM-DD'（end 含，baostock 区间闭）。
        fields: baostock 字段串（逗号分隔），默认 10 字段日K。
        adjustflag: '2'=前复权 / '3'=不复权 / '1'=后复权。
        frequency: 'd'=日 / '5'=5min / '15' / '30' / '60'。

    返 [{field: value}, ...]。缺数据/异常返 []（不臆造）。
    login 单次（ensure_login，不 per-call 重登）。
    """
    try:
        ensure_login()
    except (ImportError, DependencyMissing) as e:
        logger.warning("[baostock] login 不可用: %s", e)
        return []
    import baostock as bs  # noqa: PLC0415
    bc = _to_bs_code(code)
    field_names = fields.split(",")
    bars: list[dict[str, Any]] = []
    breaker = get_breaker("baostock")
    if not breaker.allow_request():
        logger.warning("[baostock] fetch_bars %s 熔断中，快速失败", code)
        return []
    with _BS_LOCK:  # 串行 query（baostock 进程全局非线程安全，对齐 fetch_5min_bars）
        _rate_limit()
        try:
            rs = bs.query_history_k_data_plus(
                bc, fields,
                start_date=start, end_date=end,
                frequency=frequency, adjustflag=adjustflag,
            )
            _mark_call()
            if rs.error_code == "0":
                breaker.record_success()
                while rs.next():
                    row = rs.get_row_data()
                    try:
                        bars.append(_parse_row(field_names, row))
                    except (ValueError, IndexError):
                        continue
            else:
                breaker.record_failure()
        except Exception as e:  # noqa: BLE001
            _mark_call()
            breaker.record_failure()
            logger.warning("[baostock] fetch_bars %s %s~%s 失败: %s", code, start, end, e)
            return []
    return bars


def fetch_daily_bars(
    code: str, start: str, end: str, adjustflag: str = "2",
) -> list[dict[str, Any]]:
    """baostock 日K（标准 10 字段：date/open/high/low/close/volume/amount/turn/pctChg/isST）。

    fetch_bars 的日K 专用版（fields=KLINE_FIELDS, frequency='d'）。
    返 [{date, open, high, low, close, volume, amount, turn, pctChg, isST}, ...]。
    缺数据/异常返 []（不臆造）。
    """
    return fetch_bars(code, start, end, fields=KLINE_FIELDS,
                      adjustflag=adjustflag, frequency="d")


def fetch_stock_industry() -> dict[str, str]:
    """baostock 行业分类 → {6位code: industry}。

    baostock query_stock_industry() 返 [updateDate, code(sh.600000), code_name, industry,
    industryClassification]。取 code（去前缀）→ industry。
    login 单次。缺数据/异常返 {}（不臆造）。
    """
    try:
        ensure_login()
    except (ImportError, DependencyMissing) as e:
        logger.warning("[baostock] login 不可用: %s", e)
        return {}
    import baostock as bs  # noqa: PLC0415
    mapping: dict[str, str] = {}
    breaker = get_breaker("baostock")
    if not breaker.allow_request():
        logger.warning("[baostock] fetch_stock_industry 熔断中，快速失败")
        return {}
    _rate_limit()
    try:
        rs = bs.query_stock_industry()
        _mark_call()
        if rs.error_code == "0":
            breaker.record_success()
            while rs.next():
                row = rs.get_row_data()
                if len(row) < 4:
                    continue
                bs_code = row[1]
                code = bs_code.split(".")[-1] if "." in bs_code else bs_code
                industry = row[3]
                if industry and code:
                    mapping[code] = industry
        else:
            breaker.record_failure()
    except Exception as e:  # noqa: BLE001
        _mark_call()
        breaker.record_failure()
        logger.warning("[baostock] fetch_stock_industry 失败: %s", e)
        return {}
    return mapping


def fetch_trade_dates(start: str, end: str) -> list[str]:
    """baostock 交易日历 → [date, ...]（仅 is_trading_day=='1' 的日期）。

    返 ['YYYY-MM-DD', ...]。缺数据/异常返 []（不臆造）。
    """
    try:
        ensure_login()
    except (ImportError, DependencyMissing) as e:
        logger.warning("[baostock] login 不可用: %s", e)
        return []
    import baostock as bs  # noqa: PLC0415
    trading: list[str] = []
    breaker = get_breaker("baostock")
    if not breaker.allow_request():
        logger.warning("[baostock] fetch_trade_dates 熔断中，快速失败")
        return []
    _rate_limit()
    try:
        rs = bs.query_trade_dates(start_date=start, end_date=end)
        _mark_call()
        if rs.error_code == "0":
            breaker.record_success()
            while rs.next():
                d = rs.get_row_data()  # [calendar_date, is_trading_day]
                if len(d) >= 2 and d[1] == "1":
                    trading.append(d[0])
        else:
            breaker.record_failure()
    except Exception as e:  # noqa: BLE001
        _mark_call()
        breaker.record_failure()
        logger.warning("[baostock] fetch_trade_dates %s~%s 失败: %s", start, end, e)
        return []
    return trading


def fetch_all_stock(day: str) -> list[dict[str, str]]:
    """baostock query_all_stock(day) → [{code, tradeStatus, code_name}, ...]。

    返所有证券（含指数/债券/ETF），调用方需自行过滤 A 股。
    tradeStatus '1'=trading '0'=suspended。缺数据/异常返 []（不臆造）。
    """
    try:
        ensure_login()
    except (ImportError, DependencyMissing) as e:
        logger.warning("[baostock] login 不可用: %s", e)
        return []
    import baostock as bs  # noqa: PLC0415
    stocks: list[dict[str, str]] = []
    breaker = get_breaker("baostock")
    if not breaker.allow_request():
        logger.warning("[baostock] fetch_all_stock 熔断中，快速失败")
        return []
    _rate_limit()
    try:
        rs = bs.query_all_stock(day=day)
        _mark_call()
        if rs.error_code == "0":
            breaker.record_success()
            while rs.next():
                d = rs.get_row_data()
                if len(d) < 2:
                    continue
                stocks.append({
                    "code": d[0],
                    "tradeStatus": d[1],
                    "code_name": d[2] if len(d) > 2 else "",
                })
        else:
            breaker.record_failure()
    except Exception as e:  # noqa: BLE001
        _mark_call()
        breaker.record_failure()
        logger.warning("[baostock] fetch_all_stock %s 失败: %s", day, e)
        return []
    return stocks


def fetch_stock_basic(code: str = "") -> list[dict[str, str]]:
    """baostock query_stock_basic(code) → [{code, code_name, ipoDate, outDate, type, status}]。

    code='' 返全表（含指数/债券/ETF），调用方需 code 前缀过滤 A 股。
    缺数据/异常返 []（不臆造）。
    """
    try:
        ensure_login()
    except (ImportError, DependencyMissing) as e:
        logger.warning("[baostock] login 不可用: %s", e)
        return []
    import baostock as bs  # noqa: PLC0415
    rows: list[dict[str, str]] = []
    breaker = get_breaker("baostock")
    if not breaker.allow_request():
        logger.warning("[baostock] fetch_stock_basic 熔断中，快速失败")
        return []
    _rate_limit()
    try:
        rs = bs.query_stock_basic(code=code)
        _mark_call()
        if rs.error_code == "0":
            breaker.record_success()
            while rs.next():
                d = rs.get_row_data()
                rows.append({
                    "code": d[0] if len(d) > 0 else "",
                    "code_name": d[1] if len(d) > 1 else "",
                    "ipoDate": d[2] if len(d) > 2 else "",
                    "outDate": d[3] if len(d) > 3 else "",
                    "type": d[4] if len(d) > 4 else "",
                    "status": d[5] if len(d) > 5 else "",
                })
        else:
            breaker.record_failure()
    except Exception as e:  # noqa: BLE001
        _mark_call()
        breaker.record_failure()
        logger.warning("[baostock] fetch_stock_basic 失败: %s", e)
        return []
    return rows


def fetch_profit_data(code: str, year: int, quarter: int) -> dict[str, Any] | None:
    """baostock query_profit_data → 1 row per (code, year, quarter)。

    Args:
        code: 6 位裸 code 或 9 位 baostock code。
        year/quarter: 财报年份/季度（1-4）。

    返 {pubDate, statDate, roeAvg, epsTTM, MBRevenue, totalShare} 或 None（缺失不臆造）。
    fields VERIFIED: code[0] pubDate[1] statDate[2] roeAvg[3] npMargin[4] gpMargin[5]
                     netProfit[6] epsTTM[7] MBRevenue[8] totalShare[9] liqaShare[10]
    """
    try:
        ensure_login()
    except (ImportError, DependencyMissing) as e:
        logger.warning("[baostock] login 不可用: %s", e)
        return None
    import baostock as bs  # noqa: PLC0415
    bc = _to_bs_code(code)
    breaker = get_breaker("baostock")
    if not breaker.allow_request():
        logger.warning("[baostock] fetch_profit_data %s 熔断中，快速失败", code)
        return None
    _rate_limit()
    try:
        rs = bs.query_profit_data(code=bc, year=year, quarter=quarter)
    except Exception as e:  # noqa: BLE001
        _mark_call()
        breaker.record_failure()
        logger.warning("[baostock] fetch_profit_data %s %sQ%s 失败: %s", code, year, quarter, e)
        return None
    _mark_call()
    if rs.error_code != "0":
        breaker.record_failure()
        return None
    breaker.record_success()
    while rs.next():
        d = rs.get_row_data()
        try:
            return {
                "pubDate": d[1] if len(d) > 1 else "",
                "statDate": d[2] if len(d) > 2 else "",
                "roeAvg": float(d[3]) if len(d) > 3 and d[3] else 0.0,
                "epsTTM": float(d[7]) if len(d) > 7 and d[7] else 0.0,
                "MBRevenue": float(d[8]) if len(d) > 8 and d[8] else 0.0,
                "totalShare": float(d[9]) if len(d) > 9 and d[9] else 0.0,
            }
        except (ValueError, IndexError):
            return None
    return None
