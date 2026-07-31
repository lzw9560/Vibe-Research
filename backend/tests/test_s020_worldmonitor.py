# -*- coding: utf-8 -*-
"""S020 worldmonitor 源单测：纯解析 + MCP 解包 + 缓存 TTL + breaker + fetcher 调参。

离线、无网络——monkeypatch ``_post_mcp`` / breaker，mock JSON 样本验证纯解析。
live 冒烟在 ``-m live`` 单独标（T12）。
"""
import json

from data.sources import worldmonitor as wm


# ── MCP 响应解包 ───────────────────────────────────────────────────────

def _mcp(text_payload: str) -> dict:
    """造一个 MCP tools/call 响应，content[0].text = text_payload。"""
    return {"result": {"content": [{"type": "text", "text": text_payload}]}}


def test_extract_content_text_standard_mcp():
    resp = _mcp('{"hello": 1}')
    assert wm._extract_content_text(resp) == '{"hello": 1}'


def test_content_as_json_parses_text():
    resp = _mcp('[{"symbol": "CL", "price": "80.5"}]')
    out = wm._content_as_json(resp)
    assert out == [{"symbol": "CL", "price": "80.5"}]


def test_content_as_json_non_json_returns_text():
    resp = _mcp("plain text not json")
    assert wm._content_as_json(resp) == "plain text not json"


def test_extract_content_text_none_safe():
    assert wm._extract_content_text(None) is None
    assert wm._extract_content_text({}) is None


# ── 纯解析 ─────────────────────────────────────────────────────────────

def test_parse_market_data():
    resp = _mcp(json.dumps([
        {"symbol": "CL", "price": "80.5", "change_pct": "1.2", "currency": "USD"},
        {"code": "XAU", "last": "2400", "pct_change": "-0.3"},
    ]))
    out = wm.parse_market_data(resp)
    assert len(out) == 2
    assert out[0]["symbol"] == "CL" and out[0]["price"] == 80.5
    assert out[1]["symbol"] == "XAU" and out[1]["price"] == 2400.0
    assert all(o["source"] == "worldmonitor" for o in out)


def test_parse_market_data_empty():
    assert wm.parse_market_data(None) == []
    assert wm.parse_market_data(_mcp("[]")) == []


def test_parse_country_risk_marks_composite():
    resp = _mcp(json.dumps({"countries": [
        {"country": "US", "cii": "85.2", "trend": "up"},
        {"name": "CN", "score": "72"},
    ]}))
    out = wm.parse_country_risk(resp)
    assert out["source"] == "worldmonitor_composite"
    assert len(out["countries"]) == 2
    assert out["countries"][0]["cii"] == 85.2
    assert out["countries"][1]["country"] == "CN"


def test_parse_news_clusters_desc_and_no_stock_fields():
    resp = _mcp(json.dumps([
        {"title": "B", "summary": "s2", "ts": "2026-07-29"},
        {"title": "A", "summary": "s1", "ts": "2026-07-30"},
    ]))
    out = wm.parse_news_clusters(resp)
    assert out[0]["title"] == "A"  # 时间倒序
    assert all("symbol" not in o and "code" not in o for o in out)  # 零个股字段
    assert all(o["source"] == "worldmonitor" for o in out)


def test_parse_news_intelligence():
    resp = _mcp(json.dumps({"articles": [{"headline": "Fed cuts", "date": "2026-07-30"}]}))
    out = wm.parse_news_intelligence(resp)
    assert len(out) == 1 and out[0]["title"] == "Fed cuts"


def test_parse_hotspot_escalation_composite():
    resp = _mcp(json.dumps({"hotspots": [{"name": "Mideast", "level": "high", "ts": "2026-07-30"}]}))
    out = wm.parse_hotspot_escalation(resp)
    assert out[0]["name"] == "Mideast" and out[0]["source"] == "worldmonitor_composite"


def test_parse_supply_chain():
    resp = _mcp(json.dumps({"bdi": "1500", "stress_indicators": {"port_congestion": "high"}}))
    out = wm.parse_supply_chain(resp)
    assert out["bdi"] == 1500.0 and out["source"] == "worldmonitor_composite"


def test_num_helpers():
    assert wm._num("1,234.5") == 1234.5
    assert wm._num("-") is None
    assert wm._num(None) is None
    assert wm._num(True) is None


