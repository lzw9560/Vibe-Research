# -*- coding: utf-8 -*-
"""S020 worldmonitor 决策因子源（HTTP MCP JSON-RPC 客户端 + 纯解析 + 缓存）。

worldmonitor（koala73/worldmonitor，AGPL-3.0）聚合 65+ 外部源、500+ 资讯、CII 31
国不稳定指数、Finance Radar、跨源关联。远程 MCP endpoint ``https://worldmonitor.app/mcp``
（streamable HTTP，MCP 2025-06-18，server v1.15.0），每工具支持 ``jmespath`` 投影
（80–95% token 缩减）。

**独立通道 + 熔断**（与 S019 Fred 同构，非 em_get）：直接 ``requests`` POST JSON-RPC，
``circuit_breaker.get_breaker("worldmonitor")`` 熔断（5 失败 OPEN / 60s 恢复），读
``VR_HTTP_PROXY`` 走代理。失败/无 key 返 None，不臆造。空结果不缓存（对齐 market._cached）。

合规（§1.2 弱合规）：只消费 API，不 vendor 源码（AGPL 风险）；输出宏观/地缘客观数据，
不预置标的/不推荐/不预测涨跌。pro key 存 ``VR_DATA_DIR``，env 读，绝不进 git/日志。

解析为纯函数（入参 JSON → 出参 dict/list），缺字段→None，可单测；合成分标注
``source="worldmonitor_composite"``，只作输入之一不作唯一依据。
"""
from __future__ import annotations

import json
import logging
import os
import time
from typing import Any, Callable, TypeVar

from circuit_breaker import get_breaker
from vr_paths import resolve_data_dir

log = logging.getLogger(__name__)

T = TypeVar("T")

WORLDMONITOR_MCP_URL = "https://worldmonitor.app/mcp"
_MCP_PROTOCOL_VERSION = "2025-06-18"

# 缓存 TTL（秒）。CII/热点/地缘慢变 24h；market_data 5min（对齐 market._TTL）；资讯聚类 1h。
_TTL_SLOW = 86400       # CII / hotspot / country_macro / tariff
_TTL_MARKET = 300       # market_data（商品/外汇快照）
_TTL_NEWS = 3600        # news_intelligence / news_clusters

# 模块级 TTL 缓存（key -> (expire_ts, value)）。空结果不缓存（valid 判否重试）。
_CACHE: dict[str, tuple[float, Any]] = {}

# 熔断器名（与 eastmoney 隔离，circuit_breaker 全局注册表按 name 隔离）
_BREAKER_NAME = "worldmonitor"

# 惰性 session（带代理/重试）。direct/proxy 由 VR_HTTP_PROXY 决定（国外源通常需代理）。
_SESSION = None


def _session():
    global _SESSION
    if _SESSION is not None:
        return _SESSION
    try:
        import requests
    except ImportError:  # pragma: no cover
        return None
    s = requests.Session()
    s.headers.update({
        "Content-Type": "application/json",
        "Accept": "application/json",
        "MCP-Protocol-Version": _MCP_PROTOCOL_VERSION,
        "User-Agent": "Vibe-Research/1.0 (worldmonitor client)",
    })
    proxy = os.environ.get("VR_HTTP_PROXY")
    if proxy:
        s.proxies = {"http": proxy, "https": proxy}
    try:
        from requests.adapters import HTTPAdapter
        from urllib3.util.retry import Retry
        retry = Retry(total=2, backoff_factor=0.6,
                      status_forcelist=[429, 500, 502, 503, 504], allowed_methods=["POST"])
        adapter = HTTPAdapter(max_retries=retry)
        s.mount("https://", adapter)
        s.mount("http://", adapter)
    except Exception:  # pragma: no cover
        pass
    _SESSION = s
    return s


# ── pro key reader（VR_DATA_DIR 隔离，不日志）────────────────────────────

def get_worldmonitor_api_key() -> str | None:
    """读 pro key（``$VR_DATA_DIR/worldmonitor_api_key``）。public 调用不需 key，返 None 即可。
    key 绝不进 git/日志/异常。"""
    key_file = resolve_data_dir() / "worldmonitor_api_key"
    if not key_file.is_file():
        return None
    try:
        return key_file.read_text(encoding="utf-8").strip() or None
    except OSError:
        return None


# ── MCP JSON-RPC 客户端 ─────────────────────────────────────────────────

