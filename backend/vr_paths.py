"""Project-local path helpers for Vibe-Research private data.

约束（用户 2026-07-30 指令，覆盖 CLAUDE.md §1 旧"~/.vibe-research/"约定）：
所有项目相关信息只存项目目录内，不落到 home 目录。私有数据（API key /
持仓 / 研报）放入项目根的 ``.vibe-research/``（gitignored，绝不进 git）。

仍可用 ``VR_DATA_DIR`` / ``VR_REPORTS_DIR`` 环境变量覆盖（测试时 conftest
会指到临时目录隔离）。
"""

from __future__ import annotations

import os
from pathlib import Path

# backend/vr_paths.py → 上一级即仓库根
_REPO_ROOT: Path = Path(__file__).resolve().parents[1]

#: 项目内私有数据根目录（gitignored，绝不进 git）
DEFAULT_DATA_DIR: Path = _REPO_ROOT / ".vibe-research"


def resolve_data_dir() -> Path:
    """返回生效的私有数据根目录：优先 ``$VR_DATA_DIR``，否则项目内默认。"""
    env = os.environ.get("VR_DATA_DIR")
    if env:  # 空串视同未设置
        return Path(env)
    return DEFAULT_DATA_DIR


def resolve_reports_dir() -> Path:
    """返回研报目录：优先 ``$VR_REPORTS_DIR``，否则 data_dir/myreports。"""
    env = os.environ.get("VR_REPORTS_DIR")
    if env:
        return Path(env)
    return resolve_data_dir() / "myreports"
