"""声明式工具注册表（S010 T1-T6）。

设计：
- `@register_tool(name, description, params=...)` 装饰一个普通函数，反射其签名
  生成 OpenAI function-calling 参数 schema（type/required 自动，描述与 enum 走 params 覆盖）。
- `get_openai_tools()` 导出 chat.py 的 `TOOLS`（OpenAI 格式）。
- `get_mcp_tools()` 导出 MCP inputSchema 格式（mcp_server 用）。
- `execute(name, args)` 派发：未知工具返 error dict；执行异常返 error dict（不抛，
  喂回 LLM 不中断 function-calling 循环）。

纯净性：registry 不 import astock，异常按通用 Exception 捕获（DependencyMissing
是 astock 的子类，消息格式从旧 `str(e)` 统一为 `f"{name} 执行失败：{e}"`——
无测试断言旧格式，且对用户更清晰）。
"""
from __future__ import annotations

import inspect
import types
from dataclasses import dataclass, field
from typing import Any, Callable, Union, get_args, get_origin, get_type_hints

_EMPTY = inspect.Parameter.empty


@dataclass
class ToolDef:
    """单个工具的声明式描述。"""
    name: str
    description: str
    func: Callable[..., Any]
    schema: dict  # JSON schema（OpenAI parameters / MCP inputSchema 共用）
    param_meta: dict = field(default_factory=dict)


# 注册表：插入顺序即导出顺序（dict 保序），与旧 chat.TOOLS 顺序一致。
_REGISTRY: "dict[str, ToolDef]" = {}


# ── 类型 → JSON schema 映射 ──────────────────────────────────────────

def _type_to_schema(ann: Any) -> dict:
    """把 Python 类型标注映射成 JSON schema 片段（不含 description）。

    str→string / int→integer / float→number / bool→boolean；
    list[T]→array(items=_type_to_schema(T))；
    dict→object；Optional[T]（T | None）→ 退化为 _type_to_schema(T)；
    未知 / Any → {} （不带 type 约束）。
    """
    if ann is _EMPTY or ann is Any:
        return {}

    origin = get_origin(ann)

    # Optional / Union：去掉 NoneType，取首个非 None 成员
    # （PEP 604 `str | None` → types.UnionType；typing.Optional/Union → typing.Union）
    if origin is Union or origin is types.UnionType:
        non_none = [a for a in get_args(ann) if a is not type(None)]
        if len(non_none) == 1:
            return _type_to_schema(non_none[0])
        return {}

    if origin in (list, set, frozenset):
        args = get_args(ann)
        sch: dict = {"type": "array"}
        if args:
            sch["items"] = _type_to_schema(args[0])
        return sch

    if origin in (dict,):
        return {"type": "object"}

    # 单一类型
    if ann is str:
        return {"type": "string"}
    if ann is int:
        return {"type": "integer"}
    if ann is float:
        return {"type": "number"}
    if ann is bool:
        return {"type": "boolean"}
    if ann in (dict,):
        return {"type": "object"}
    return {}


def _build_schema_from_signature(func: Callable[..., Any]) -> dict:
    """反射函数签名 → JSON schema（properties / required）。

    description / enum 等 schema 字段由 `register_tool(params=...)` 覆盖补全，
    反射只负责类型与 required（有默认值 → 非必需）。
    """
    # 用 get_type_hints 解析字符串标注（from __future__ import annotations 下
    # signature().annotation 是字符串，需按模块全局 + builtins 求值）。
    try:
        hints = get_type_hints(func)
    except Exception:  # pragma: no cover — 解析失败兜底
        hints = {}

    props: dict[str, dict] = {}
    required: list[str] = []
    sig = inspect.signature(func)
    for pname, param in sig.parameters.items():
        if param.kind in (inspect.Parameter.VAR_POSITIONAL, inspect.Parameter.VAR_KEYWORD):
            continue
        ann = hints.get(pname, _EMPTY)
        props[pname] = _type_to_schema(ann)
        if param.default is _EMPTY:
            required.append(pname)

    schema: dict = {"type": "object", "properties": props}
    if required:
        schema["required"] = required
    return schema


# ── 注册 / 导出 / 派发 ───────────────────────────────────────────────

def register_tool(
    name: str,
    description: str,
    *,
    params: "dict[str, dict] | None" = None,
) -> Callable[[Callable[..., Any]], Callable[..., Any]]:
    """装饰器：把函数登记进 `_REGISTRY`，反射签名生成 schema。

    params: 可选，每参数的额外 schema 字段（description/enum/...），覆盖反射出的
    类型片断。例如 `params={"stage": {"enum": ["s1","s2","s3"], "description": "..."}}`。
    """

    def deco(func: Callable[..., Any]) -> Callable[..., Any]:
        schema = _build_schema_from_signature(func)
        meta = params or {}
        for pname, extra in meta.items():
            if pname in schema["properties"]:
                # 合并：反射出的类型在前，params 覆盖/补全在后
                merged = {**schema["properties"][pname], **extra}
                schema["properties"][pname] = merged
            else:
                schema["properties"][pname] = dict(extra)
        _REGISTRY[name] = ToolDef(
            name=name, description=description, func=func,
            schema=schema, param_meta=meta,
        )
        return func

    return deco


def get_openai_tools() -> list[dict]:
    """导出 OpenAI function-calling 格式（chat.TOOLS 替代品）。"""
    return [
        {
            "type": "function",
            "function": {
                "name": td.name,
                "description": td.description,
                "parameters": td.schema,
            },
        }
        for td in _REGISTRY.values()
    ]


def get_mcp_tools() -> list[dict]:
    """导出 MCP inputSchema 格式（mcp_server 用）。"""
    return [
        {
            "name": td.name,
            "description": td.description,
            "inputSchema": td.schema,
        }
        for td in _REGISTRY.values()
    ]


def get_tool(name: str) -> ToolDef | None:
    return _REGISTRY.get(name)


def execute(name: str, args: "dict | None") -> Any:
    """派发执行工具，返回可序列化结果；失败返 `{"error": ...}` 不抛。

    未知工具 → `{"error": "未知工具 {name}"}`；
    执行异常 → `{"error": "{name} 执行失败：{e}"}`（喂回 LLM，不中断循环）。
    """
    td = _REGISTRY.get(name)
    if td is None:
        return {"error": f"未知工具 {name}"}
    try:
        return td.func(**(args or {}))
    except Exception as e:  # noqa: BLE001 — 工具错误回喂给模型，不中断循环
        return {"error": f"{name} 执行失败：{e}"}


def tool_names() -> list[str]:
    """已注册工具名（按注册顺序）。cli_runtime 共享工具清单用。"""
    return list(_REGISTRY.keys())
