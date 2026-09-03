# -*- coding: utf-8 -*-
"""R1 涨停基因得分采集（B1）。复用 limitup_screener。"""

from __future__ import annotations

import astock  # noqa: F401  (确保限流栈可用)

from utils.async_utils import run_coro_sync  # C3 缓解：async↔sync 桥接（避嵌套 loop）


def fetch_genes(date: str) -> dict[str, dict]:
    """返回 {code: {name, gene_score, high_gene, qualify}}。取不到返回 {}。"""
    try:
        import limitup_screener as ls
        if hasattr(ls, "get_screener_result"):
            # get_screener_result 是 async def，必须 await（否则返回 coroutine，下游 gene_scores=None → 静默空）。
            result = run_coro_sync(ls.get_screener_result(date))
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
            "gene_obj": g,  # S084 R1：存完整 GeneScore 对象（diagnosis.py 塞 card.gene_score）
        }
    return out
