# -*- coding: utf-8 -*-
"""S104/S105：hithink-finance 数据源封装。

作 A 股结构性缺口唯一源——补东财/新浪/腾讯零供给的字段：
- 估值 PS_TTM / PCF_TTM（东财 full_valuation 结构性缺）
- 异动 / 飙升榜 / 热股榜（项目从无独立源）

**集成形态**（S105）：Python 直连 HTTP（`urllib`）替代 subprocess CLI。
subprocess 冷启动 ~1.0s，直连 ~0.1s（快 10 倍），数据一致。

**复刻 CLI envelope 转译层**（直读 dist/ 源码核实，S105 逆向）：
- 远端原始 envelope：``{code:int, message:str, request_id?:str, data:unknown}``
  （dist/infrastructure/fuyao/envelope.js）
- ``code == 0`` → 成功取 data；非 0 → 失败（businessError）
- 重试：``RETRYABLE_HTTP_STATUS_CODES={429,502,503,504}`` +
  ``RETRYABLE_BUSINESS_CODES={4001,5001,5002,5003}``，maxAttempts=3，
  指数退避 ``min(1000*2^attempt, 8000)+20% 抖动``，Retry-After 优先（上限 30s）
  （dist/infrastructure/fuyao/retry.js）

**硬约束**（grill 锁定）：
1. thscode 映射：复用 ``tencent.get_prefix``（6 位 → sh/sz/bj），转 ``.SH/.SZ/.BJ``。
   返回剥后缀还原裸 6 位 code（项目内部体系）。
2. 失败返 None（hithink_src 下游惯用空），记 log 含 CLI 风格 code（FUYAO_/UPSTREAM_HTTP_），
   **不透传远端 envelope**（否则下游拿 error 当数据崩）。
3. CLI 不在运行时调用，仅作升级后契约校验源（tools/hithink_parity_check.py）。

**§44 口径**：PS/PCF 是东财零供给的唯一源，无需 cross_validate 仲裁；
PE/PB 两源一致但不在本 spec 接仲裁（等 cross_validate 接线，第 3 层孤儿）。
"""
from __future__ import annotations

import json
import logging
import os
import random
import subprocess
import time
import urllib.error
import urllib.parse
import urllib.request
from typing import Any

from circuit_breaker import get_breaker
from data.sources._common import DependencyMissing
from data.sources.tencent import get_prefix

logger = logging.getLogger("vibe-research")

# ── 协议常量（复刻 dist/infrastructure/fuyao/retry.js + client.js）────────────
_BASE_URL = "https://fuyao.aicubes.cn"
_RETRYABLE_HTTP_STATUS = {429, 502, 503, 504}
_RETRYABLE_BUSINESS_CODES = {4001, 5001, 5002, 5003}
_MAX_ATTEMPTS = 3
_TIMEOUT_DEFAULT = 30
_TIMEOUT_VALUATION = 15
_TIMEOUT_SPECIAL = 30
_MAX_RETRY_AFTER_S = 30.0
_RETRY_BASE_MAX_S = 8.0  # min(1000*2^attempt, 8000)ms → 8s 上限

# ── endpoint 表（复刻 dist/contracts/remote-capabilities.js）─────────────────
_EP_VALUATION = "/api/a-share/valuations/snapshot"
_EP_SKYROCKET = "/api/a-share/special-data/skyrocket-list"
_EP_HOT_STOCK = "/api/a-share/special-data/hot-stock-list"
_EP_ANOMALY_LIST = "/api/a-share/special-data/anomaly-analysis-list"
_EP_ANOMALY_STOCK = "/api/a-share/special-data/anomaly-analysis-stock"
_EP_LIMIT_UP_POOL = "/api/a-share/special-data/limit-up-pool"  # 涨停池（按历史日期）
_EP_AUCTION_SNAPSHOT = "/api/a-share/auction/snapshot"  # 集合竞价快照（今日 only，不可补历史）

