# -*- coding: utf-8 -*-
"""S244 红利低波 512890 仓位规则 executor——季再平衡 + drawdown 监控。

practitioner reframe 落地:选股 alpha 穷尽后,散户 edge 在 sizing/风控/行为。
仓位规则基于 explore_portfolio_allocation.py 回测验证:
- 512890 底仓 25%(20-30% Sharpe 最优区间中值,20% S1.223 / 30% S1.035)
- 季再平衡(每季初调回 25%)
- drawdown control 简化:-20% 减仓提醒(回测显示 -15% 减半边际效果小,放宽 -20%)

非自动交易(PaperPortfolio 无 broker),提醒辅助用户手动执行。
详见 specs/S244-divlowvol-position-rule/spec.md。
"""
from __future__ import annotations

import logging
from datetime import datetime
from typing import Any

from scheduler.executors.signals import _send_text_notification

logger = logging.getLogger("vibe-research")

TARGET_WEIGHT = 0.25  # 25% 底仓(20-30% 最优区间中值)
DD_CUT = -0.20  # -20% 减仓提醒(回测验证 -15% 边际效果小,放宽 -20%)
DD_RECOVER = -0.10  # -10% 正常区(>= -10% 不打扰)
ETF_CODE = "512890"
LOOKBACK_DAYS = 250  # 滚动峰值窗口(约 1 年)


def get_divlowvol_drawdown() -> dict[str, Any]:
    """拉 512890 近 LOOKBACK_DAYS 日,算当前 drawdown(从滚动峰值)。

    走 akshare fund_etf_hist_em(东财 fund 接口,非 datacenter,单次调用无熔断风险)。
    返回 {code, current, peak, drawdown, date}。
    """
    import akshare as ak  # noqa: PLC0415
    df = ak.fund_etf_hist_em(symbol=ETF_CODE, period="daily", adjust="qfq")
    df = df.tail(LOOKBACK_DAYS).reset_index(drop=True)
    close = df["收盘"].astype(float)
    peak = float(close.max())
    cur = float(close.iloc[-1])
    dd = (cur - peak) / peak if peak > 0 else 0.0
    return {
        "code": ETF_CODE,
        "current": cur,
        "peak": peak,
        "drawdown": dd,
        "date": str(df["日期"].iloc[-1])[:10],
    }


def portfolio_rebalance_remind(payload: dict[str, Any]) -> dict[str, Any]:
    """季初(1/4/7/10 月)提醒调回 25% 仓位。非季初 skip 不打扰。"""
    now = datetime.now()
    month = now.month
    if month not in (1, 4, 7, 10):
        return {"status": "skip", "reason": f"非季初月({month}月),不打扰"}
    text = (
        f"【季再平衡提醒】512890 红利低波底仓调回目标仓位 {int(TARGET_WEIGHT*100)}%\n"
        f"规则(回测验证 S244):20-30% Sharpe 最优区间(20% S1.223 / 30% S1.035)\n"
        f"操作:调仓到 {int(TARGET_WEIGHT*100)}% + 闲置资金 GC001 逆回购 sweep(S243)\n"
        f"非自动交易,用户手动执行——S244 practitioner reframe(散户 edge 在 sizing)"
    )
    _send_text_notification(text)
    return {"status": "sent", "target_weight": TARGET_WEIGHT, "month": month}


def portfolio_drawdown_monitor(payload: dict[str, Any]) -> dict[str, Any]:
    """512890 drawdown 监控:-20% 减仓提醒,>=-10% 正常 skip,中间观察区 skip。

    回测验证( explore_portfolio_allocation.py):-15% 减半边际效果小(512890 低波减半错过反弹),
    放宽到 -20% 减仓提醒。
    """
    try:
        info = get_divlowvol_drawdown()
    except Exception as e:  # noqa: BLE001
        logger.warning("[portfolio_dd] fetch err: %s", repr(e)[:120])
        return {"status": "skip", "reason": f"fetch err: {repr(e)[:80]}"}

    dd = info["drawdown"]
    if dd <= DD_CUT:
        text = (
            f"【512890 减仓提醒】drawdown {dd*100:.1f}% ≤ {int(DD_CUT*100)}%\n"
            f"当前价 {info['current']:.3f} vs 滚动峰值 {info['peak']:.3f}({info['date']})\n"
            f"建议:减仓到 {int(TARGET_WEIGHT*50)}%(目标 {int(TARGET_WEIGHT*100)}%/2)\n"
            f"规则(S244):-20% 减仓提醒(回测 -15% 边际效果小放宽),用户手动决策"
        )
        _send_text_notification(text)
        return {"status": "sent", "drawdown": dd, "action": "reduce", "current": info["current"]}
    if dd >= DD_RECOVER:
        return {"status": "skip", "drawdown": dd, "reason": f"drawdown {dd*100:.1f}% ≥ {int(DD_RECOVER*100)}% 正常"}
    return {"status": "skip", "drawdown": dd, "reason": f"drawdown {dd*100:.1f}% 在观察区({int(DD_CUT*100)}%~{int(DD_RECOVER*100)}%)"}
