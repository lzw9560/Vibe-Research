"""Vibe-Research 工具函数 —— 移植自 vibe-astock@3c3b7c8 util.py。

只移植 Vibe-Research 无等价物的 4 个函数（atomic_write_json / china_now /
china_today / validate_trade_date）。safe_join 仅被丢弃模块消费，按 YAGNI 不移植；
is_degraded_report / strip_model_noise / is_a_share_closed / is_weekend /
is_today 是 vibe-astock 自家基建，Vibe-Research 有更强版本（vr_paths），不移植。

# derived from vibe-astock@3c3b7c8 (github.com/lzw9560), Apache-2.0, modified
# Original author: Simon Lin (simonlin0423@gmail.com)
"""
from __future__ import annotations

import datetime
import json
import os
import threading
import uuid

from vr_paths import is_trading_day, prev_trading_date

try:
    from zoneinfo import ZoneInfo

    _CN_TZ = ZoneInfo("Asia/Shanghai")
except Exception:  # noqa: BLE001  无时区库退回本机时间（聊胜于无）
    _CN_TZ = None


def china_now() -> datetime.datetime:
    """上海时区当前时间（无 zoneinfo 时退回本机时间）。"""
    return datetime.datetime.now(_CN_TZ) if _CN_TZ else datetime.datetime.now()


def china_today() -> str:
    """上海时区今日 YYYY-MM-DD。"""
    return china_now().strftime("%Y-%m-%d")


def validate_trade_date(date: str) -> str:
    """严格解析 YYYY-MM-DD，拒绝非法/未来日期，返回规范化字符串。

    所有入口（API/CLI）的日期闸门：只有通过校验的规范日期才进入文件名和数据查询，
    杜绝 ``../../`` 目录穿越（vibe-astock #1/#7 修复）。
    """
    if not isinstance(date, str):
        raise ValueError(f"日期需为字符串，得到 {type(date).__name__}")
    try:
        d = datetime.datetime.strptime(date.strip(), "%Y-%m-%d").date()
    except ValueError:
        raise ValueError(f"非法日期 {date!r}，需 YYYY-MM-DD 格式")
    if d.strftime("%Y-%m-%d") > china_today():
        raise ValueError(f"拒绝未来日期 {date}")
    return d.strftime("%Y-%m-%d")


def atomic_write_json(path: str, payload: object) -> bool:
    """原子写 JSON 缓存。

    tmp + os.replace + fsync：断电/崩溃时不留"存在但内容为空"的缓存。
    写成功 True，失败 False（缓存失败从不影响调用方返回值）。
    """
    tmp = f"{path}.{uuid.uuid4().hex}.tmp"
    try:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(tmp, "w", encoding="utf-8") as fh:
            json.dump(payload, fh, ensure_ascii=False)
            fh.flush()
            os.fsync(fh.fileno())
        os.replace(tmp, path)
        return True
    except Exception:  # noqa: BLE001
        try:
            os.unlink(tmp)
        except OSError:
            pass
        return False


# ===== trade_calendar 4 函数（P4-T1b，移植自 duanxian/trade_calendar.py@3c3b7c8）=====
# is_settled / trade_dates_ending_at 基于 vr_paths 本地日历（零网络，节假日靠
# _A_SHARE_HOLIDAYS）；quote_trade_day / live_quotes_are_close_of 照搬 urllib
# 直连腾讯 qt.gtimg.cn（腾讯不封 IP，astock.py 同款底座，不走 em_get）。

_REF_STOCK = "sh600000"  # 参考股，判实时行情属于哪个交易日
_QUOTE_URL = "http://qt.gtimg.cn/q="
_F_QUOTE_TIME = 30  # 腾讯实时行情的时间戳字段位，形如 20260724161450
_QUOTE_DAY_TTL = 120.0
_QUOTE_DAY_BOUNDARIES = ((9, 15), (15, 5))  # 开盘（集合竞价）/ 收盘定稿状态边界
_quote_day_cache: dict[str, object] = {}
_quote_day_lock = threading.Lock()


def is_a_share_closed() -> bool:
    """A 股是否已收盘（上海时间 15:05 后）。移植自 util.py。"""
    n = china_now()
    return (n.hour, n.minute) >= (15, 5)


def latest_closed_session() -> str | None:
    """最近一个已收盘交易日（YYYY-MM-DD）。基于 vr_paths 本地日历，零网络。

    今天交易日 + 15:05 后 → 今天；否则上一交易日（已收盘）。
    """
    today_d = datetime.datetime.strptime(china_today(), "%Y-%m-%d").date()
    if is_trading_day(today_d) and is_a_share_closed():
        return today_d.isoformat()
    return prev_trading_date(today_d).isoformat()


