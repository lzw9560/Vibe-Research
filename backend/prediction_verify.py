# -*- coding: utf-8 -*-
"""S061 R3：到期自动验证。

对账函数：到期日取实际收益 → hit/miss/voided。
- horizon=1 用 backtest_lite._calc_next_day_return_meta（次日 close，!fetch_ok→voided）
- horizon>1 用持有期 close 收益
- K 线缺失 → voided 诚实标注
"""
from __future__ import annotations

import logging
from datetime import datetime
from typing import Any

import prediction_ledger as pl

_logger = logging.getLogger("vibe-research")

# 判定阈值：次日溢价>0 即 hit（与漏斗预测 expected=">0" 一致）
HIT_THRESHOLD = 0.0


def _calc_actual_return(code: str, stated_at: str, horizon: int) -> float | None:
    """取实际收益。horizon=1 用次日 close；horizon>1 用 horizon 日后 close。

    返回 None 表示 K 线缺失（不臆造）。
    horizon=1 复用 backtest_lite._calc_next_day_return_meta（mootdx K 线，不联网东财），
    !fetch_ok→None（voided，不计 miss，S123 R4）。
    """
    try:
        from backtest_lite import _calc_next_day_return_meta
        if horizon == 1:
            ret, fetch_ok = _calc_next_day_return_meta(code, stated_at, kline_cache={})
            return ret if fetch_ok else None  # K 线缺失→None（voided，不计 miss，S123 R4）
        # horizon > 1：取 stated_at + horizon 日的 close vs stated_at close
        import astock
        from data.mappers import kline_from_mootdx
        raw = astock.kline(code, category=4, offset=horizon + 15)
        bars = kline_from_mootdx(code, raw).bars
        if not bars:
            return None
        target_close = None
        end_close = None
        for i, b in enumerate(bars):
            if (b.date or "")[:10] == stated_at:
                target_close = b.close
                if i + horizon < len(bars):
                    end_close = bars[i + horizon].close
                break
        if target_close is None or end_close is None:
            return None
        return (end_close - target_close) / target_close if target_close else None
    except Exception as exc:
        _logger.warning("[prediction_verify] %s 收益计算失败: %s", code, exc)
        return None


def verify_due_predictions(as_of: str | None = None,
                            db_path: str = pl.WINRATE_DB_PATH) -> dict[str, Any]:
    """对账入口：扫到期日 <= as_of 的 pending 预测，逐条验证。

    幂等：已验证的不重写（verify_prediction 内 SQL WHERE status='pending'）。
    """
    target_date = as_of or datetime.now().strftime("%Y-%m-%d")
    due = pl.get_due_predictions(target_date, db_path=db_path)
    if not due:
        return {"verified": 0, "hit": 0, "miss": 0, "voided": 0, "expired": 0, "date": target_date}

    verified = hit = miss = voided = 0
    for pred in due:
        actual = _calc_actual_return(pred.code, pred.stated_at, pred.horizon)
        if actual is None:
            ok = pl.verify_prediction(pred.id, None, "voided", "K线缺失", db_path=db_path)
            if ok:
                voided += 1
        else:
            status = "hit" if actual > HIT_THRESHOLD else "miss"
            ok = pl.verify_prediction(pred.id, actual, status, "", db_path=db_path)
            if ok:
                if status == "hit":
                    hit += 1
                else:
                    miss += 1
        if ok:
            verified += 1

    # 过期兜底：到期日 < as_of 仍 pending 的（K 线实在拿不到）→ expired
    expired = pl.expire_overdue(target_date, db_path=db_path)

    return {
        "verified": verified,
        "hit": hit,
        "miss": miss,
        "voided": voided,
        "expired": expired,
        "date": target_date,
    }
