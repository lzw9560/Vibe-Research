#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""S164 R3：裸 requests lint gate —— 禁止裸调 requests.get/post on eastmoney/tencent host。

CI gate：所有东财/腾讯端点调用必须走 ``em_get``（限流 + 熔断 + 代理降级防封路径）。
裸 ``requests.get`` / ``requests.post`` / ``session.get`` / ``session.post`` 直接打
eastmoney/tencent host 绕过防封 backbone，有 IP 封禁风险。

用法（CI gate）::

    python backend/tools/lint_no_bare_requests.py
    # exit 0 = 无违规（或仅 known violations）
    # exit 1 = 发现新违规

已知违规（待统一 em_get，advisory 不阻断 CI）：
- ``data/sources/eastmoney.py`` :: ``eastmoney_reports`` / ``eastmoney_industry_reports``
  （reportapi.eastmoney.com，走 ``_report_session().get()``）
- ``data/sources/eastmoney.py`` :: ``hot_concepts``
  （emappdata.eastmoney.com，走 ``requests.post()``）

白名单（em_get 实现本身 / proxy health-check）：
- ``data/transport.py`` —— em_get 限流/熔断/代理路径的内部 session.get
- ``proxy_pool.py`` —— proxy 健康检查裸调 push2his（deferred optional，by design）
"""

from __future__ import annotations

import ast
import sys
from pathlib import Path

# 必须走 em_get 的 host（东财 + 腾讯）
PROTECTED_HOSTS = (
    "eastmoney.com",
    "tencent.com",
    "qq.com",
)

# em_get 实现本身 + proxy health-check（裸 requests 是 by design）
WHITELIST_FILES = {
    "data/transport.py",
    "proxy_pool.py",
}

# 已知违规函数名（待统一 em_get，advisory 不阻断 CI）
KNOWN_VIOLATION_FUNCS = {
    "eastmoney_reports",
    "eastmoney_industry_reports",
    "hot_concepts",
}


class _BareRequestsFinder(ast.NodeVisitor):
    """AST 遍历：找 .get()/.post() 调用打 protected host 的代码。"""

    def __init__(self, filepath: str, source_lines: list[str]):
        self.filepath = filepath
        self.source_lines = source_lines
        self.violations: list[tuple[int, str, str]] = []  # (lineno, url, func_name)
        # 收集模块级 string 赋值（用于解析 _REPORT_API = "..." 这类变量）
        self._string_vars: dict[str, str] = {}
        # 当前所在函数名
        self._func_stack: list[str] = []

    def _is_protected(self, url: str) -> bool:
        return any(h in url for h in PROTECTED_HOSTS)

    def _resolve_arg(self, arg: ast.AST) -> str | None:
        """解析调用的第一个参数为 URL 字符串。"""
        if isinstance(arg, ast.Constant) and isinstance(arg.value, str):
            return arg.value
        if isinstance(arg, ast.Name):
            return self._string_vars.get(arg.id)
        if isinstance(arg, ast.JoinedStr):  # f-string
            # 拼接所有静态部分
            parts = []
            for val in arg.values:
                if isinstance(val, ast.Constant) and isinstance(val.value, str):
                    parts.append(val.value)
            return "".join(parts) if parts else None
        return None

    def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
        self._func_stack.append(node.name)
        self.generic_visit(node)
        self._func_stack.pop()

    visit_AsyncFunctionDef = visit_FunctionDef

    def visit_Assign(self, node: ast.Assign) -> None:
        """收集模块级/函数级 string 变量赋值（如 _REPORT_API = "..."）。"""
        if len(node.targets) == 1 and isinstance(node.targets[0], ast.Name):
            if isinstance(node.value, ast.Constant) and isinstance(node.value.value, str):
                self._string_vars[node.targets[0].id] = node.value.value
        self.generic_visit(node)

    def visit_Call(self, node: ast.Call) -> None:
        """找 .get()/.post() 调用打 protected host。"""
        if isinstance(node.func, ast.Attribute) and node.func.attr in ("get", "post"):
            if node.args:
                url = self._resolve_arg(node.args[0])
                if url and self._is_protected(url):
                    func_name = self._func_stack[-1] if self._func_stack else "<module>"
                    self.violations.append((node.lineno, url, func_name))
        self.generic_visit(node)


def _relative_path(filepath: Path, backend_root: Path) -> str:
    """返回相对 backend/ 的路径（如 data/sources/eastmoney.py）。"""
    try:
        return str(filepath.relative_to(backend_root))
    except ValueError:
        return str(filepath)


def lint(backend_root: Path) -> int:
    """扫描 backend/ 下所有 .py 文件（排除 tests/tools/.venv/__pycache__）。

    返回 exit code（0 = 通过，1 = 有新违规）。
    """
    new_violations: list[tuple[str, int, str, str]] = []  # (file, lineno, url, func)
    known_found: list[tuple[str, int, str, str]] = []

    # 排除目录前缀（相对 backend/）
    skip_prefixes = ("tests/", "tools/", ".venv/", "__pycache__/")

    scanned = 0
    for py_file in sorted(backend_root.rglob("*.py")):
        rel = _relative_path(py_file, backend_root)
        if rel in WHITELIST_FILES:
            continue
        if any(rel.startswith(p) for p in skip_prefixes):
            continue
        try:
            source = py_file.read_text(encoding="utf-8")
            tree = ast.parse(source, filename=str(py_file))
        except (SyntaxError, UnicodeDecodeError):
            continue
        finder = _BareRequestsFinder(rel, source.splitlines())
        finder.visit(tree)
        scanned += 1
        for lineno, url, func_name in finder.violations:
            entry = (rel, lineno, url, func_name)
            if func_name in KNOWN_VIOLATION_FUNCS:
                known_found.append(entry)
            else:
                new_violations.append(entry)

    # 报告
    print("=" * 70)
    print("S164 R3: 裸 requests lint gate — eastmoney/tencent host 必须走 em_get")
    print("=" * 70)
    print(f"扫描 {scanned} 个文件\n")

    if known_found:
        print(f"[KNOWN] {len(known_found)} 处已知违规（待统一 em_get，advisory）:")
        for rel, lineno, url, func in known_found:
            print(f"  {rel}:{lineno}  {func}()  →  {url}")
        print()

    if new_violations:
        print(f"[FAIL] {len(new_violations)} 处新违规（必须走 em_get）:")
        for rel, lineno, url, func in new_violations:
            print(f"  {rel}:{lineno}  {func}()  →  {url}")
        print("\n修复：将 requests.get/post 改为 em_get（限流+熔断+代理降级防封路径）")
        return 1

    print("[PASS] 无新违规（所有 eastmoney/tencent 调用走 em_get）")
    return 0


if __name__ == "__main__":
    backend_root = Path(__file__).resolve().parent.parent
    sys.exit(lint(backend_root))
