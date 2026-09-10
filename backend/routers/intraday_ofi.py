# -*- coding: utf-8 -*-
"""S178 — OFI 盘中数据只读看板 API（read-only，非信号生成器）。

honest label「conditioning 数据收集 · 非交易信号」。数据来自 S176 采集器
（ofi_collect cron */3 9-14 写 intraday_ofi_snapshots）。本路由纯读 load_ofi，
不写私有数据，不接 AI 工具链（防 signal-creep：conditioning 数据默认不进
AI prompt 避免被误用为交易信号源——非隐私隔离，OFI 是公开盘口微结构数据）。
"""
from __future__ import annotations

from typing import Any, Dict

import asyncio
from fastapi import APIRouter, Query

from data.intraday_accumulation_store import load_ofi

router = APIRouter(tags=["intraday_ofi"])


@router.get("/api/intraday/ofi")
async def intraday_ofi(
    date: str = Query(..., description="单日 YYYY-MM-DD（必传，防无界）"),
    code: str | None = Query(None, description="可选 6 位裸 code 过滤"),
    limit: int = Query(2000, ge=1, le=10000, description="上界 10000 防无界 payload"),
) -> Dict[str, Any]:
    """单日 OFI 快照（read-only，非信号）。

    返 {snapshots, count, date, truncated}——用 `snapshots` key 不用 `data`，
    避 client.ts:66 auto-unwrap 吞 `truncated` 元数据。
    """
    def _build() -> dict:
        rows = load_ofi(date, date)  # 单日强制（防无界 payload）
        if code:
            rows = [r for r in rows if r.get("code") == code]
        total = len(rows)
        truncated = total > limit
        snapshots = rows[:limit]
        return {
            "snapshots": snapshots,
            "count": len(snapshots),
            "date": date,
            "truncated": truncated,
        }
    return await asyncio.to_thread(_build)
