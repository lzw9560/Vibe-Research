# -*- coding: utf-8 -*-
"""pytest conftest — 将项目根目录加入 sys.path，使 `from feishu...` 可被测试导入。

放置在项目根目录，pytest 启动时自动加载。
"""
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))
