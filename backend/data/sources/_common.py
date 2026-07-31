# -*- coding: utf-8 -*-
"""S008 源模块共享件。

- ``UA``：HTTP User-Agent（tencent urllib / eastmoney requests / cninfo 共用）。
- ``DependencyMissing``：惰性依赖（akshare/mootdx）未装时抛出，前端据此提示安装。

从 ``astock.py`` 迁出，逻辑不变。
"""

from __future__ import annotations


UA = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36"


class DependencyMissing(RuntimeError):
    """惰性依赖未安装时抛出，前端据此提示 pip install。"""
