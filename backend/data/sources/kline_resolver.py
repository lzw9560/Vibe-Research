# -*- coding: utf-8 -*-
"""S008 多源异构日K线解析器——数据总线上的解耦层。

模式：**职责链 + 策略**。每个源是一个可互换的策略（实现 ``KlineSource``
契约），解析器按链顺序尝试、首个成功且非空即返。**不硬编码任何单源策略**：
不同网络环境（开发/家庭/VPN/远程）下不同源可达——本机公司网对东财 push2his
IP-封禁但对百度/新浪不限流（2026-07-31 实测），其它网络可能反过来——链路按
"独立源 + 回退"组织，哪个通用哪个。

消费者（t16_panel_train 等）只调 ``astock.kline_multi(code)``，与具体源解耦：
源增删/切换只改本模块 ``_SOURCES`` 注册表，消费者零变更（与 astock 门面契约一致）。

**统一复权口径（adjust 契约）**：各源原生口径不一——百度前复权（qfq，2026-07-31 实测：
茅台 2018 收盘 413 vs 新浪 raw 730，历史价下调、最新价与 raw 收敛→qfq 签名）、akshare qfq
（``adjust="qfq"`` 显式）、新浪/mootdx 不复权（raw）。混用口径会污染收益特征与标签（除权日
raw 序列单日 ~-10% 假跌、历史价虚高 7-14%）。消费者传 ``adjust="qfq"`` 时，**只走能原生提供
该口径的源**（百度+akshare），不回退 raw 源——**不臆造复权因子**（无除权日历则不可重算，
诚实地按源能力筛选而非编造）。无 qfq 源可达即诚实返空，消费者按空剔除。

加源食谱（维护迭代）：
1. 写 ``def _xxx(code) -> list[dict]`` 返 raw bars（字段对齐 §字段约定，失败抛异常）；
2. 在 ``_SOURCES`` 追加 ``("xxx", _xxx)``，并在 ``_SOURCE_ADJUST`` 声明其原生口径。
源依赖重（mootdx/akshare）用函数内 lazy import，避免 ``import astock`` 炸链。

返 ``tuple[list[dict], str | None]``：bars + 命中源名（可观测、可记日志）。
全源失败返 ``([], None)``——不抛、不臆造，消费者按空 bars 决策（诚实无数据）。

字段约定（raw bar dict）：``date/open/close/high/low/volume/amount/ma5/ma10/ma20``，
缺字段=``None``（不臆造），对齐 ``mappers.baidu_kline_from_dict`` / ``kline_from_mootdx``。
"""
from __future__ import annotations

import logging

log = logging.getLogger(__name__)


# ── 各源实现（lazy import 重依赖，函数即策略，name 用注册表绑定）─────────────

def _baidu(code: str) -> list[dict]:
    """百度股市通日K线（urllib，不封 IP，自带 MA5/10/20）。"""
    from data.sources.baidu import fetch_raw
    return fetch_raw(code)


def _sina(code: str) -> list[dict]:
    """新浪日K线（urllib，不封 IP，无 MA）。"""
    from data.sources.sina import fetch_raw
    return fetch_raw(code)


def _mootdx(code: str) -> list[dict]:
    """mootdx TDX 日K线（TCP 7709，惰性）。"""
    from data.sources.mootdx_src import kline
    return kline(code)


def _akshare(code: str) -> list[dict]:
    """akshare stock_zh_a_hist（东财 push2his，多数公司网被封，链尾兜底）。"""
    from data.sources.akshare_src import _akshare
    ak = _akshare()
    df = ak.stock_zh_a_hist(symbol=code, period="daily", adjust="qfq")
    bars: list[dict] = []
    for _, r in df.iterrows():
        vol = r.get("成交量")
        amt = r.get("成交额")
        bars.append({
            "date": str(r["日期"]),
            "open": float(r["开盘"]), "close": float(r["收盘"]),
            "high": float(r["最高"]), "low": float(r["最低"]),
            "volume": int(vol) if pd_notna(vol) else None,
            "amount": float(amt) if pd_notna(amt) else None,
            "ma5": None, "ma10": None, "ma20": None,
        })
    return bars


def pd_notna(v) -> bool:
    """pandas notna 的惰性版（避免顶层 import pandas 重依赖）。"""
    try:
        from pandas import notna
        return bool(notna(v))
    except Exception:
        return v is not None


# 源链注册表（策略集，按名字）。顺序：独立不封 IP 源在前，东财 push2his 兜底。
# 按名查找（非绑函数引用）——可测试、可热替换：monkeypatch ``_<name>`` 即生效。
# 增删源：写 ``_<name>(code)`` 函数 + 在此表加/删名字，消费者零变更。
_SOURCES: list[str] = ["baidu", "sina", "mootdx", "akshare"]

# 各源原生复权口径（单一事实源）。消费者传 ``adjust="qfq"`` 时只走口径匹配的源——
# 不回退到 raw 源（混用污染收益），不臆造复权因子重算（无除权日历则不可重算）。
#   "qfq"  = 前复权（百度默认、akshare ``adjust="qfq"``）
#   "none" = 不复权（新浪 getKLineData 无 adjust 参数、mootdx bars 默认 raw）
# 2026-07-31 实测：百度对 600519 2018 收盘返 413（raw ~730），最新日与新浪 raw
# 收敛→qfq 签名确认。akshare qfq 与百度 qfq 应一致（同前复权口径）。
_SOURCE_ADJUST: dict[str, str] = {
    "baidu": "qfq",
    "sina": "none",
    "mootdx": "none",
    "akshare": "qfq",
}


def adjust_of(name: str) -> str | None:
    """某源的原生复权口径（未知源返 None）。供消费者观测/日志。"""
    return _SOURCE_ADJUST.get(name)


def _call(name: str, code: str) -> list[dict]:
    """按名查找源函数并调用（monkeypatch ``_<name>`` 即生效，便于测试）。"""
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
    """多源回退取日K线。返 (bars, source_name)；全失败返 ([], None)。

    ``sources`` 可限定子集（如 ["baidu","sina"]），默认全链。某源抛任何异常
    （网络/限流/依赖缺失）→ 记 warning 并回退下一源，不中断。

    ``adjust`` 统一复权口径契约：传 ``"qfq"`` 时只走原生前复权源（百度/akshare），
    不回退 raw 源（新浪/mootdx）——**避免混用口径污染收益特征与标签**（除权日 raw
    序列假跌、历史价虚高）。无匹配口径源可达即诚实返空（不臆造复权因子重算）。
    消费者按空 bars 剔除该股（诚实无数据）。口径取值见 ``_SOURCE_ADJUST``。
    """
    for name in _chain(sources, adjust):
        try:
            bars = _call(name, code)
        except Exception as e:  # noqa: BLE001 — 多源回退，吞异常回退下一源
            log.warning("kline source %s failed for %s: %s", name, code, repr(e)[:200])
            continue
        if bars:
            return bars, name
        log.warning("kline source %s returned empty for %s", name, code)
    return [], None


def list_sources(adjust: str | None = None) -> list[str]:
    """可用源名（按链顺序）。传 ``adjust`` 只返该口径源，供诊断/配置。"""
    return _chain(None, adjust)
