# -*- coding: utf-8 -*-
"""项目内验算工具集（从 ~/tools 集成）。

本包同时承载两个职责：
1. **验算工具**：``financial_rigor.py``（CLI 风格财务验算，data/validators 复用口径）
2. **AI 工具层兼容层**（S010 重构后实际在 ``ai.tools.registry``，此处 re-export
   供 main 分支遗留的 ``debate.py`` / ``agents.py`` / ``mcp_server.py`` 等
   ``import tools; tools.TOOLS / tools.exec_tool`` 调用兼容，不回退 S010）。

develop 的工具单一事实源是 ``ai.tools.registry``（声明式注册，S010），
本 ``__init__`` 只是薄壳 re-export，不重复定义工具。
"""
from __future__ import annotations

# S010：AI 工具层——registry 是单一事实源（chat / mcp_server / cli_runtime 共读）。
# re-export 让 `import tools; tools.TOOLS` / `tools.exec_tool` 兼容旧调用方。
from ai.tools import registry  # noqa: F401

TOOLS = registry.get_openai_tools()
# main 兼容：派发结构（test_agents 校验「每工具有 handler」+ 异常包装 + monkeypatch）
# 从 registry._REGISTRY 派生 name→handler 字典
TOOL_NAMES = list(registry._REGISTRY.keys())
_HANDLERS = {name: td.func for name, td in registry._REGISTRY.items()}


def exec_tool(name: str, args: dict | None = None) -> Any:
    """派发工具，失败返 ``{"error": ...}`` 不抛（喂回 LLM 不中断循环）。

    经 ``_HANDLERS`` 派发（main 兼容：测试可 monkeypatch _HANDLERS 替换 handler）。
    异常格式与 ``registry.execute`` 一致（``f"{name} 执行失败：{e}"``）。
    """
    h = _HANDLERS.get(name)
    if h is None:
        return {"error": f"未知工具：{name}"}
    try:
        return h(args or {})
    except Exception as e:  # noqa: BLE001 — 异常转 error dict 喂回 LLM
        return {"error": f"{name} 执行失败：{e}"}


# —— schema 简写 helper（main tools.py 遗留，test_agents 校验裁剪逻辑时引用）——
def _t(name: str, desc: str, props: dict | None = None, required: list[str] | None = None) -> dict:
    return {
        "type": "function",
        "function": {
            "name": name,
            "description": desc,
            "parameters": {"type": "object", "properties": props or {}, "required": required or []},
        },
    }


def _pick(rows: list[dict], keys: tuple[str, ...] | None, limit: int) -> list[dict]:
    """取前 limit 条（控 token）；keys 为 None 时保留全部字段，只截条数。"""
    head = (rows or [])[:limit]
    if keys is None:
        return [r for r in head if isinstance(r, dict)]
    return [{k: r.get(k) for k in keys} for r in head if isinstance(r, dict)]


__all__ = ["registry", "TOOLS", "exec_tool", "_t", "_pick"]
