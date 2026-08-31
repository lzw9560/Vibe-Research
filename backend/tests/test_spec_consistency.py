# -*- coding: utf-8 -*-
"""spec→plan/tasks 一致性 lint 回归守卫（task 121）。

防跨会话 drift：plan.md/tasks.md 不得裸引用 spec 已收回的 stale 事实
（具体权重/rebound 主因子/n=6537 单组/039 修饰接入/pass×0.8）。
含 ~~划掉 / §44 注解 / 已废止 / 收回 / placeholder 的视为已处置，跳过。

lint 本体：tools/spec_plan_stale_lint.py（repo root）。
退出码 0=clean，1=有 bare stale（CI 友好；此处作 pytest 断言）。

S066 归档后原 hardcode `_SPEC=specs/S066-...` 路径失效致每次全量 1 failed；
改扫 specs/S* 根所有未归档 spec 的 plan/tasks（active 约定现为 spec.md
单文件，无 plan/tasks 时 skip——约定回归则自动覆盖）。
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

# backend/tests/test_spec_consistency.py → parents[2] = repo root
_REPO = Path(__file__).resolve().parents[2]
_LINT = _REPO / "tools" / "spec_plan_stale_lint.py"


def _active_plan_tasks_files() -> list[Path]:
    """未归档 spec（specs/S* 根，不含 archive）的 plan.md/tasks.md。"""
    specs = _REPO / "specs"
    files: list[Path] = []
    for d in specs.iterdir():
        if not (d.is_dir() and d.name.startswith("S")):
            continue
        for name in ("plan.md", "tasks.md"):
            f = d / name
            if f.exists():
                files.append(f)
    return sorted(files)


def test_plan_tasks_no_bare_stale_markers() -> None:
    """active spec 的 plan/tasks 无 bare stale（spec 已收回事实未裸引用）。"""
    files = _active_plan_tasks_files()
    if not files:
        pytest.skip("无 active spec 用 plan/tasks 约定（当前 spec.md 单文件）")
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
