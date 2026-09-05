"""S149 Phase 3 — 隐私边界闭包扫描（P3-T1a/b/c）。

AGENTS.md 硬约束：个人交易数据（journal/journal_risk/portfolio）不接入 AI prompt。
守「chat → ai/tools/* 闭包内无个人数据模块」+ 运行时工具遍历 + ast.walk 惰性导入覆盖。

denylist 用显式字符串（{journal, journal_risk, portfolio}），不靠 `journal` 子串匹配
（否则 `journal_risk` 命中不可靠——spec Phase 3 隐私约束 #4）。

本测试是**边界守卫**（green-when-clean / red-on-leak）：当前闭包不含个人数据模块（绿）；
journal.py / journal_risk.py 移植后若被误 import 进 ai/tools，立即红。反向（journal
不 import chat/ai.tools）在模块移植后激活（find_spec 前置）。零网络盖章红→绿见
test_daily_review_disk.py + journal 移植后的 _market_context 测试。
"""
from __future__ import annotations

import ast
import importlib.util
import pathlib

import pytest

# 个人数据模块 denylist（显式字符串，不靠子串）。P3-T4：+at_risk/excursion/attribution/
# inbox/risk_rules（journal_risk 家族——at_risk.report/risk_rules.violations 等都读个人交易）。
DENYLIST = {
    "journal", "journal_risk", "portfolio",
    "at_risk", "excursion", "attribution", "inbox", "risk_rules",
}

# 闭包种子：chat（context builder 根）+ ai/tools 全注册模块（registry 反射的 tool 来源）
SEEDS = [
    "chat",
    "ai.tools",
    "ai.tools.registry",
    "ai.tools.stock_tools",
    "ai.tools.strategy_tools",
    "ai.tools.worldmonitor_tools",
]


def _is_project_module(module_name: str) -> bool:
    """模块是否是项目内（backend/）模块——resolve 到非 site-packages 的 .py 源。"""
    try:
        spec = importlib.util.find_spec(module_name)
    except (ModuleNotFoundError, ValueError):
        return False
    if spec is None or spec.origin is None:
        return False
    origin = spec.origin
    return origin.endswith(".py") and "site-packages" not in origin and "/lib/python" not in origin


def _source_path(module_name: str) -> str | None:
    try:
        spec = importlib.util.find_spec(module_name)
    except (ModuleNotFoundError, ValueError):
        return None
    return spec.origin if spec and spec.origin and spec.origin.endswith(".py") else None


def _imported_modules(source_path: str) -> set[str]:
    """ast 解析源文件，收集所有 import 的模块/名字。

    ast.walk 覆盖函数内惰性 import（`def f(): from . import journal`）——
    不只扫模块顶层（一跳扫描抓不到惰性传递链，spec grill #4）。

    对 ImportFrom 同时收集 node.module（`from X.Y import z`→X.Y）和 alias.name
    （`from . import journal`→journal；相对 import 的 module 是 None，名字在 names），
    守隐私边界对相对惰性 import 也生效。
    """
    try:
        tree = ast.parse(pathlib.Path(source_path).read_text(encoding="utf-8"))
    except (OSError, SyntaxError):
        return set()
    out: set[str] = set()
    for node in ast.walk(tree):  # walk = 全树，含函数体
        if isinstance(node, ast.Import):
            for n in node.names:
                out.add(n.name)
        elif isinstance(node, ast.ImportFrom):
            if node.module:
                out.add(node.module)
            for n in node.names:  # 相对 import `from . import journal` 的名字
                out.add(n.name)
    return out


def _project_closure(seeds: list[str], max_depth: int = 12) -> tuple[set[str], set[str]]:
    """从 seeds 出发 BFS 项目内传递 import 图。返 (闭包模块集, 所有 import 的顶层名集)。"""
    seen: set[str] = set()
    all_imports: set[str] = set()
    queue = list(seeds)
    depth = 0
    while queue and depth < max_depth:
        depth += 1
        next_queue: list[str] = []
        for mod in queue:
            if mod in seen:
                continue
            seen.add(mod)
            if not _is_project_module(mod):
                continue
            path = _source_path(mod)
            if not path:
                continue
            for imp in _imported_modules(path):
                all_imports.add(imp)
                top = imp.split(".")[0]
                # 项目内模块递归（绝对 import）
                if _is_project_module(imp):
                    next_queue.append(imp)
                elif _is_project_module(top):
                    next_queue.append(top)
        queue = next_queue
    return seen, all_imports


def test_closure_excludes_personal_data_modules():
    """P3-T1a：chat→ai/tools/* 闭包内无 journal/journal_risk/portfolio（denylist 显式）。"""
    _, all_imports = _project_closure(SEEDS)
    # 检查每个 import 的顶层名是否命中 denylist（显式字符串匹配，非子串）
    leaked = {imp for imp in all_imports if imp.split(".")[0] in DENYLIST}
    assert not leaked, (
        f"隐私边界破裂：chat→ai/tools 闭包 import 了个人数据模块 {leaked}"
        "（journal/journal_risk/portfolio 不得接入 AI prompt）"
    )


def test_registry_has_no_personal_data_tool():
    """P3-T1b 运行时遍历：registry 注册的工具名不含个人数据模式（journal/trade/position/fill）。"""
    from ai.tools import registry
    tools = registry.get_openai_tools()
    names = []
    for t in tools:
        if isinstance(t, dict):
            fn = t.get("function", {})
            names.append(fn.get("name", "") if isinstance(fn, dict) else "")
        else:
            names.append(getattr(t, "name", ""))
    personal_patterns = ("journal", "trade", "position", "fill", "portfolio", "pnl")
    leaked = [n for n in names if any(p in n.lower() for p in personal_patterns)]
    assert not leaked, f"registry 注册了疑似个人数据工具：{leaked}（个人数据不接入 AI 工具面）"


def test_ast_walk_covers_lazy_imports():
    """P3-T1c：ast.walk 能扫到函数内惰性 import（机制健全性——非一跳顶层扫描）。

    `from . import journal` 的 module 是 None（相对 import），名字在 alias.name；
    _imported_modules 同时收集 alias.name，故相对惰性 import 也被扫到。
    """
    src = '''
def f():
    from . import journal  # 相对惰性 import（module=None，name=journal）
    return journal
'''
    tree = ast.parse(src)
    found = any(
        isinstance(n, ast.ImportFrom) and any(a.name == "journal" for a in n.names)
        for n in ast.walk(tree)
    )
    assert found, "ast.walk 未扫到函数内惰性 import（隐私扫描机制失效）"


@pytest.mark.parametrize("mod_name", [
    "journal", "journal_risk", "at_risk", "excursion", "attribution", "inbox", "risk_rules",
])
def test_personal_modules_do_not_import_chat_or_tools(mod_name):
    """P3-T1a/T4e 反向：个人数据模块的 import 图不含 chat/ai.tools（移植后激活）。

    模块移植前 find_spec=None → skip（守卫待激活）；移植后若 import chat/ai.tools → 红。
    """
    if importlib.util.find_spec(mod_name) is None:
        pytest.skip(f"{mod_name} 尚未移植（P3-T3/T4 后激活反向守卫）")
    path = _source_path(mod_name)
    assert path is not None
    imports = _imported_modules(path)
    leaked = {imp for imp in imports if imp.split(".")[0] in {"chat", "ai"}}
    assert not leaked, (
        f"{mod_name} import 了 {leaked}（个人数据模块不得 import chat/ai.tools，"
        "防 AI context 反向触达）"
    )
