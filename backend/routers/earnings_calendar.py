"""S216 P2 EarningsCalendar router — 全市场财报季日历聚合。

GET /api/earnings-calendar?codes=600519,000001&forward_days=90
返 DANGER_MONTHS（监管强制披露窗口 1.31/4.30/8.31，公开知识非臆造）
+ 可选 per_code 聚合（announcements + lockup_expiry，东财走 em_get 防封）。

守工程底线：
- 不臆造（缺数据返空 + data_status，非 mock 假数据）
- 私有数据隔离（codes 由用户提供，不读持仓/研报）
- 东财走 em_get 不裸调 requests（astock.announcements/lockup_expiry 已走 em_get）
"""
from __future__ import annotations

import logging
from typing import Any, Dict

from fastapi import APIRouter, HTTPException, Query

router = APIRouter(tags=["earnings-calendar"])
logger = logging.getLogger("vibe-research")

# A 股财报披露窗口：1/4/8 月为强制披露雷区（公开监管知识，非臆造数据）。
# 1 月：三季报 + 年度业绩预告/快报 deadline（1.31）
# 4 月：年报 deadline（4.30）+ 一季报
# 8 月：中报 deadline（8.31）
DANGER_MONTHS = [
    {"month": 1, "label": "1 月", "reason": "三季报 + 年度业绩预告/快报（1.31 deadline）", "deadline": "01-31"},
    {"month": 4, "label": "4 月", "reason": "年报（4.30 deadline）+ 一季报", "deadline": "04-30"},
    {"month": 8, "label": "8 月", "reason": "中报（8.31 deadline）", "deadline": "08-31"},
]


def _validate_codes(codes_str: str) -> list[str]:
    """逗号分隔 6 位代码校验。非法 → 400（fail fast）。"""
    if not codes_str:
        return []
    raw = [c.strip() for c in codes_str.split(",") if c.strip()]
    if not raw:
        return []
    if any(not c.isdigit() or len(c) != 6 for c in raw):
        raise HTTPException(400, "codes 必须是逗号分隔的 6 位数字")
    return raw


def _aggregate_per_code(code: str, forward_days: int) -> dict:
    """单 code 聚合 announcements + lockup_expiry。缺数据标 missing 不臆造。"""
    import astock  # noqa: PLC0415
    announcements: list[dict] = []
    lockup_expiries: list[dict] = []
    status = "ok"
    errors: list[str] = []
    try:
        announcements = astock.announcements(code, limit=15)
    except Exception as e:  # noqa: BLE001
        status = "missing"
        errors.append(f"announcements: {e!r}")
    try:
        lockup = astock.lockup_expiry(code, forward_days=forward_days, raise_on_failure=True)
        lockup_expiries = lockup.get("upcoming", []) if isinstance(lockup, dict) else []
    except Exception as e:  # noqa: BLE001
        if status != "ok":
            status = "missing"
        else:
            status = "partial"
        errors.append(f"lockup: {e!r}")
    return {
        "code": code,
        "announcements": announcements,
        "lockup_expiries": lockup_expiries,
        "data_status": status,
        "errors": errors,
    }


@router.get("/api/earnings-calendar")
def earnings_calendar(
    codes: str = Query("", description="逗号分隔的 6 位代码，可选（提供则聚合 per-code 披露/解禁）"),
    forward_days: int = Query(90, ge=1, le=365, description="解禁前瞻天数"),
) -> Dict[str, Any]:
    """财报季日历聚合：DANGER_MONTHS（监管强制披露窗口）+ 可选 per-code 聚合。

    无 codes → 返日历结构（DANGER_MONTHS 公开知识），per_code=None。
    有 codes → 聚合 per-code announcements + lockup_expiry（东财走 em_get 防封）。
    缺数据 → data_status=partial/missing 不臆造。
    """
    code_list = _validate_codes(codes)
    if not code_list:
        return {
            "data": {
                "danger_months": DANGER_MONTHS,
                "per_code": None,
                "data_status": "empty",
                "note": "无 codes 参数，仅返日历结构。提供 codes 查 per-code 披露/解禁聚合。",
            }
        }

    per_code = []
    n_missing = 0
    for code in code_list:
        result = _aggregate_per_code(code, forward_days)
        per_code.append(result)
        if result["data_status"] == "missing":
            n_missing += 1

    if n_missing == len(per_code):
        overall = "missing"
    elif n_missing > 0:
        overall = "partial"
    else:
        overall = "ok"

    return {
        "data": {
            "danger_months": DANGER_MONTHS,
            "per_code": per_code,
            "data_status": overall,
            "note": "财报季日历聚合，东财端点走 em_get 防封。历史统计特征，市场有风险。",
        }
    }


def is_earnings_season_unsafe(code: str, target_date: str) -> bool:
    """M5 ReportSeasonCircuitBreaker：财报季未披露股拉黑（防一字跌停保护钱）。

    判 target_date 月 in DANGER_MONTHS（1/4/8）+ 该 code 在窗口内无 announcement → 未披露 → True。
    异常/失败 → False（不拉黑，不臆造——缺数据不拦交易，只拦确认未披露）。
    """
    try:
        from datetime import datetime  # noqa: PLC0415
        month = datetime.strptime(target_date[:10], "%Y-%m-%d").month
    except (ValueError, TypeError):
        return False
    if month not in {d["month"] for d in DANGER_MONTHS}:
        return False  # 非财报季月，不拦
    try:
        import astock  # noqa: PLC0415
        announcements = astock.announcements(code, limit=15)
    except Exception:
        return False  # 数据取得失败不拦（不臆造）
    return len(announcements) == 0  # 财报季月内无 announcement → 未披露 → 拉黑


__all__ = ["router", "is_earnings_season_unsafe"]