# 估值快照 5min TTL 缓存（盘中估值不变，省请求）
_valuation_cache: dict[tuple[str, ...], tuple[float, dict[str, dict]]] = {}
_VALUATION_CACHE_TTL = 300.0


# ── Key 解析 + envelope 转译 + 有界重试 ────────────────────────────────────────

def _resolve_api_key() -> str:
    """解析 hithink API Key：优先 env HITHINK_FINANCE_API_KEY，fallback macOS keychain。

    CLI 读取优先级（dist/infrastructure/credentials/api-key-provider.js）：
    explicit > env > keyring。本封装无 explicit 参数，故 env > keychain。
    都失败抛 DependencyMissing（复用 akshare 同款，下游惯用降级）。
    """
    k = os.environ.get("HITHINK_FINANCE_API_KEY")
    if k:
        return k
    # fallback macOS keychain（本机自托管场景；CLI auth login 写入处）
    try:
        r = subprocess.run(
            ["security", "find-generic-password", "-s", "hithink-finance", "-a", "profile:default", "-w"],
            capture_output=True, text=True, timeout=3,
        )
        if r.returncode == 0 and r.stdout.strip():
            return r.stdout.strip()
    except (subprocess.SubprocessError, OSError):
        pass
    raise DependencyMissing(
        "hithink API Key 未配置：设 HITHINK_FINANCE_API_KEY（.env）或 hithink-finance auth login"
    )


def _retry_delay(attempt: int, retry_after: str | None = None) -> float:
    """复刻 retry.js：Retry-After 优先（上限 30s），否则指数退避 + 20% 抖动。

    retry.js: base = min(1000 * 2^attempt, 8000)ms + base * 0.2 * random()。
    """
    if retry_after:
        try:
            return min(float(retry_after), _MAX_RETRY_AFTER_S)
        except (TypeError, ValueError):
            pass
    base = min(1000 * (2 ** attempt), 8000) / 1000.0  # 秒
    return base + base * 0.2 * random.random()


def _http_get(path: str, query: dict[str, Any], timeout: int = _TIMEOUT_DEFAULT) -> dict | None:
    """直连 fuyao，复刻 CLI envelope 转译 + 有界重试。

    返 ``data`` 字段（``code == 0`` 时）；失败/熔断/超时返 None（下游惯用空，不透传 envelope）。
    重试耗尽 + 非重试错误 → record_failure + 返 None。

    envelope 转译（client.js request）：``code==0`` 成功取 data；
    非 0 业务错误（1000-1999 validation / 2000-2999 auth / 其余 upstream）。
    """
    breaker = get_breaker("hithink")
    if not breaker.allow_request():
        logger.warning("[hithink] 熔断中，快速失败 path=%s", path)
        return None

    try:
        key = _resolve_api_key()
    except DependencyMissing:
        logger.warning("[hithink] API Key 未配置，path=%s", path)
        return None

    url = _BASE_URL + path + "?" + urllib.parse.urlencode(query)
    last_err = ""
    for attempt in range(_MAX_ATTEMPTS):
        try:
            req = urllib.request.Request(
                url, headers={"X-api-key": key, "accept": "application/json"}
            )
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                body = json.loads(resp.read())
            code = body.get("code")
            data = body.get("data")
            if code == 0:
                breaker.record_success()
                return data if isinstance(data, dict) else {"item": data}
            # code != 0：业务错误
            last_err = f"FUYAO_{code} {str(body.get('message'))[:100]}"
            if code in _RETRYABLE_BUSINESS_CODES and attempt < _MAX_ATTEMPTS - 1:
                time.sleep(_retry_delay(attempt))
                continue
            breaker.record_failure()
            logger.warning("[hithink] biz err %s path=%s", last_err, path)
            return None
        except urllib.error.HTTPError as e:
            last_err = f"UPSTREAM_HTTP_{e.code}"
            if e.code in _RETRYABLE_HTTP_STATUS and attempt < _MAX_ATTEMPTS - 1:
                ra = e.headers.get("retry-after") if e.headers else None
                time.sleep(_retry_delay(attempt, ra))
                continue
            breaker.record_failure()
            logger.warning("[hithink] HTTP %s path=%s", e.code, path)
            return None
        except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as e:
            last_err = f"{type(e).__name__}:{str(e)[:80]}"
            if attempt < _MAX_ATTEMPTS - 1:
                time.sleep(_retry_delay(attempt))
                continue
            breaker.record_failure()
            logger.warning("[hithink] net err %s path=%s", last_err, path)
            return None
    # 循环正常结束（全重试耗尽）—— breaker 已在最后一次失败 record，保险再记一次
    breaker.record_failure()
    logger.warning("[hithink] 重试耗尽 path=%s last=%s", path, last_err)
    return None


