# -*- coding: utf-8 -*-
"""S243 运维 yield AI 工具——query_yield 查 GC001/CB/打新。

@register_tool 注册后，chat.TOOLS（API /api/chat）+ MCP 自动同时获得（§3 架构约定）。
"""
from __future__ import annotations

from data.sources import akshare_yield
from ai.tools.registry import register_tool


@register_tool(
    "query_yield",
    "查今日运维 yield 时机：GC001 逆回购实时年化利率 + 季末/月末标记 + 今日 CB 信用申购 + 今日打新筛选红线。"
    "散户结构性 yield（非选股 alpha）：逆回购零风险 2-3%/年（季末 5-15%）/CB 零成本信用申购/打新筛选（发行PE/行业PE>1.5 高溢价风险）。"
    "S243。",
)
def query_yield() -> dict:
    repo = akshare_yield.get_gc001_rate()
    cbs = akshare_yield.get_today_cb_subscriptions()
    ipos = akshare_yield.get_today_ipos()
    return {
        "repo": repo,
        "cb_today": {"count": len(cbs), "items": cbs},
        "ipo_today": {"count": len(ipos), "items": ipos},
        "summary": (
            f"GC001={repo.get('rate')}%（季末={'是' if repo.get('quarter_end') else '否'}），"
            f"今日 CB 申购 {len(cbs)} 只，打新 {len(ipos)} 只"
        ),
    }