def _post_mcp(tool: str, arguments: dict | None = None,
              jmespath: str | None = None, proxy: str | None = None) -> dict | None:
    """POST JSON-RPC ``tools/call`` 到 worldmonitor MCP。返 result dict 或 None。

    ``jmespath`` 嵌入 arguments（服务端投影，降 token）。breaker 包裹：OPEN 时短路返 None；
    调用成功/失败记录。pro key（若在位）注入 arguments``api_key``（供 pro 工具鉴权）。
    失败/无网络返 None，不抛、不臆造。

    TODO（grill #2，待 live 冒烟）：MCP 2025-06-18 streamable HTTP 通常要求先 ``initialize``
    建会话（返 session-id header）再 ``tools/call``，且响应可能为 SSE 事件流
    （``event: message\\ndata: {...}``）。当前实现跳过 initialize、用 ``r.json()`` 解析——
    worldmonitor 端点真可达后需补 initialize 握手 + SSE 解析；未补前不可达即降级 None。
    """
    breaker = get_breaker(_BREAKER_NAME)
    if not breaker.allow_request():
        log.debug("worldmonitor breaker OPEN, short-circuit for %s", tool)
        return None
    s = _session()
    if s is None:
        breaker.record_failure()
        return None
    args = dict(arguments or {})
    if jmespath:
        args["jmespath"] = jmespath
    # pro key 注入（public 工具忽略；pro 工具服务端校验）
    pro_key = get_worldmonitor_api_key()
    if pro_key:
        args.setdefault("api_key", pro_key)
    payload = {
        "jsonrpc": "2.0", "id": 1, "method": "tools/call",
        "params": {"name": tool, "arguments": args},
    }
    try:
        r = s.post(WORLDMONITOR_MCP_URL, json=payload, timeout=20)
        if r.status_code != 200:
            breaker.record_failure()
            log.warning("worldmonitor %s HTTP %s", tool, r.status_code)
            return None
        data = r.json()
        # JSON-RPC error 响应（grill #8）：{"jsonrpc":"2.0","error":{...}} 不当成功
        if isinstance(data, dict) and data.get("error"):
            breaker.record_failure()
            log.warning("worldmonitor %s JSON-RPC error: %s", tool, str(data["error"])[:160])
            return None
        breaker.record_success()
        return data
    except Exception as e:  # noqa: BLE001 — 国外源不稳，吞异常降级 None
        breaker.record_failure()
        log.warning("worldmonitor %s failed: %s", tool, repr(e)[:160])
        return None


# ── MCP result 解包 ────────────────────────────────────────────────────

def _extract_content_text(resp: dict | None) -> str | None:
    """MCP tools/call 返回 → content[0].text。容错多种形状。"""
    if not isinstance(resp, dict):
        return None
    result = resp.get("result")
    if isinstance(result, dict):
        content = result.get("content")
        if isinstance(content, list) and content:
            first = content[0]
            if isinstance(first, dict):
                return first.get("text")
    # 某些实现直接返 {"text": ...} 或裸字符串
    if "text" in resp:
        return resp["text"]
    if isinstance(resp.get("result"), str):
        return resp["result"]
    return None


def _content_as_json(resp: dict | None) -> Any:
    """MCP 响应 → content JSON（先取 text 再 json.loads；失败返原 text 或 None）。"""
    text = _extract_content_text(resp)
    if text is None:
        return None
    if isinstance(text, (dict, list)):
        return text
    try:
        return json.loads(text)
    except (json.JSONDecodeError, TypeError):
        return text


# ── TTL 缓存包装（空不缓存）────────────────────────────────────────────

def _cached_wm(key: str, ttl: int, fn: Callable[[], T]) -> T:
    """TTL 缓存；fn 返 None/空 list/空 dict 时不缓存（下次仍调 fn）。"""
    now = time.time()
    cached = _CACHE.get(key)
    if cached and cached[0] > now:
        return cached[1]  # type: ignore[return-value]
    val = fn()
    # 空结果不缓存（对齐 market._cached 的 valid 判否重试）
    if val is None or (isinstance(val, (list, dict, str)) and len(val) == 0):
        return val
    _CACHE[key] = (now + ttl, val)
    return val


# ── 11 fetcher（薄封装 + 缓存）──────────────────────────────────────────
# 命名映射 worldmonitor 工具名 → 本模块 fetcher。jmespath 透传。