# ── thscode 映射（S104 保留，复用 tencent.get_prefix）─────────────────────────

def _to_thscode(code: str) -> str:
    """6 位裸 code → hithink thscode（带交易所后缀）。

    复用 tencent.get_prefix（6/9/5 开头→SH，8 开头→BJ，其余→SZ）。
    例：600519 → 600519.SH，000001 → 000001.SZ，830xxx → 830xxx.BJ。
    """
    return f"{code}.{get_prefix(code).upper()}"


def _strip_thscode(thscode: str) -> str:
    """thscode（600519.SH）→ 裸 6 位 code（600519）。无后缀原样返。"""
    return thscode.split(".")[0]


def _items(data: dict[str, Any]) -> list[dict[str, Any]]:
    """hithink data → item 列表。data 可能是 {item:[...]} / {items:[...]} / 裸 list。"""
    if isinstance(data, dict):
        return data.get("item") or data.get("items") or []
    if isinstance(data, list):
        return data
    return []


# ── 5 对外函数（S104 接口不变，S105 改调 _http_get）────────────────────────────

def valuation_snapshot(codes: list[str]) -> dict[str, dict]:
    """批量估值快照——补东财结构性缺的 PS_TTM / PCF_TTM。

    返 {裸code: {pe_ttm, pe_mrq, pb_mrq, ps_ttm, pcf_ttm}}。
    hithink 失败/熔断 → 返 {}（调用方降级，PS/PCF 仍 None，诚实缺失）。
    5min TTL 缓存（盘中估值不变，省请求）。
    """
    if not codes:
        return {}
    cache_key = tuple(sorted(codes))
    now = time.time()
    cached = _valuation_cache.get(cache_key)
    if cached and now - cached[0] < _VALUATION_CACHE_TTL:
        return cached[1]

    thscodes = ",".join(_to_thscode(c) for c in codes)
    data = _http_get(_EP_VALUATION, {"thscodes": thscodes}, _TIMEOUT_VALUATION)
    if data is None:
        return {}
    out: dict[str, dict] = {}
    for it in _items(data):
        ths = it.get("thscode") or it.get("code") or ""
        bare = _strip_thscode(ths)
        if not bare:
            continue
        out[bare] = {
            "pe_ttm": it.get("pe_ttm"),
            "pe_mrq": it.get("pe_mrq"),
            "pb_mrq": it.get("pb_mrq"),
            "ps_ttm": it.get("ps_ttm"),
            "pcf_ttm": it.get("pcf_ttm"),
        }
    if out:
        _valuation_cache[cache_key] = (now, out)
    return out


def skyrocket(period: str = "day") -> list[dict]:
    """飙升榜。返 [{code, name, rank, heat, rank_change, rank_trend}]。

    period: hithink 只接受 day / hour。
    """
    data = _http_get(_EP_SKYROCKET, {"period": period}, _TIMEOUT_SPECIAL)
    if data is None:
        raise RuntimeError("hithink 飙升榜暂不可达（熔断/离线/API Key 缺失）")
    return _normalize_rank_items(_items(data))


