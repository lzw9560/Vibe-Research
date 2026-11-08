# -*- coding: utf-8 -*-
"""S243 运维 yield executor——逆回购 sweep 提醒 + CB 信用申购提醒。

散户结构性 yield（非选股 alpha）。提醒+规则辅助用户手动执行（非自动交易，PaperPortfolio 无 broker）。
详见 specs/S243-yield-ops-dashboard/spec.md。
"""
from __future__ import annotations

import logging
from typing import Any

from scheduler.executors.signals import _send_text_notification
from data.sources.akshare_yield import get_gc001_rate, get_today_cb_subscriptions

logger = logging.getLogger("vibe-research")


def yield_repo_remind(payload: dict[str, Any]) -> dict[str, Any]:
    """14:30 逆回购 sweep 提醒。触发条件：GC001>3% OR 季末/年末 OR 月末。
    平日 GC001<3% 非季末/月末 → 不打扰（避免轰炸）。"""
    repo = get_gc001_rate()
    if repo.get("error"):
        logger.warning("[yield_repo] fetch err: %s", repo.get("error"))
        return {"status": "skip", "reason": repo.get("error")}

    rate = repo.get("rate")
    qe = repo.get("quarter_end")
    me = repo.get("month_end")
    threshold = repo.get("threshold", 3.0)

    # 触发条件
    should_remind = (rate is not None and rate >= threshold) or qe or me
    if not should_remind:
        return {"status": "skip", "rate": rate, "reason": f"GC001={rate}%<{threshold}% 非季末/月末"}

    # 飞书提醒
    tag = ""
    if qe:
        tag = "🔴 季末/年末高息日"
    elif me:
        tag = "🟡 月末"
    elif rate and rate >= 5:
        tag = "🟢 利率飙升"
    text = (
        f"【逆回购 sweep 时机】{tag}\n"
        f"GC001 年化: {rate}%\n"
        f"季末: {'是' if qe else '否'} | 月末: {'是' if me else '否'}\n"
        f"操作: 14:50 前证券账户逆回购（GC001 沪 / R-001 深）\n"
        f"底仓闲置资金 sweep，零风险 2-3%/年（季末 5-15%）\n"
        f"运维 yield（非选股 alpha）——S243"
    )
    _send_text_notification(text)
    return {"status": "sent", "rate": rate, "quarter_end": qe, "month_end": me}


def yield_cb_remind(payload: dict[str, Any]) -> dict[str, Any]:
    """09:15 CB 信用申购提醒。当日有 CB 申购才提醒（信用申购零成本，中签率低但 lottery）。"""
    today_cbs = get_today_cb_subscriptions()
    if not today_cbs:
        return {"status": "skip", "reason": "今日无 CB 申购"}

    lines = [f"  {c.get('code','')} {c.get('name','')}" for c in today_cbs[:5]]
    text = (
        f"【CB 信用申购】今日 {len(today_cbs)} 只可转债申购\n"
        + "\n".join(lines)
        + (f"\n  ...等 {len(today_cbs)-5} 只" if len(today_cbs) > 5 else "")
        + f"\n操作: 9:30-15:00 信用申购（零成本无市值要求）\n"
        f"中签率低但零成本 lottery——S243"
    )
    _send_text_notification(text)
    return {"status": "sent", "n_cbs": len(today_cbs)}
