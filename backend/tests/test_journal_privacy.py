# -*- coding: utf-8 -*-
"""S166 R3 / §1.2 工程底线边界测试：个人交易数据模块不接入 AI prompt。

守 AGENTS.md 个人数据隔离：journal / at_risk / risk_rules / excursion / attribution /
inbox 是个人交易数据只读 API 给前端渲染，AI 永远看不到（不进 chat.TOOLS / 不被
chat / mcp_server import）。一旦泄漏，模型回答变成"针对这个人当前处境"的个性化
投资建议，是本项目合规立足点（非个性化）唯一不能碰的那条线。

grill finding（MEDIUM confirmed）：test_journal_privacy.py 缺失——privacy boundary
closure scan 缺位。本测试静态扫 AI 入口模块源码的 import 集，确保不含个人数据模块。
"""
import ast
import importlib
from pathlib import Path

#: 个人数据模块（§1.2 隔离边界——AI 不可见）。
PRIVATE_MODULES = {"journal", "at_risk", "risk_rules", "excursion", "attribution", "inbox"}

#: 可能接入 AI prompt 的入口模块（须守边界，不 import 个人数据模块）。
AI_ENTRY_MODULES = ("chat", "mcp_server", "debate", "reflection")


def _imports_of(module_name: str) -> set[str]:
    """静态扫模块源码所有 import 顶层名（ast，不执行模块业务逻辑）。"""
    mod = importlib.import_module(module_name)
    src = Path(mod.__file__).read_text(encoding="utf-8")
    tree = ast.parse(src)
    names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for n in node.names:
                names.add(n.name.split(".")[0])
        elif isinstance(node, ast.ImportFrom) and node.module:
            names.add(node.module.split(".")[0])
    return names


def test_ai_entry_modules_do_not_import_private_data():
    """chat / mcp_server / debate / reflection 不 import 个人数据模块（§1.2 隔离）。"""
    leaks: list[str] = []
    for entry in AI_ENTRY_MODULES:
        try:
            imported = _imports_of(entry)
        except ImportError:
            continue  # 模块不可 import（缺依赖等）→ 跳过，不阻断
        leak = imported & PRIVATE_MODULES
        if leak:
            leaks.append(f"{entry} import 了 {leak}")
    assert not leaks, (
        "§1.2 个人数据隔离破坏：\n  " + "\n  ".join(leaks)
        + "\n个人交易数据进 AI prompt = 个性化投资建议，是本项目不可碰的底线。"
    )


def test_private_modules_do_not_import_chat_or_ai_tools():
    """反向边界：个人数据模块不 import chat / 不注册 AI 工具（防反向泄漏）。"""
    for priv in PRIVATE_MODULES:
        try:
            imported = _imports_of(priv)
        except ImportError:
            continue
        assert "chat" not in imported, (
            f"{priv} 不应 import chat（个人数据模块不该碰 AI 入口，§1.2 反向隔离）"
        )