def fetch_market_data(jmespath: str | None = None) -> dict | None:
    """Finance Radar 市场数据（商品/外汇/指数/加密）。TTL 5min。"""
    return _cached_wm("market_data", _TTL_MARKET,
                      lambda: _post_mcp("get_market_data", jmespath=jmespath))


def fetch_country_risk(jmespath: str | None = None) -> dict | None:
    """CII 31 国不稳定指数。TTL 24h。"""
    return _cached_wm("country_risk", _TTL_SLOW,
                      lambda: _post_mcp("get_country_risk", jmespath=jmespath))


def fetch_news_intelligence(jmespath: str | None = None) -> dict | None:
    """GDELT 资讯情报。TTL 1h。"""
    return _cached_wm("news_intelligence", _TTL_NEWS,
                      lambda: _post_mcp("get_news_intelligence", jmespath=jmespath))


def fetch_news_clusters(jmespath: str | None = None) -> dict | None:
    """跨源资讯聚类。TTL 1h。"""
    return _cached_wm("news_clusters", _TTL_NEWS,
                      lambda: _post_mcp("get_news_clusters", jmespath=jmespath))


def fetch_economic_data_china(jmespath: str | None = None) -> dict | None:
    """中国宏观 12 序列（PBoC/GACC 不可取——诚实记缺口）。TTL 24h。"""
    return _cached_wm("economic_data_china", _TTL_SLOW,
                      lambda: _post_mcp("get_economic_data", {"country": "CN"}, jmespath=jmespath))


def fetch_country_macro(jmespath: str | None = None) -> dict | None:
    """IMF WEO 国家宏观。TTL 24h。"""
    return _cached_wm("country_macro", _TTL_SLOW,
                      lambda: _post_mcp("get_country_macro", jmespath=jmespath))


def fetch_tariff_trends(jmespath: str | None = None) -> dict | None:
    """关税趋势。TTL 24h。"""
    return _cached_wm("tariff_trends", _TTL_SLOW,
                      lambda: _post_mcp("get_tariff_trends", jmespath=jmespath))


def fetch_supply_chain(jmespath: str | None = None) -> dict | None:
    """干散货航运压力（供应链）。TTL 24h。"""
    return _cached_wm("supply_chain", _TTL_SLOW,
                      lambda: _post_mcp("get_supply_chain_data", jmespath=jmespath))


def fetch_energy_intelligence(jmespath: str | None = None) -> dict | None:
    """EIA 能源情报。TTL 24h。"""
    return _cached_wm("energy_intel", _TTL_SLOW,
                      lambda: _post_mcp("get_energy_intelligence", jmespath=jmespath))


def fetch_china_decision_signals(jmespath: str | None = None) -> dict | None:
    """中国决策信号。TTL 24h。"""
    return _cached_wm("china_decision_signals", _TTL_SLOW,
                      lambda: _post_mcp("get_china_decision_signals", jmespath=jmespath))


def fetch_hotspot_escalation(jmespath: str | None = None) -> dict | None:
    """热点升级。TTL 24h。"""
    return _cached_wm("hotspot_escalation", _TTL_SLOW,
                      lambda: _post_mcp("get_hotspot_escalation", jmespath=jmespath))


# ── 纯解析函数（无 I/O，可单测）──────────────────────────────────────────
# 输入：MCP 响应 dict（经 _content_as_json 解包后的 JSON）。缺字段→None，不臆造。

def parse_market_data(resp: dict | None) -> list[dict]:
    """商品/外汇快照 → [{symbol, price, change_pct, currency, source}]。

    worldmonitor Finance Radar 字段名随版本，容错取常见键。缺→None。
    """
    data = _content_as_json(resp)
    if data is None:
        return []
    items = data if isinstance(data, list) else data.get("data", []) if isinstance(data, dict) else []
    out: list[dict] = []
    for it in items if isinstance(items, list) else []:
        if not isinstance(it, dict):
            continue
        out.append({
            "symbol": it.get("symbol") or it.get("code") or it.get("name"),
            "price": _num(it.get("price") or it.get("last") or it.get("value")),
            "change_pct": _num(it.get("change_pct") or it.get("pct_change") or it.get("change_percent")),
            "currency": it.get("currency"),
            "source": "worldmonitor",
        })
    return out


