"""S010 工具注册表包。

导入本包副作用：`stock_tools` 装饰 7 个工具进 `registry._REGISTRY`。
三出口（chat / mcp_server / cli_runtime）只 import `ai.tools.registry`，
不直接依赖 `stock_tools`（除非要强制触发注册——本 `__init__` 已代劳）。
"""
from __future__ import annotations

from . import registry  # noqa: F401
from . import stock_tools  # noqa: F401 — 触发 @register_tool 注册

__all__ = ["registry", "stock_tools"]
