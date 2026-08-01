# -*- coding: utf-8 -*-
"""S020 P6：worldmonitor_query 工具注册 + 派发（离线，不触网）。

覆盖：
1. 注册进 chat.TOOLS / registry，schema 白名单 enum 为 11 个权威工具；
2. 未知 tool → 白名单拒绝，不调用 fetcher；
3. 透传 tool name + jmespath 到 fetcher，原样返回结果；
4. fetcher 返 None（离线/熔断）→ 降级 error dict，不抛；
5. fetcher 抛异常 → registry.execute 捕获，返 error dict。
"""
from __future__ import annotations

import chat
from ai.tools import worldmonitor_tools as wmt

_KNOWN = (
    "get_market_data",
    "get_country_risk",
    "get_news_intelligence",
    "get_news_clusters",
    "get_economic_data",
    "get_country_macro",
    "get_tariff_trends",
    "get_supply_chain_data",
    "get_energy_intelligence",
    "get_china_decision_signals",
    "get_hotspot_escalation",
)


def _tool_names() -> set[str]:
    return {t["function"]["name"] for t in chat.TOOLS}


def _schema(tool_name: str) -> dict:
    for t in chat.TOOLS:
        if t["function"]["name"] == tool_name:
            return t["function"]["parameters"]
    raise AssertionError(f"tool {tool_name} 未注册")


def test_tool_registered_in_chat() -> None:
    assert "worldmonitor_query" in _tool_names()


def test_schema_whitelist_enum() -> None:
    params = _schema("worldmonitor_query")
    assert params["required"] == ["tool"]
    enum = params["properties"]["tool"]["enum"]
    assert tuple(enum) == _KNOWN  # 保序白名单
    assert "jmespath" in params["properties"]


def test_unknown_tool_rejected() -> None:
    out = chat._exec_tool("worldmonitor_query", {"tool": "get_bogus"})
    assert out == {"error": "未知 worldmonitor 工具 get_bogus"}


def test_passthrough_tool_and_jmespath(monkeypatch) -> None:
    seen: dict = {}

    def fake(jmespath: str | None = None) -> dict:
        seen["jmespath"] = jmespath
        return {"market": [{"code": "AAPL", "chg": 1.5}]}

    monkeypatch.setitem(wmt._WM_FETCHERS, "get_market_data", fake)
    out = chat._exec_tool(
        "worldmonitor_query",
        {"tool": "get_market_data", "jmespath": "market[0:1]"},
    )
    assert seen["jmespath"] == "market[0:1]"
    assert out == {"market": [{"code": "AAPL", "chg": 1.5}]}


def test_jmespath_defaults_none(monkeypatch) -> None:
    seen: dict = {}

    def fake(jmespath: str | None = None) -> dict:
        seen["jmespath"] = jmespath
        return {"ok": True}

    monkeypatch.setitem(wmt._WM_FETCHERS, "get_country_risk", fake)
    out = chat._exec_tool("worldmonitor_query", {"tool": "get_country_risk"})
    assert out == {"ok": True}
    assert seen["jmespath"] is None


def test_offline_degrade_when_fetcher_none(monkeypatch) -> None:
    monkeypatch.setitem(wmt._WM_FETCHERS, "get_news_intelligence", lambda **_: None)
    out = chat._exec_tool("worldmonitor_query", {"tool": "get_news_intelligence"})
    assert out["error"]
    assert out["tool"] == "get_news_intelligence"
    assert "不注入猜测数据" in out["note"]


def test_fetcher_exception_captured(monkeypatch) -> None:
    def boom(jmespath: str | None = None) -> dict:
        raise RuntimeError("simulated")

    monkeypatch.setitem(wmt._WM_FETCHERS, "get_tariff_trends", boom)
    out = chat._exec_tool("worldmonitor_query", {"tool": "get_tariff_trends"})
    assert out["error"].startswith("worldmonitor_query 执行失败")