def hot_stock(period: str = "day") -> list[dict]:
    """热股榜。返同飙升榜结构。period: day / hour。"""
    data = _http_get(_EP_HOT_STOCK, {"period": period}, _TIMEOUT_SPECIAL)
    if data is None:
        raise RuntimeError("hithink 热股榜暂不可达（熔断/离线/API Key 缺失）")
    return _normalize_rank_items(_items(data))


def anomaly_list(tag_codes: str | None = None) -> list[dict]:
    """今日异动分析。返 [{code, name, ...}]。盘后可能空（item=0）诚实返 []；
    源断（_http_get None：熔断/离线/Key 缺）raise RuntimeError（S120，不伪装空榜喂 LLM）。"""
    query: dict[str, Any] = {}
    if tag_codes:
        query["tag_codes"] = tag_codes
    data = _http_get(_EP_ANOMALY_LIST, query, _TIMEOUT_SPECIAL)
    if data is None:
        raise RuntimeError("hithink 异动榜暂不可达（熔断/离线/API Key 缺失）")
    return _normalize_anomaly_items(_items(data))


def anomaly_stock(codes: list[str]) -> list[dict]:
    """个股异动（≤50 只 thscodes）。返 [{code, name, ...}]。"""
    if not codes or len(codes) > 50:
        return []
    thscodes = ",".join(_to_thscode(c) for c in codes)
    data = _http_get(_EP_ANOMALY_STOCK, {"thscodes": thscodes}, _TIMEOUT_SPECIAL)
    if data is None:
        return []
    return _normalize_anomaly_items(_items(data))


def limit_up_pool(date_str: str) -> list[dict]:
    """涨停池（按历史日期，盘后可查）——交叉验证 baostock 派生涨停。

    date_str: 'YYYY-MM-DD'。转 Beijing 午夜 ms（hithink ``date_ms`` 契约）。
    返 [{code, name, lbc?}]（lbc 连板数若 hithink 提供，字段名未实测取多个候选）。
    hithink 失败/熔断/Key 缺 → 返 []（不伪装，调用方降级，防封路径仍走 circuit_breaker）。
    """
    from datetime import datetime, timedelta, timezone

    tz_bj = timezone(timedelta(hours=8))
    try:
        dt = datetime.strptime(date_str, "%Y-%m-%d").replace(tzinfo=tz_bj)
    except ValueError:
        logger.warning("[hithink] limit_up_pool 非法日期 %s", date_str)
        return []
    date_ms = int(dt.timestamp() * 1000)
    data = _http_get(_EP_LIMIT_UP_POOL, {"date_ms": date_ms}, _TIMEOUT_SPECIAL)
    if data is None:
        return []
    out: list[dict[str, Any]] = []
    for it in _items(data):
        ths = it.get("thscode") or it.get("code") or ""
        bare = _strip_thscode(ths)
        if not bare:
            continue
        row: dict[str, Any] = {"code": bare, "name": it.get("name", "")}
        for k in ("limit_times", "continuous", "lianban", "lbc", "limit_up_times"):
            if k in it:
                row["lbc"] = it.get(k)
                break
        out.append(row)
    return out


