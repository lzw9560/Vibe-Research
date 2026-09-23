# -*- coding: utf-8 -*-
"""S008 日K线解析器——多源 fallback 链（baostock → 东方财富 → hithink → cache）。

2026-09-20 恢复多源：baostock 单源后 baostock 把用户 IP 拉黑
（``10001011 黑名单用户``），单点风险显现。现改顺序 fallback：
baostock 优先（免费匿名 login，qfq 前复权，正常最稳）→ 失败/空/黑名单
fallback 东方财富日K（via ``em_get`` 限流/熔断/代理探测防封，复用
``akshare_src._fetch_cyq_klines`` 验证过的 push2his kline/get 端点）→
东财也封 fallback hithink 日K（fuyao HTTP 独立通道，非东财/腾讯域名不共享
封禁）→ 三源都失败用本地 cache（``baostock_kline_cache.json`` lazy load 进程内复用）。
不再单点 baostock。

2026-09-23 加 hithink 第三源：baostock 黑名单（10001011）+ 东财 push2* IP 封
两源都封时，hithink-finance fuyao HTTP 是独立数据通道（fuyao.aicubes.cn）。
hithink_src.fetch_kline 已有 _http_get envelope 转译 + 有界重试 + 熔断，复用之。

**顺序 fallback 而非并发抢答**：baostock 黑名单报错快（非超时），顺序不拖慢
正常情况；并发会在 baostock 正常时也调东财，浪费 em_get 限流配额且 push2his
被封拖慢。顺序 fallback 语义清晰、省配额、易测试。

保留多源框架（``_SOURCES`` 注册表 + ``_SOURCE_ADJUST`` 口径 + ``sources``/
``adjust`` 参数 + ``list_sources``/``adjust_of`` 接口）——将来加源只改
``_SOURCES`` + ``_SOURCE_ADJUST`` + 写 ``_xxx`` 函数，消费者零变更。

返 tuple[list[dict], str | None]：bars + 命中源名（"baostock"/"eastmoney"/
"hithink"/"cache"）。全失败返 ([], None)——不抛、不臆造，消费者按空决策（诚实无数据）。

字段约定（raw bar dict）：date/open/close/high/low/volume/amount/ma5/ma10/ma20，
缺字段=None（baostock/东财均无 ma，消费侧 ``_compute_ma`` 自算，
strategies/pattern_scan.py:170-199，不依赖 kline 返 ma 字段），60 bars 够
（:177 len<20 check）。
"""
from __future__ import annotations

import logging

log = logging.getLogger(__name__)


