# -*- coding: utf-8 -*-
"""R1 涨停基因得分采集（B1）。复用 limitup_screener。"""

from __future__ import annotations

import asyncio
import concurrent.futures

import astock  # noqa: F401  (确保限流栈可用)


def _await(coro):
    """在 sync 上下文里跑 limitup_screener 的 async 函数。

    funnel.run_funnel 是 sync 路径（FastAPI 以 threadpool 跑 sync 端点），
    此处无 running loop → asyncio.run；若上层已在 async 上下文（有 running loop），
    则在独立线程起新 loop 跑，避免嵌套 loop 报错。
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


def fetch_genes(date: str) -> dict[str, dict]:
    """返回 {code: {name, gene_score, high_gene, qualify}}。取不到返回 {}。"""
    try:
        import limitup_screener as ls
        if hasattr(ls, "get_screener_result"):
            # get_screener_result 是 async def，必须 await（否则返回 coroutine，下游 gene_scores=None → 静默空）。
            result = _await(ls.get_screener_result(date))
        else:
            result = ls.service.precompute_daily(date)
    except Exception:
        return {}

    scores = getattr(result, "gene_scores", None)
    if scores is None:
        return {}
    out: dict[str, dict] = {}
    for g in scores:
        code = getattr(g, "code", None)
        if not code:
            continue
        out[code] = {
            "name": getattr(g, "name", code),
            "gene_score": getattr(g, "total_score", None),
            "high_gene": getattr(g, "high_gene", False),
            "qualify": getattr(g, "qualify", False),
        }
    return out