def is_settled(date_str: str) -> bool:
    """date 的盘面数据是否已定稿、不会再变 —— 落盘缓存的唯一判据。

    基于 vr_paths 本地日历（零网络），节假日精度靠 ``_A_SHARE_HOLIDAYS``。
    """
    return date_str < china_today() or date_str == latest_closed_session()


def trade_dates_ending_at(end_date: str, n: int = 10) -> list[str]:
    """以 end_date 为终点向前取 n 个已收盘交易日（升序，含 end_date 若交易日）。

    未收盘的今天不算（与 last_trade_dates 口径一致）。基于 vr_paths.is_trading_day。
    """
    end_d = datetime.datetime.strptime(validate_trade_date(end_date), "%Y-%m-%d").date()
    dates: list[str] = []
    d = end_d
    safety = end_d - datetime.timedelta(days=n * 3 + 16)  # 节假日稀疏，足够取 n 个
    while len(dates) < n and d >= safety:
        if is_trading_day(d):
            dates.append(d.isoformat())
        d = d - datetime.timedelta(days=1)
    dates.reverse()
    # reverse 后 dates[-1]=最大日期；若==今天且未收盘则剔除（未定稿不算）
    if dates and dates[-1] == china_today() and not is_a_share_closed():
        dates = dates[:-1]
    return dates[-n:] if dates else []


def _seconds_to_next_boundary() -> float:
    """距下一个交易状态边界还有几秒（跨天算到明天那个）。"""
    n = china_now()
    now_s = (n.hour * 3600 + n.minute * 60 + n.second) + n.microsecond / 1e6
    for h, m in _QUOTE_DAY_BOUNDARIES:
        b = float(h * 3600 + m * 60)
        if b > now_s:
            return b - now_s
    first = float(_QUOTE_DAY_BOUNDARIES[0][0] * 3600 + _QUOTE_DAY_BOUNDARIES[0][1] * 60)
    return 24 * 3600 - now_s + first


def quote_trade_day() -> str | None:
    """参考股实时行情里的交易日（YYYY-MM-DD）。判不了返回 None。

    urllib 直连腾讯 qt.gtimg.cn（不封 IP，astock.py 同款底座）。缓存 TTL 120s，
    跨状态边界不入缓存（避免开盘前的慢请求覆盖开盘后的新结果）。
    """
    import time as _time

    now = _time.monotonic()
    until = _quote_day_cache.get("until")
    if isinstance(until, float) and now < until:
        return _quote_day_cache.get("day")  # type: ignore[return-value]

    with _quote_day_lock:
        now = _time.monotonic()
        until = _quote_day_cache.get("until")
        if isinstance(until, float) and now < until:
            return _quote_day_cache.get("day")  # type: ignore[return-value]

        deadline = now + min(_QUOTE_DAY_TTL, max(0.0, _seconds_to_next_boundary()))
        day: str | None = None
        try:
            import urllib.request

            raw = urllib.request.urlopen(_QUOTE_URL + _REF_STOCK, timeout=8).read().decode("gbk", "ignore")
            f = raw.split("~")
            ts = f[_F_QUOTE_TIME].strip() if len(f) > _F_QUOTE_TIME else ""
            if len(ts) >= 8 and ts[:8].isdigit():
                day = f"{ts[:4]}-{ts[4:6]}-{ts[6:8]}"
        except Exception:  # noqa: BLE001  判不了就判不了，交给调用方保守降级
            day = None
        if _time.monotonic() < deadline:
            _quote_day_cache.clear()
            _quote_day_cache.update({"day": day, "until": deadline})
        else:
            _quote_day_cache.clear()
        return day


def live_quotes_are_close_of(date_str: str) -> tuple[bool, str]:
    """现在拉实时行情，能否当作 date_str 的收盘涨跌幅？

    基于 quote_trade_day（实时行情交易日）+ latest_closed_session + is_a_share_closed。
    返回 (ok, reason)。ok=False **不代表那天算不出来**——已收盘场次走定稿记录
    （data.fetch_prev_pool）照样能算，那才是复盘类指标的首选路径。
    """
    if date_str != latest_closed_session():
        return False, f"{date_str} 非最近已收盘交易日；实时行情只有当前值，不能冒充历史收盘"
    qd = quote_trade_day()
    if qd is None:
        return False, "判不出实时行情属于哪个交易日（取数失败），保守起见不拿它当收盘用"
    if qd != date_str:
        return False, (f"实时行情当前属于 {qd} 这一场，不能当作 {date_str} 的收盘表现"
                       "—— 这只说明实时行情这条路不通；已收盘场次改用定稿记录")
    if date_str == china_today() and not is_a_share_closed():
        return False, (f"当前是交易时段，实时行情是今天盘中的价，"
                       f"不能当作 {date_str} 的收盘表现——今天这一场要等收盘才有定稿数据")
    return True, ""
