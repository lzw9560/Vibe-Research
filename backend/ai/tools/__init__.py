"""S010 工具注册表包。

导入本包副作用：各 *_tools 模块的 @register_tool 装饰函数登记进
`registry._REGISTRY`。三出口（chat / mcp_server / cli_runtime）只 import
`ai.tools.registry`，不直接依赖具体 *_tools（除非要强制触发注册——本
`__init__` 已代劳）。
"""
from __future__ import annotations

from . import registry  # noqa: F401
from . import stock_tools  # noqa: F401 — 触发 @register_tool 注册
from . import worldmonitor_tools  # noqa: F401 — 触发 @register_tool 注册
from . import strategy_tools  # noqa: F401 — S058：query_strategy_card 注册
from . import kg_tools  # noqa: F401 — 知识图谱查询工具（query_kg_entities 等）

__all__ = [
    "registry",
    "stock_tools",
    "worldmonitor_tools",
    "strategy_tools",
    "kg_tools",
]
