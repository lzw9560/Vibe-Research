# -*- coding: utf-8 -*-
"""async↔sync 桥接工具：在 sync 上下文跑 async 函数，避嵌套 event loop（C3 缓解）。

quant-mindset C3 裂缝登记：asyncio.run 不能在 running loop 里调（嵌套 loop 崩，
RuntimeError: asyncio.run() cannot be called from a running event loop）。
本 helper 检测 running loop：有则线程兜底（新线程起新 loop），无则直接 asyncio.run。
单一源（DRY：原 candidate_funnel/sources/gene.py 与 factors/limitup_screener_factor.py
各有一份相同 _await，copy-paste 易漂移，抽此共享）。
"""

from __future__ import annotations

import asyncio
import concurrent.futures
from typing import Any


def run_coro_sync(coro: Any) -> Any:
    """在 sync 上下文跑 async coro，自动避嵌套 event loop（C3 缓解）。

    无 running loop（纯 sync / FastAPI sync 端点 threadpool 路径）→ 直接 asyncio.run(coro)。
    有 running loop（被 async fn 直调）→ ThreadPoolExecutor 起新线程跑 asyncio.run，
    避免 'asyncio.run() cannot be called from a running event loop' 崩溃。

    用法：sync 代码需取 async 结果时调本函数；勿在 async fn 里直接 asyncio.run。
    """
    try:
        asyncio.get_running_loop()
        running = True
    except RuntimeError:
        running = False
    if running:
        with concurrent.futures.ThreadPoolExecutor(max_workers=1) as ex:
            return ex.submit(asyncio.run, coro).result()
    return asyncio.run(coro)
