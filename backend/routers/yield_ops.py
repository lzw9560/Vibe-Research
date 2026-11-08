# -*- coding: utf-8 -*-
"""S243 运维 yield router——GC001 逆回购 + CB 信用申购。

散户结构性 yield（非选股 alpha）。详见 specs/S243-yield-ops-dashboard/spec.md。
"""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter

from data.sources.akshare_yield import get_gc001_rate, get_cb_list, get_today_cb_subscriptions, get_today_ipos

router = APIRouter(tags=["yield-ops"])


@router.get("/api/yield/repo")
def repo_yield() -> dict[str, Any]:
    """GC001 逆回购实时年化利率 + 季末/年末标记。"""
    return get_gc001_rate()


@router.get("/api/yield/cb")
def cb_list() -> dict[str, Any]:
    """CB 全市场列表（含申购日/上市日）。"""
    return {"count": 0, "items": get_cb_list()}


@router.get("/api/yield/cb/today")
def cb_today() -> dict[str, Any]:
    """今日申购 CB（09:15 提醒用）。"""
    items = get_today_cb_subscriptions()
    return {"count": len(items), "items": items, "date": __import__("datetime").date.today().isoformat()}


@router.get("/api/yield/ipo")
def ipo_today() -> dict[str, Any]:
    """今日申购新股 + 打新筛选红线（发行PE/行业PE 避雷）。"""
    items = get_today_ipos()
    return {"count": len(items), "items": items, "date": __import__("datetime").date.today().isoformat()}


@router.get("/api/yield/snapshot")
def yield_snapshot() -> dict[str, Any]:
    """运维 yield 总览：GC001 + 今日 CB + 今日打新（看板 panel 用）。"""
    repo = get_gc001_rate()
    today_cbs = get_today_cb_subscriptions()
    today_ipos = get_today_ipos()
    return {
        "repo": repo,
        "cb_today": {"count": len(today_cbs), "items": today_cbs},
        "ipo_today": {"count": len(today_ipos), "items": today_ipos},
    }
