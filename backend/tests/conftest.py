# -*- coding: utf-8 -*-
"""backend/tests/conftest.py — pytest 共享 fixture + sys.path 注入。

确保 `import astock` / `from config import ...` 等扁平布局导入在测试中可用。
"""
import sys
from pathlib import Path

# backend/ 目录在 sys.path（扁平布局，非包）
_backend_dir = str(Path(__file__).resolve().parent.parent)
if _backend_dir not in sys.path:
    sys.path.insert(0, _backend_dir)

# 项目根目录在 sys.path（vr_paths 等）
_root_dir = str(Path(__file__).resolve().parents[2])
if _root_dir not in sys.path:
    sys.path.insert(0, _root_dir)