def auction_snapshot(codes: list[str], stage: str = "final") -> list[dict]:
    """集合竞价快照（今日 only，不可补历史）——§44 reframe 标记的最未证否盘中 edge。

    竞价量比（``auction_volume_ratio``）是 S152/S156 证否封板时间/秒板后仍未证否的
    盘中维度。本函数把 hithink ``/api/a-share/auction/snapshot`` 端点接线进项目
    （S167 spec §2 表 "竞价量比 9:15-9:25" 行原标 "needs new source integration"）。

    thscodes ≤100/批（endpoint 硬限 "at most 100 raw tokens"），超出自动分批。
    stage: ``live``（09:15-09:25 实时竞价演化，orders 可撤/不可撤两段）|
    ``final``（09:25 集合 match 终态，开盘价确定）。返每只归一 dict，含：

    - ``auction_volume_ratio``（§44 关键信号：竞价量比）
    - ``auction_price`` / ``auction_pct``（竞价价 / 竞价涨跌幅 vs 昨收）
    - ``auction_volume`` / ``auction_amount`` / ``auction_unmatched``（竞价量/额/未匹配）
    - ``auction_turnover_pct`` / ``auction_yesterday_ratio_pct``（竞价换手 / 竞价量占昨量）
    - ``pre_close_price`` / ``open_price`` / ``last_price`` / ``float_market_cap``
    - ``source_timestamp`` / ``auction_phase`` / ``data_status``（源态透传，诚实标注：
      非交易日 ``phase=closed, status=not_ready``，item 仍返昨日终态——累积时由调用方
      按 ``data_status`` 过滤/标注，不臆造当日竞价）

    hithink 失败/熔断/Key 缺 → 本批跳过返已取部分（最终可能 []），不抛（调用方降级
    记 data_status=degraded）。返字段缺值 None（不臆造）。
    """
    if not codes or stage not in ("live", "final"):
        return []
    out: list[dict[str, Any]] = []
    meta: dict[str, Any] = {}  # 顶层 timestamp/auction_phase/data_status（首批取，透传每行）
    for i in range(0, len(codes), 100):
        batch = codes[i:i + 100]
        thscodes = ",".join(_to_thscode(c) for c in batch)
        data = _http_get(
            _EP_AUCTION_SNAPSHOT,
            {"thscodes": thscodes, "stage": stage},
            _TIMEOUT_SPECIAL,
        )
        if data is None:
            continue  # 本批失败，下批继续（部分降级，不整体抛）
        if not meta:
            meta = {k: data.get(k) for k in ("timestamp", "auction_phase", "data_status")
                    if k in data}
        for it in _items(data):
            ths = it.get("thscode") or it.get("ticker") or ""
            bare = _strip_thscode(ths) if "." in str(ths) else str(ths)
            if not bare:
                continue
            out.append({
                "code": bare,
                "name": it.get("name", ""),
                "stage": stage,
                "auction_price": it.get("auction_price"),
                "auction_pct": it.get("auction_pct"),
                "auction_volume": it.get("auction_volume"),
                "auction_amount": it.get("auction_amount"),
                "auction_unmatched": it.get("auction_unmatched"),
                "auction_turnover_pct": it.get("auction_turnover_pct"),
                "auction_yesterday_ratio_pct": it.get("auction_yesterday_ratio_pct"),
                "auction_volume_ratio": it.get("auction_volume_ratio"),
                "pre_close_price": it.get("pre_close_price"),
                "open_price": it.get("open_price"),
                "last_price": it.get("last_price"),
                "float_market_cap": it.get("float_market_cap"),
                "source_timestamp": meta.get("timestamp"),
                "auction_phase": it.get("auction_phase") or meta.get("auction_phase"),
                "data_status": it.get("data_status") or meta.get("data_status"),
            })
    return out


def _normalize_rank_items(items: list[dict[str, Any]]) -> list[dict]:
    """飙升/热股榜 item 归一：thscode→code，保留 rank/heat/rank_change/rank_trend。"""
    out = []
    for it in items:
        ths = it.get("thscode") or it.get("code") or ""
        bare = _strip_thscode(ths)
        if not bare:
            continue
        out.append({
            "code": bare,
            "name": it.get("name", ""),
            "rank": it.get("rank"),
            "heat": it.get("heat"),
            "rank_change": it.get("rank_change"),
            "rank_trend": it.get("rank_trend"),
        })
    return out


def _normalize_anomaly_items(items: list[dict[str, Any]]) -> list[dict]:
    """异动 item 归一：thscode→code，原样保留 hithink 字段（异动 schema 未实测全字段）。"""
    out = []
    for it in items:
        ths = it.get("thscode") or it.get("code") or ""
        bare = _strip_thscode(ths)
        if not bare:
            continue
        row = {"code": bare, "name": it.get("name", "")}
        for k, v in it.items():
            if k not in ("thscode", "ticker", "name"):
                row[k] = v
        out.append(row)
    return out
