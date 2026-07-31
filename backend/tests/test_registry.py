# -*- coding: utf-8 -*-
"""S010 T12：声明式工具注册表单测。

覆盖：
- 反射签名 → JSON schema 的类型映射（str/int/float/bool/list[str]/Optional/enum）
- required vs optional（有默认值 → 非必需）
- 三出口导出一致性（get_openai_tools / get_mcp_tools / execute 同名同 schema）
- chat.TOOLS == registry.get_openai_tools()（chat.py 已改读 registry，T7）
- 派发：未知工具返 error dict；执行异常返 error dict（不抛）
- 合规（§1 弱合规）：SYSTEM_PROMPT 允许方向性研判 + 守工程底线（可复现/不承诺确定性）
"""
from __future__ import annotations

import inspect
import json

import astock
import chat
import gstock

from ai.tools import registry


# ── 反射 / schema ────────────────────────────────────────────────────

def _openai(name: str) -> dict:
    td = registry.get_tool(name)
    assert td is not None, f"{name} 未注册"
    return td.schema


def test_reflection_str_required():
    sch = _openai("query_valuation")
    assert sch["properties"]["code"] == {"type": "string", "description": "6 位股票代码"}
    assert sch["required"] == ["code"]


def test_reflection_array_of_string():
    sch = _openai("query_quote")
    assert sch["properties"]["codes"] == {
        "type": "array",
        "items": {"type": "string"},
        "description": "6 位股票代码列表，如 ['600519','000858']",
    }
    assert sch["required"] == ["codes"]


def test_reflection_optional_param_not_required():
    sch = _openai("prediction_short_sector")
    # stage 必需 + enum 覆盖；date 有默认 → 非必需
    assert sch["required"] == ["stage"]
    assert sch["properties"]["stage"]["enum"] == ["s1", "s2", "s3"]
    assert "date" in sch["properties"]
    assert "date" not in sch.get("required", [])


def test_reflection_no_params_empty_properties():
    sch = _openai("prediction_intraday_framework")
    assert sch["properties"] == {}
    assert "required" not in sch  # 无必需参数


def test_reflection_global_stock_symbol():
    sch = _openai("query_global_stock")
    assert sch["properties"]["symbol"]["type"] == "string"
    assert sch["required"] == ["symbol"]


# ── 三出口一致性 ─────────────────────────────────────────────────────

def test_three_exports_same_names_and_schema():
    openai_tools = registry.get_openai_tools()
    mcp_tools = registry.get_mcp_tools()
    names = registry.tool_names()

    openai_names = [t["function"]["name"] for t in openai_tools]
    mcp_names = [t["name"] for t in mcp_tools]

    assert openai_names == mcp_names == names
    # OpenAI 与 MCP 共用同一 schema 对象（inputSchema == parameters）
    for o, m in zip(openai_tools, mcp_tools):
        assert o["function"]["parameters"] == m["inputSchema"]
        assert o["function"]["description"] == m["description"]


def test_chat_tools_equals_registry():
    """T7：chat.TOOLS 是 registry.get_openai_tools() 的同值产出。"""
    assert chat.TOOLS == registry.get_openai_tools()


def test_chat_exec_tool_delegates_to_registry(monkeypatch):
    """chat._exec_tool 是 registry.execute 薄壳——monkeypatch registry 可拦截。"""
    called: list[tuple[str, dict]] = []
    monkeypatch.setattr(
        registry, "execute",
        lambda name, args: (called.append((name, args)), {"ok": 1})[1],
    )
    out = chat._exec_tool("query_quote", {"codes": ["600519"]})
    assert out == {"ok": 1}
    assert called == [("query_quote", {"codes": ["600519"]})]


# ── 派发：未知工具 / 异常 ────────────────────────────────────────────

def test_execute_unknown_tool_returns_error_dict():
    out = registry.execute("does_not_exist", {})
    assert out == {"error": "未知工具 does_not_exist"}


def test_execute_swallows_exception_returns_error_dict(monkeypatch):
    """工具抛异常时 execute 捕获并返 error dict，不向调用方抛。"""
    monkeypatch.setattr(astock, "tencent_quote", lambda codes: (_ for _ in ()).throw(RuntimeError("boom")))
    out = registry.execute("query_quote", {"codes": ["600519"]})
    assert "error" in out
    assert "query_quote 执行失败" in out["error"]
    assert "boom" in out["error"]


def test_execute_dispatches_query_quote(monkeypatch):
    raw = {"600519": {"name": "茅台", "price": 1700.0, "last_close": 1680.0,
                       "turnover_pct": 0.5, "limit_up": 1870.0, "limit_down": 1530.0,
                       "mcap_yi": 21000.0}}
    monkeypatch.setattr(astock, "tencent_quote", lambda codes: raw)
    out = registry.execute("query_quote", {"codes": ["600519"]})
    q = out["600519"]
    assert q["turnover_rate"] == 0.5
    assert q["market_cap"] == 21000.0 * 1e8


def test_execute_dispatches_global_stock_not_found(monkeypatch):
    monkeypatch.setattr(gstock, "us_hk_stock", lambda symbol: {})
    out = registry.execute("query_global_stock", {"symbol": "ZZZ"})
    assert out.get("error")


def test_execute_short_sector_bad_stage():
    out = registry.execute("prediction_short_sector", {"stage": "s9"})
    assert out == {"error": "stage must be one of s1|s2|s3"}


# ── 合规（§1 弱合规，T15 chat 侧） ────────────────────────────────────

def test_system_prompt_allows_directional_research():
    """§1.1：允许方向性研判/买卖时机/收益预期/操作建议（半自动化，用户决策）。"""
    text = chat.SYSTEM_PROMPT
    for kw in ("方向性研判", "买卖时机", "收益预期", "操作建议"):
        assert kw in text, f"SYSTEM_PROMPT 应允许 {kw}（§1.1 弱合规）"


def test_system_prompt_retains_engineering_floor():
    """§1.2 工程底线：判断可复现（不臆造/可复算）+ 不承诺确定性保证。"""
    text = chat.SYSTEM_PROMPT
    assert "可复算" in text or "可复现" in text
    assert "不" in text and "确定性" in text  # 不得承诺确定性


def test_system_prompt_no_tools_single_assignment():
    """R7 回归：SYSTEM_PROMPT_NO_TOOLS 仅一处顶层赋值。"""
    src = inspect.getsource(chat)
    assert src.count("SYSTEM_PROMPT_NO_TOOLS = ") == 1
    assert hasattr(chat, "SYSTEM_PROMPT_NO_TOOLS")
    assert "投研助理" in chat.SYSTEM_PROMPT_NO_TOOLS


def test_registry_only_objective_and_research_tools():
    """§1.2：注册表只挂客观取数 + 研究性判断工具，无越权工具。"""
    names = set(registry.tool_names())
    assert names == {
        "query_quote", "query_valuation", "query_reports", "query_news",
        "query_global_stock", "prediction_short_sector", "prediction_intraday_framework",
    }