def parse_country_risk(resp: dict | None) -> dict:
    """CII 31 国不稳定指数 → {countries: [{country, cii, trend}], source: worldmonitor_composite}。

    CII 是 worldmonitor 合成指标 → source 标 composite（作输入之一，不作唯一依据）。
    """
    data = _content_as_json(resp)
    if data is None:
        return {"countries": [], "source": "worldmonitor_composite"}
    if isinstance(data, dict) and "countries" in data:
        raw = data.get("countries") or []
    elif isinstance(data, list):
        raw = data
    else:
        raw = []
    countries: list[dict] = []
    for it in raw if isinstance(raw, list) else []:
        if not isinstance(it, dict):
            continue
        countries.append({
            "country": it.get("country") or it.get("name"),
            "cii": _num(it.get("cii") or it.get("score") or it.get("index")),
            "trend": it.get("trend"),
        })
    return {"countries": countries, "source": "worldmonitor_composite"}


def parse_news_clusters(resp: dict | None) -> list[dict]:
    """资讯聚类 → [{title, summary, category, ts, source:worldmonitor}]。零个股字段。"""
    data = _content_as_json(resp)
    if data is None:
        return []
    items = data if isinstance(data, list) else data.get("clusters", []) if isinstance(data, dict) else []
    out: list[dict] = []
    for it in items if isinstance(items, list) else []:
        if not isinstance(it, dict):
            continue
        out.append({
            "title": it.get("title") or it.get("headline") or it.get("topic"),
            "summary": it.get("summary") or it.get("description") or it.get("snippet"),
            "category": it.get("category") or it.get("theme"),
            "ts": it.get("ts") or it.get("timestamp") or it.get("date"),
            "source": "worldmonitor",
        })
    # 时间倒序（ts 可能为 None，None 排后）
    out.sort(key=lambda x: x.get("ts") or "", reverse=True)
    return out


def parse_news_intelligence(resp: dict | None) -> list[dict]:
    """GDELT 资讯 → [{title, summary, category, ts, source:worldmonitor}]。零个股字段。"""
    data = _content_as_json(resp)
    if data is None:
        return []
    items = data if isinstance(data, list) else data.get("articles", data.get("items", [])) if isinstance(data, dict) else []
    out: list[dict] = []
    for it in items if isinstance(items, list) else []:
        if not isinstance(it, dict):
            continue
        out.append({
            "title": it.get("title") or it.get("headline"),
            "summary": it.get("summary") or it.get("description") or it.get("snippet"),
            "category": it.get("category") or it.get("theme"),
            "ts": it.get("ts") or it.get("date") or it.get("timestamp"),
            "source": "worldmonitor",
        })
    out.sort(key=lambda x: x.get("ts") or "", reverse=True)
    return out


def parse_hotspot_escalation(resp: dict | None) -> list[dict]:
    """热点升级 → [{name, level, ts, source:worldmonitor_composite}]。"""
    data = _content_as_json(resp)
    if data is None:
        return []
    items = data if isinstance(data, list) else data.get("hotspots", data.get("items", [])) if isinstance(data, dict) else []
    out: list[dict] = []
    for it in items if isinstance(items, list) else []:
        if not isinstance(it, dict):
            continue
        out.append({
            "name": it.get("name") or it.get("title") or it.get("hotspot"),
            "level": it.get("level") or it.get("severity") or it.get("escalation"),
            "ts": it.get("ts") or it.get("timestamp") or it.get("date"),
            "source": "worldmonitor_composite",
        })
    out.sort(key=lambda x: x.get("ts") or "", reverse=True)
    return out


def parse_supply_chain(resp: dict | None) -> dict:
    """干散货航运压力 → {bdi, stress_indicators: {...}, source:worldmonitor_composite}。

    BDI（波罗的海干散货指数）为公开 feed；合成分标 composite。
    """
    data = _content_as_json(resp)
    if data is None:
        return {"bdi": None, "stress_indicators": {}, "source": "worldmonitor_composite"}
    d = data if isinstance(data, dict) else {}
    return {
        "bdi": _num(d.get("bdi") or d.get("baltic_dry_index")),
        "stress_indicators": d.get("stress_indicators") or d.get("indicators") or {},
        "source": "worldmonitor_composite",
    }


# ── 工具 ────────────────────────────────────────────────────────────────

def _num(v) -> float | None:
    if v is None:
        return None
    if isinstance(v, bool):
        return None
    if isinstance(v, (int, float)):
        return float(v)
    s = str(v).strip().replace(",", "").replace("%", "")
    if s in ("", "-", "--", "nan", "None"):
        return None
    try:
        return float(s)
    except ValueError:
        return None
