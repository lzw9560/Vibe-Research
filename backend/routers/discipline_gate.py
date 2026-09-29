# -*- coding: utf-8 -*-
"""S231 打板纪律门禁 router——前端看板展示 verdict。

风控工具非 edge 基建。只读 evaluate_discipline_gate 结果，不创造 alpha。
"""
from typing import Any, Dict

from fastapi import APIRouter, Query

from tools.discipline_gate import evaluate_discipline_gate, render_discipline_report
from vr_paths import prev_trading_date_str

router = APIRouter(tags=["discipline-gate"])


@router.get("/api/discipline-gate/verdict")
def get_discipline_verdict(
    date: str | None = Query(None, description="YYYY-MM-DD，默认上一交易日"),
) -> Dict[str, Any]:
    """S231 打板纪律门禁 verdict——7 条件门禁 + cap=0 terminal + 飞书报告。

    前端看板用：展示当前打板纪律状态（BLOCK/CAUTION/PASS）+ 7 条件 pass/fail。
    """
    target = date or prev_trading_date_str()
    verdict = evaluate_discipline_gate(target)
    return {"data": verdict}


@router.get("/api/discipline-gate/report")
def get_discipline_report(
    date: str | None = Query(None, description="YYYY-MM-DD，默认上一交易日"),
) -> Dict[str, Any]:
    """S231 打板纪律门禁人话报告（飞书格式）。"""
    target = date or prev_trading_date_str()
    verdict = evaluate_discipline_gate(target)
    report = render_discipline_report(verdict)
    return {"data": {"verdict": verdict, "report_text": report}}