# ── 缓存 TTL（空不缓存）────────────────────────────────────────────────

def test_cached_wm_caches_nonempty():
    wm._CACHE.clear()
    calls = [0]
    def fn():
        calls[0] += 1
        return {"x": 1}
    assert wm._cached_wm("k", 60, fn) == {"x": 1}
    assert wm._cached_wm("k", 60, fn) == {"x": 1}
    assert calls[0] == 1  # 第二次命中缓存


def test_cached_wm_empty_not_cached():
    wm._CACHE.clear()
    calls = [0]
    def fn():
        calls[0] += 1
        return []
    assert wm._cached_wm("k", 60, fn) == []
    assert wm._cached_wm("k", 60, fn) == []
    assert calls[0] == 2  # 空结果不缓存，每次都调


# ── fetcher 调参（monkeypatch _post_mcp）──────────────────────────────

def test_fetcher_calls_correct_tool(monkeypatch):
    seen = {}
    def fake_post(tool, arguments=None, jmespath=None, proxy=None):
        seen["tool"] = tool
        seen["jmespath"] = jmespath
        seen["args"] = arguments
        return None  # 空结果，不缓存
    monkeypatch.setattr(wm, "_post_mcp", fake_post)
    wm._CACHE.clear()
    wm.fetch_market_data(jmespath="data[*].symbol")
    assert seen["tool"] == "get_market_data"
    assert seen["jmespath"] == "data[*].symbol"
    wm.fetch_country_risk()
    assert seen["tool"] == "get_country_risk"
    wm.fetch_economic_data_china()
    assert seen["tool"] == "get_economic_data" and seen["args"] == {"country": "CN"}


def test_all_eleven_fetchers_wired(monkeypatch):
    """11 fetcher 各调对 tool name。"""
    tools = []
    def fake_post(tool, arguments=None, jmespath=None, proxy=None):
        tools.append(tool)
        return None
    monkeypatch.setattr(wm, "_post_mcp", fake_post)
    wm._CACHE.clear()
    wm.fetch_market_data()
    wm.fetch_country_risk()
    wm.fetch_news_intelligence()
    wm.fetch_news_clusters()
    wm.fetch_economic_data_china()
    wm.fetch_country_macro()
    wm.fetch_tariff_trends()
    wm.fetch_supply_chain()
    wm.fetch_energy_intelligence()
    wm.fetch_china_decision_signals()
    wm.fetch_hotspot_escalation()
    assert len(tools) == 11
    assert "get_market_data" in tools and "get_hotspot_escalation" in tools


# ── breaker OPEN 短路 ─────────────────────────────────────────────────

def test_breaker_open_short_circuits(monkeypatch):
    """breaker OPEN 时 _post_mcp 短路返 None，不调 session。"""
    from circuit_breaker import CircuitBreaker, CircuitState
    breaker = CircuitBreaker("worldmonitor")
    breaker.state = CircuitState.OPEN
    breaker.last_failure_time = float("inf")  # 永不超时恢复
    monkeypatch.setattr(wm, "get_breaker", lambda name: breaker)
    # 即便 session 可用，OPEN 时不应走到 post
    assert wm._post_mcp("get_market_data") is None


def test_post_mcp_no_session_returns_none(monkeypatch):
    """session 不可用（requests 缺失）→ record_failure + None。"""
    from circuit_breaker import CircuitBreaker
    breaker = CircuitBreaker("worldmonitor")
    monkeypatch.setattr(wm, "get_breaker", lambda name: breaker)
    monkeypatch.setattr(wm, "_SESSION", None, raising=False)
    monkeypatch.setattr(wm, "_session", lambda: None)
    assert wm._post_mcp("get_market_data") is None


# ── pro key 隔离 ──────────────────────────────────────────────────────

def test_get_worldmonitor_api_key_missing(monkeypatch, tmp_path):
    """key 缺失返 None。"""
    monkeypatch.setenv("VR_DATA_DIR", str(tmp_path))
    assert wm.get_worldmonitor_api_key() is None


def test_get_worldmonitor_api_key_present(monkeypatch, tmp_path):
    (tmp_path / "worldmonitor_api_key").write_text("secret-key\n")
    monkeypatch.setenv("VR_DATA_DIR", str(tmp_path))
    assert wm.get_worldmonitor_api_key() == "secret-key"
