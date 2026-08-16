# -*- coding: utf-8 -*-
"""工作流阶段/日期判定正确性（S068 §9 后续 small 级修复）。

- get_current_stage 用北京时区 + 09:00-09:30 竞价归盘前（原 naive+误归 intraday）。
- TradingWorkflow.__init__ 用 last_trading_date_str（原 naive today，周末/节假日取错日）。
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

_BEI = timezone(timedelta(hours=8))


def _at(hhmm: str, day: int = 17) -> datetime:  # 2026-08-17 周一
    h, m = hhmm.split(":")
    return datetime(2026, 8, day, int(h), int(m), tzinfo=_BEI)


def test_get_current_stage_boundaries():
    from trading_workflow import TradingWorkflow

    w = TradingWorkflow()
    # 09:00-09:29 竞价归盘前（原实现误归 intraday 上午盘）
    assert w.get_current_stage(_at("09:00"))["stage"] == "pre-market"
    assert w.get_current_stage(_at("09:29"))["stage"] == "pre-market"
    # 09:30 开盘 → intraday 上午盘
    s = w.get_current_stage(_at("09:30"))
    assert s["stage"] == "intraday" and s["market_status"] == "上午盘"
    # 11:30 仍上午盘；14:00 下午盘
    assert w.get_current_stage(_at("11:30"))["market_status"] == "上午盘"
    assert w.get_current_stage(_at("14:00"))["market_status"] == "下午盘"
    # 15:00 收盘 → 盘后
    assert w.get_current_stage(_at("15:00"))["stage"] == "post-market"
    # 08:00 盘前；07:00 / 22:00 非交易时段
    assert w.get_current_stage(_at("08:00"))["stage"] == "pre-market"
    assert w.get_current_stage(_at("07:00"))["market_status"] == "非交易时段"
    assert w.get_current_stage(_at("22:00"))["market_status"] == "非交易时段"


def test_init_uses_last_trading_date(monkeypatch):
    """__init__(date=None) 应委托 last_trading_date_str，而非 datetime.now()（周末取错日）。"""
    import trading_workflow as tw

    monkeypatch.setattr(tw, "last_trading_date_str", lambda d=None: "2026-08-14")
    w = tw.TradingWorkflow()
    assert w.date == "2026-08-14"
    # 显式 date 不被覆盖
    assert tw.TradingWorkflow(date="2026-08-03").date == "2026-08-03"


def test_non_trading_day_does_not_advance():
    """非交易日（周末/节假日）整日不随时间推进——固定"非交易日"（原实现周六 10:00 误显 intraday）。"""
    from trading_workflow import TradingWorkflow
    w = TradingWorkflow()
    # 2026-08-15 周六 10:00——若只看时分会显 intraday 上午盘，但周六非交易日→固定非交易日
    sat_am = datetime(2026, 8, 15, 10, 0, tzinfo=_BEI)
    s = w.get_current_stage(sat_am)
    assert s["market_status"] == "非交易日"
    assert s["stage"] == "pre-market"  # 不推进到 intraday
    # 周六 15:00 也固定非交易日（不推进到 post-market）
    sat_pm = datetime(2026, 8, 15, 15, 0, tzinfo=_BEI)
    assert w.get_current_stage(sat_pm)["market_status"] == "非交易日"
    # 对照：交易日（周一 2026-08-17 10:00）正常推进 intraday
    mon_am = datetime(2026, 8, 17, 10, 0, tzinfo=_BEI)
    assert w.get_current_stage(mon_am)["stage"] == "intraday"
