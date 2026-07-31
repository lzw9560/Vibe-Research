"""Vibe-Research AI 子包：声明式工具注册表 + SYSTEM_PROMPT 边界（S010）。

三出口（chat / mcp_server / cli_runtime）共读 `ai.tools.registry`，消除
chat.py 手写 TOOLS 列表 + `_exec_tool` 硬分支。`import ai.tools` 即触发
stock_tools 注册 5 个数据工具 + 2 个预测工具。
"""
from __future__ import annotations
