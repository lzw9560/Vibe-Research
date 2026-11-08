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


def get_trailing_relative_return(window: int = LOOKBACK_DAYS) -> dict[str, Any]:
    """S244 监控 enrichment:512890 vs 沪深300 trailing 相对收益。

    6专家panel共识:S44 drawdown_monitor 只算绝对回撤,挡不住 regime-drift 慢渗
    (2025 超额 -13% 但绝对 +4.6% 未触发减仓)。加 trailing 相对收益监控,
    跑输 >10% 时提醒 "alpha regime shift—review thesis"。

    返回 {etf_ret, bench_ret, relative_ret, flag}。flag="regime_shift" 若 relative < -10%。
    """
    import akshare as ak  # noqa: PLC0415
    etf_df = ak.fund_etf_hist_em(symbol=ETF_CODE, period="daily", adjust="qfq")
    bench_df = ak.stock_zh_index_daily_em(symbol="sh000300")  # 沪深300
    etf_df["日期"] = etf_df["日期"].astype(str)
    bench_df["date"] = bench_df["date"].astype(str)
    # 对齐日期(沪深300 日期范围更广,取交集)
    merged = etf_df[["日期", "收盘"]].merge(
        bench_df[["date", "close"]], left_on="日期", right_on="date"
    ).tail(window)
    etf_ret = (float(merged["收盘"].iloc[-1]) / float(merged["收盘"].iloc[0]) - 1) if len(merged) > 1 else 0.0
    bench_ret = (float(merged["close"].iloc[-1]) / float(merged["close"].iloc[0]) - 1) if len(merged) > 1 else 0.0
    rel = etf_ret - bench_ret
    flag = "regime_shift" if rel < -0.10 else "normal"
    return {
        "etf_ret": etf_ret,
        "bench_ret": bench_ret,
        "relative_ret": rel,
        "flag": flag,
        "window_days": len(merged),
    }


def portfolio_rebalance_remind(payload: dict[str, Any]) -> dict[str, Any]:
    """季初(1/4/7/10 月)提醒调回 25% 仓位。非季初 skip 不打扰。

    S244 监控 enrichment(6专家panel):加 trailing 相对收益(512890 vs 沪深300),
    跑输 >10% 时提醒加 "⚠ alpha regime shift—review thesis" flag(仅 review 不自动减仓)。
    """
    now = datetime.now()
    month = now.month
    if month not in (1, 4, 7, 10):
        return {"status": "skip", "reason": f"非季初月({month}月),不打扰"}
    # trailing 相对收益监控(6专家panel consensus:regime-drift 缺口)
    rel_info = None
    regime_flag = ""
    try:
        rel_info = get_trailing_relative_return()
        if rel_info["flag"] == "regime_shift":
            regime_flag = (
                f"\n⚠ alpha regime shift—review thesis\n"
                f"  512890 trailing {rel_info['window_days']}日 {rel_info['etf_ret']*100:+.1f}% vs 沪深300 {rel_info['bench_ret']*100:+.1f}%"
                f" → 跑输 {rel_info['relative_ret']*100:+.1f}% (<-10% 阈值)\n"
                f"  flag 仅 review 不自动减仓(S44 drawdown -20% 仍管绝对回撤)"
            )
    except Exception as e:  # noqa: BLE001
        logger.warning("[portfolio_rebalance] trailing rel err: %s", repr(e)[:100])
    text = (
        f"【季再平衡提醒】512890 红利低波底仓调回目标仓位 {int(TARGET_WEIGHT*100)}%\n"
        f"规则(回测验证 S244):20-30% Sharpe 最优区间(20% S1.223 / 30% S1.035)"
        f"{regime_flag}\n"
        f"操作:调仓到 {int(TARGET_WEIGHT*100)}% + 闲置资金 GC001 逆回购 sweep(S243)\n"
        f"非自动交易,用户手动执行——S244 practitioner reframe(散户 edge 在 sizing)"
    )
    _send_text_notification(text)
    return {
        "status": "sent",
        "target_weight": TARGET_WEIGHT,
        "month": month,
        "regime_flag": rel_info["flag"] if rel_info else "unknown",
        "relative_ret": rel_info["relative_ret"] if rel_info else None,
    }


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
