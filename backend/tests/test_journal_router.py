# -*- coding: utf-8 -*-
"""S166 路由接线测试：app.py 真实注册 journal_router（源码级 wiring 校验）。

grill finding（MEDIUM confirmed）：test_journal_router.py 缺失——test_journal_risk.py 用
minimal-app TestRouter 不验 app.py 真实接线（删 app.include_router(journal_router) 会让
真实 :8900 的 /api/journal/* 404，但 minimal-app 测试仍绿，静默漏网）。

本测试 ast 解析 app.py 源码，确认 `from routers import journal as journal_router` +
`app.include_router(journal_router.router)` 都在——删任一行本测试红。

源码级（非 runtime）：避免 `import app` 的 ~2min 冷启动（app.py import 全量 routers
+ astock + scheduled_tasks 重）。端点 runtime 实跑由 minimal-app TestRouter 在
test_journal_risk.py 覆盖（16 端点绿）；本测试补 app.py 接线源码校验，两层闭合。
"""
import ast
from pathlib import Path

_APP_PATH = Path(__file__).resolve().parent.parent / "app.py"


def _app_ast() -> ast.Module:
    return ast.parse(_APP_PATH.read_text(encoding="utf-8"))


def _has_import_from(from_module: str, name: str, as_name: str | None = None) -> bool:
    """app.py 是否有 `from <from_module> import <name> [as <as_name>]`。"""
    for node in ast.walk(_app_ast()):
        if (isinstance(node, ast.ImportFrom)
                and node.module and node.module == from_module):
            for n in node.names:
                if n.name == name and (as_name is None or n.asname == as_name):
                    return True
    return False


def _has_include_router(router_var: str) -> bool:
    """app.py 是否有顶层 `app.include_router(<router_var>.router)`。"""
    for node in ast.iter_child_nodes(_app_ast()):  # 只看顶层（非函数内）
        if isinstance(node, ast.Expr) and isinstance(node.value, ast.Call):
            call = node.value
            func = call.func
            if (isinstance(func, ast.Attribute) and func.attr == "include_router"
                    and isinstance(func.value, ast.Name) and func.value.id == "app"):
                for arg in call.args:
                    if (isinstance(arg, ast.Attribute) and arg.attr == "router"
                            and isinstance(arg.value, ast.Name)
                            and arg.value.id == router_var):
                        return True
    return False


def test_app_imports_journal_router():
    """app.py 有 `from routers import journal as journal_router`。"""
    assert _has_import_from("routers", "journal", as_name="journal_router"), (
        "app.py 缺 `from routers import journal as journal_router`——journal_router 未 import，"
        "/api/journal/* + /api/risk/* 16 端点无法上线"
    )


def test_app_includes_journal_router():
    """app.py 顶层有 `app.include_router(journal_router.router)`——16 端点真实接线。"""
    assert _has_include_router("journal_router"), (
        "app.py 缺顶层 `app.include_router(journal_router.router)`——"
        "journal_router import 了但没 include，真实 :8900 的 /api/journal/* 会 404"
    )
