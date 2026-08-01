"""S020 P6：worldmonitor 决策因子工具（透传 tool name + jmespath）。

`@register_tool("worldmonitor_query", ...)` 装饰的函数 = 工具签名（供反射生成 schema）
 + 执行逻辑：whitelist 校验 `tool` → 调 `worldmonitor.fetch_*`（内部已带 TTL 缓存 +
 熔断 + jmespath 服务端投影）→ 原样返回 MCP result。注册进 registry 后，chat / mcp_server /
 cli_runtime 三出口自动可见（`chat.TOOLS = registry.get_openai_tools()`），无需改 chat.py。

合规（§1.2 弱合规）：工具只返回宏观/地缘/资讯等客观研究数据；无 key 或现网不可达时
 fetcher 返 None，本工具安全降级为说明性 dict（不抛、不注入假数据）。pro key 由
 `worldmonitor.get_worldmonitor_api_key()` 读 `$VR_DATA_DIR`，绝不进 git/日志。
"""
from __future__ import annotations

from data.sources import worldmonitor as wm

from .registry import register_tool

# ── tool name → fetcher 映射（权威清单，与 worldmonitor.py 11 fetcher 一一对应）──
# key = worldmonitor MCP 工具名（LLM 可见）；value = 本仓库 fetcher。
# get_economic_data 固定参数 {"country": "CN"} 已烘焙进 fetch_economic_data_china。
_WM_FETCHERS: dict[str, callable] = {
    "get_market_data": wm.fetch_market_data,
    "get_country_risk": wm.fetch_country_risk,
    "get_news_intelligence": wm.fetch_news_intelligence,
    "get_news_clusters": wm.fetch_news_clusters,
    "get_economic_data": wm.fetch_economic_data_china,
    "get_country_macro": wm.fetch_country_macro,
    "get_tariff_trends": wm.fetch_tariff_trends,
    "get_supply_chain_data": wm.fetch_supply_chain,
    "get_energy_intelligence": wm.fetch_energy_intelligence,
    "get_china_decision_signals": wm.fetch_china_decision_signals,
    "get_hotspot_escalation": wm.fetch_hotspot_escalation,
}


@register_tool(
    "worldmonitor_query",
    "查 worldmonitor 决策因子（11 类宏观/地缘/资讯/供应链研究数据）。"
    "可选 jmespath 服务端投影以缩减 token。客观研究数据，非投资建议。",
    params={
        "tool": {
            "enum": list(_WM_FETCHERS),
            "description": "worldmonitor 工具名（见 enum）",
        },
        "jmespath": {
            "description": "可选 JMESPath 表达式，服务端投影缩减 token，如 'data[0:5]'",
        },
    },
)
def worldmonitor_query(tool: str, jmespath: str | None = None) -> dict:
    fetcher = _WM_FETCHERS.get(tool)
    if fetcher is None:
        return {"error": f"未知 worldmonitor 工具 {tool}"}
    raw = fetcher(jmespath=jmespath)
    if raw is None:
        return {
            "error": f"worldmonitor {tool} 暂不可达（离线或熔断）",
            "tool": tool,
            "note": "联网后可重试；本工具不注入猜测数据",
        }
    return raw