def _baostock(code: str) -> list[dict]:
    """baostock 日K（qfq 前复权，首选源——免费匿名 login，无 IP 限制免防封）。

    singleton login（baostock_src.ensure_login 进程级 + _BS_LOCK 串行 query 防线程
    竞争），adjustflag=2 qfq，返最近 60 交易日 bars（start=now-120 天容纳周末）。
    baostock 无 ma5/10/20——消费侧 _compute_ma 自算（pattern_scan:170-199）。

    黑名单/超时/空返 []（不抛、不臆造），由 fetch_kline fallback 东财。
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


def _eastmoney(code: str) -> list[dict]:
    """东方财富日K（qfq 前复权，fallback 源——baostock 黑名单/超时/空时启用）。

    走 ``em_get``（data.transport.eastmoney_get）限流/熔断/代理探测防封，
    复用 ``akshare_src._fetch_cyq_klines`` 验证过的 push2his kline/get 端点。
    params: secid（1.沪 / 0.深）、klt=101 日K、fqt=1 前复权（对齐 baostock
    adjustflag=2）、ut=_ZTB_UT 日K通用公开 token、fields2=f51-f56 6 字段、lmt=60。
    em_get 自带 breaker('eastmoney') + 0.3s 限流 + 直连/代理探测 + timeout=8。

    返最近 60 交易日 bars，字段映射：f51 date / f52 open / f53 close / f54 high /
    f55 low / f56 volume（amount/ma 无 → None）。失败/空/熔断/异常返 []（不抛、
    不臆造），由 fetch_kline fallback cache。
    """
    from datetime import datetime  # noqa: PLC0415
    from data.transport import eastmoney_get as em_get  # noqa: PLC0415 — 防封底线
    from .eastmoney import _ZTB_UT  # noqa: PLC0415 — 日K通用公开 token（非密钥）

    # secid 映射：6 开头（沪市主板 60xxxx / 科创 688xxx）→ 1.，其余（深市主板 /
    # 创业板 / 北交所）→ 0.。对齐 akshare_src._fetch_cyq_klines:251 的映射。
    secid = f"{1 if code.startswith('6') else 0}.{code}"
    params = {
        "secid": secid,
        "fields1": "f1,f2,f3",
        "fields2": "f51,f52,f53,f54,f55,f56",  # date,open,close,high,low,volume
        "klt": "101",   # 日K
        "fqt": "1",     # 前复权（对齐 baostock adjustflag=2 qfq）
        "end": datetime.now().date().strftime("%Y%m%d"),
        "lmt": "60",    # 最近 60 条（对齐 baostock 60 bars）
        "ut": _ZTB_UT,
    }
    headers = {"Referer": "https://quote.eastmoney.com/"}
    try:
        r = em_get("https://push2his.eastmoney.com/api/qt/stock/kline/get",
                   params=params, headers=headers, timeout=8)
        data = r.json()
    except Exception as e:  # noqa: BLE001 — em_get 熔断 OPEN raise / 请求异常 / JSON 失败
        log.warning("kline eastmoney em_get failed for %s: %s", code, repr(e)[:200])
        return []

    klines = (data.get("data") or {}).get("klines")
    if not klines:
        return []  # 该股无数据 / 新股 / body 空

    def _to_float(s: str) -> float | None:
        try:
            return float(s)
        except (TypeError, ValueError):
            return None

    bars: list[dict] = []
    for line in klines:
        parts = line.split(",")
        if len(parts) < 6:
            continue  # 坏行跳过
        # f51-f56: date,open,close,high,low,volume
        o = _to_float(parts[1]); c = _to_float(parts[2])
        h = _to_float(parts[3]); lo = _to_float(parts[4])
        v = _to_float(parts[5])
        if any(x is None for x in (o, c, h, lo)):
            continue  # 关键数值缺失行跳过
        bars.append({
            "date": parts[0],
            "open": o, "close": c,
            "high": h, "low": lo,
            "volume": int(v) if v else None,
            "amount": None,  # 东财 kline/get f56 后无 amount 字段（f57 是 amount 但未取）
            "ma5": None, "ma10": None, "ma20": None,
        })
    return bars[-60:] if len(bars) > 60 else bars


def _hithink(code: str) -> list[dict]:
    """hithink 日K（qfq 前复权，fallback 源——baostock+东财都封/失败时启用）。

    baostock 黑名单 + 东财 push2 IP 封时，hithink 是独立通道
    （fuyao.aicubes.cn 非 东财/腾讯域名，不共享封禁风险）。直连 fuyao HTTP
    （hithink_src._http_get）复用 envelope 转译 + 有界重试 + 熔断，
    adjust=forward 前复权（对齐 baostock adjustflag=2 / 东财 fqt=1）。

    返最近 60 交易日 bars（start=now-120 天容纳周末取 60 交易日）。
    hithink 无 ma5/10/20——消费侧 _compute_ma 自算（pattern_scan:170-199）。
    失败/熔断/Key 缺/空 → 返 []（不抛、不臆造），由 fetch_kline fallback cache。
    """
    from datetime import datetime, timedelta  # noqa: PLC0415
    from data.sources.hithink_src import fetch_kline  # noqa: PLC0415

    now = datetime.now()
    start_ms = int((now - timedelta(days=120)).timestamp() * 1000)
    end_ms = int(now.timestamp() * 1000)
    bars_raw = fetch_kline(code, start_ms, end_ms, adjust="forward")
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


# --- cache fallback（三源都失败时的最后兜底）---

def _load_cache() -> dict:
    """全量 load（deprecated；生产走 _cache_bars per-code 内部 get_bars）。

    从 SQLite 全量读（2.19GB 峰值一次性 local，非常驻）。原模块级 _CACHE + mtime
    已删——SQLite 是源，refresh upsert 增量更新。保留接口兼容 offline 工具。
    """
    from engine.kline_cache_store import load_all
    return load_all()


def _cache_bars(code: str) -> list[dict]:
    """从 cache 取 code 最近 60 bars，映射到 bar dict 格式。

    cache bars 是 baostock 10 字段（date/open/high/low/close/volume/amount/turn/
    pctChg/isST），映射到 9 字段（date/open/close/high/low/volume/amount + ma=None）。
    code 不在 cache / cache 不存在返 []（不臆造）。
    """
    from engine.kline_cache_store import get_bars
    bars = get_bars(code)
    if not bars:
        return []
    out: list[dict] = []
    for r in bars[-60:]:
        vol = r.get("volume")
        amt = r.get("amount")
        out.append({
            "date": r.get("date"),
            "open": r.get("open"), "close": r.get("close"),
            "high": r.get("high"), "low": r.get("low"),
            "volume": int(vol) if vol else None,
            "amount": float(amt) if amt else None,
            "ma5": None, "ma10": None, "ma20": None,
        })
    return out


# 源链注册表（策略集，按名字）。2026-09-20：baostock + 东方财富（fallback）。
# 2026-09-23：加 hithink 第三源（baostock 黑名单 + 东财 push2 IP 封时独立通道）。
# cache 不在 _SOURCES（cache 是最后兜底，非"源"，不走 sources/adjust 筛选）。
# 加源食谱：写 _xxx(code) 函数 + 在 _SOURCES 追加名字 + _SOURCE_ADJUST 声明口径。
_SOURCES: list[str] = ["baostock", "eastmoney", "hithink"]

# 各源原生复权口径（单一事实源）。消费者传 adjust="qfq" 时只走口径匹配的源。
# baostock adjustflag=2 = 前复权 qfq；东财 fqt=1 = 前复权 qfq；hithink adjust=forward = 前复权 qfq。
_SOURCE_ADJUST: dict[str, str] = {
    "baostock": "qfq",
    "eastmoney": "qfq",
    "hithink": "qfq",
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

    顺序 fallback 链：baostock 优先 → 失败/空/黑名单 fallback 东方财富（em_get
    防封）→ 东财也封 fallback hithink（fuyao HTTP 独立通道）→ 三源都失败用
    cache（lazy load baostock_kline_cache.json）→ cache 也没有返 ([], None)。
    不抛、不臆造，消费者按空决策。

    baostock 黑名单报错快（非超时），顺序 fallback 不拖慢正常情况。sources/adjust
    参数限定源链子集/口径——空链返 ([], None)。
    """
    chain = _chain(sources, adjust)
    if not chain:
        return [], None
    for name in chain:
        try:
            bars = _call(name, code)
            if bars:
                return bars, name
        except Exception as e:  # noqa: BLE001 — 源失败吞异常，试下一个源
            log.warning("kline source %s failed for %s: %s", name, code, repr(e)[:200])
            continue
    # 三源都失败 → cache fallback（最后兜底）。仅 sources 未限定时触发——
    # sources 参数限定源链子集，cache 不是"源"不在 _SOURCES，限定时不走 cache
    # （sources 限定意味着调用方接受"这些源都失败就返空"）。
    if sources is not None:
        log.warning("kline sources=%s all empty/failed for %s", sources, code)
        return [], None
    try:
        cached = _cache_bars(code)
        if cached:
            log.info("kline all sources failed for %s, using cache (%d bars)", code, len(cached))
            return cached, "cache"
    except Exception as e:  # noqa: BLE001 — cache 失败也吞，诚实返空
        log.warning("kline cache fallback failed for %s: %s", code, repr(e)[:200])
    log.warning("kline all sources + cache empty for %s", code)
    return [], None


def list_sources(adjust: str | None = None) -> list[str]:
    """可用源名（按链顺序）。传 adjust 只返该口径源，供诊断/配置。

    注：返的是 _SOURCES（baostock/eastmoney/hithink），不含 cache（cache 是最后兜底非"源"）。
    """
    return _chain(None, adjust)
