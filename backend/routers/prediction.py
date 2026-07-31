"""Prediction router — S017 T10.

Exposes the cascade prediction snapshots and the educational intraday
research framework (S4).  All responses carry the research-grade disclaimer.

Compliance (CLAUDE.md §1):
    * Outputs are教育研究性判断 — "历史统计特征，研究参考，不构成投资建议".
    * The intraday framework is a "看什么 / 怎么判" educational checklist with
      **no** buy/sell/stop-loss/take-profit instructions and **no** signal
      push.  ``current_value`` is null until S008 live data lands.
    * Snapshots live project-local (``.vibe-research/``); none enter git.

Until S008 live feature materialisation lands, ``get_features`` returns an
empty DataFrame, so no real predictions are produced — the prediction
endpoint reports ``status: "no_snapshot"`` and the framework reports null
current values rather than fabricating numbers (禁止臆造).
"""

from __future__ import annotations

from datetime import date as _date
from typing import Any

from fastapi import APIRouter, HTTPException, Query

from predict.predict import load_cascade
from predict.feature_interface import HEAD_FEATURE_SUBSETS

router = APIRouter(tags=["prediction"])

DISCLAIMER = "历史统计特征，研究参考，不构成投资建议"

# Educational intraday research framework (S4).  Each item tells the user
# *what to watch* and *how to judge it* — objective reference only, no signal,
# no trade instruction.  Current values are populated once S008 is live.
INTRADAY_FRAMEWORK: list[dict[str, Any]] = [
    {
        "key": "volume_ratio",
        "label": "量比突变",
        "how_to_read": "量比 = 当日成交量 / 过去5日平均成交量。量比放大常伴随分歧或加速。",
        "reference": "量比 > 2 视为显著放量，需结合价格方向研判。",
        "current_value": None,  # TODO S008 live
        "hint": "放量上涨与缩量下跌含义不同，需并表观察。",
    },
    {
        "key": "intraday_price_volume",
        "label": "分时量价形态",
        "how_to_read": "分时白线为价格、黄线为均价。白线持续在黄线上方为相对偏强。",
        "reference": "价格创新高但量能未跟上，注意背离。",
        "current_value": None,
        "hint": "均价线方向与价格关系是研判强弱的基础。",
    },
    {
        "key": "seal_fund_change",
        "label": "封板资金变化",
        "how_to_read": "涨停封单金额增减反映多头延续意愿；封单快速减少需警惕。",
        "reference": "封单金额持续走低或反复开板为弱封信号。",
        "current_value": None,
        "hint": "炸板率与封板资金变化同向观察更稳健。",
    },
    {
        "key": "leader_attribute",
        "label": "龙头属性",
        "how_to_read": "是否为板块领涨标的；龙头通常先于板块启动、晚于板块回落。",
        "reference": "板块联动度高的标的波动放大，独立性强的标的抗板块回落。",
        "current_value": None,
        "hint": "龙头属性需结合连板梯队与板块涨幅排名综合研判。",
    },
]


def intraday_framework_payload(head: str = "short_sector") -> dict[str, Any]:
    """Build the educational intraday framework payload (sync, reusable)."""
    return {
        "head": head,
        "stage": "s4",
        "items": INTRADAY_FRAMEWORK,
        "disclaimer": DISCLAIMER,
    }


def prediction_payload(
    head: str, stage: str, date: str | None = None
) -> dict[str, Any]:
    """Build the cascade-snapshot payload for *head* / *stage* (sync, reusable).

    Shared by the HTTP route and the chat AI tool.
    """
    t = date or _date.today().isoformat()
    snaps = load_cascade(head, t)
    match = next((s for s in snaps if s.stage == stage), None)
    if match is None:
        return {
            "data": None,
            "status": "no_snapshot",
            "head": head,
            "stage": stage,
            "t": t,
            "disclaimer": DISCLAIMER,
        }
    return {
        "data": match.to_dict(),
        "status": "ok",
        "head": head,
        "stage": stage,
        "t": t,
        "disclaimer": DISCLAIMER,
    }


@router.get("/api/prediction/intraday-framework")
async def intraday_framework(
    head: str = Query("short_sector", description="预测头"),
) -> dict[str, Any]:
    """Educational intraday research checklist (S4) — *what to watch*.

    No signals, no trade instructions.  ``current_value`` is null until S008
    live data lands.
    """
    return intraday_framework_payload(head)


@router.get("/api/prediction/{head}")
async def get_prediction(
    head: str,
    stage: str = Query("s1", description="级联阶段 s1|s2|s3"),
    date: str | None = Query(None, description="交易日期 YYYY-MM-DD，默认今日"),
) -> dict[str, Any]:
    """Return the cascade snapshot for *head* / *stage* on *date*.

    Returns ``data: null`` with ``status: "no_snapshot"`` when no snapshot
    has been produced yet (S008 live features pending).  Always carries the
    disclaimer.
    """
    if head not in HEAD_FEATURE_SUBSETS and head != "short_sector":
        raise HTTPException(404, f"unknown prediction head: {head}")
    if stage not in ("s1", "s2", "s3"):
        raise HTTPException(422, f"stage must be one of s1|s2|s3, got '{stage}'")
    return prediction_payload(head, stage, date)


__all__ = ["router"]
