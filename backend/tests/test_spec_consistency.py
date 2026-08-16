# -*- coding: utf-8 -*-
"""spec→plan/tasks 一致性 lint 回归守卫（task 121）。

防跨会话 drift：plan.md/tasks.md 不得裸引用 spec 已收回的 stale 事实
（具体权重/rebound 主因子/n=6537 单组/039 修饰接入/pass×0.8）。
含 ~~划掉 / §44 注解 / 已废止 / 收回 / placeholder 的视为已处置，跳过。

lint 本体：tools/spec_plan_stale_lint.py（repo root）。
退出码 0=clean，1=有 bare stale（CI 友好；此处作 pytest 断言）。
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

# backend/tests/test_spec_consistency.py → parents[2] = repo root
_REPO = Path(__file__).resolve().parents[2]
_LINT = _REPO / "tools" / "spec_plan_stale_lint.py"
_SPEC = _REPO / "specs" / "S066-策略特定漏斗架构重构"


def test_plan_tasks_no_bare_stale_markers() -> None:
    """plan/tasks 无 bare stale（spec 已收回事实未裸引用）。"""
    files = [_SPEC / "plan.md", _SPEC / "tasks.md"]
    missing = [str(f) for f in files if not f.exists()]
    assert not missing, f"spec plan/tasks 文件缺失：{missing}"

    r = subprocess.run(
        [sys.executable, str(_LINT), *[str(f) for f in files]],
        capture_output=True,
        text=True,
        cwd=str(_REPO),
    )
    assert r.returncode == 0, (
        "spec→plan/tasks 一致性 lint 发现 bare stale（spec 已收回但 plan/tasks 仍裸引用）：\n"
        + r.stdout
    )
