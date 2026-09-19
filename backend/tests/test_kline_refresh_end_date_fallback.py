# -*- coding: utf-8 -*-
"""refresh_kline_cache end_date 回退测试。

bug（2026-09-20 v3 审查发现）：kline_refresh cron 17:15 跑时 ``end_date =
last_trading_date()``（今天 09-19），baostock 当日 bar 17:00+ 才更新。未就绪时
line 78-81 ``return 0`` 跳过整轮——连 09-17/18 的 bars 也不拉 → cache 停在
上次成功刷新日期（实测停 09-16，3 交易日 stale）。

fix：当日 bar 未就绪时回退 ``end_date = prev_trading_date_str()``，继续刷新
前一天数据（不跳过整轮）。
"""
from __future__ import annotations


def test_resolve_end_date_today_ready_no_fallback(monkeypatch):
    """当日 bar 就绪 → end_date 不变，不回退。"""
    from tools.refresh_kline_cache import _resolve_refresh_end_date

    # Arrange — fetch 返非空 = 当日 bar 就绪
    fetch_fn = lambda code, start, end: [{"date": end, "close": 100.0}]

    # Act
    end, skipped = _resolve_refresh_end_date("2026-09-19", fetch_fn)

    # Assert
    assert end == "2026-09-19"
    assert skipped is False


def test_resolve_end_date_today_not_ready_falls_back_to_prev(monkeypatch):
    """当日 bar 未就绪 → 回退到前一交易日，不跳过整轮（仍返 end_date 供刷新）。"""
    from tools.refresh_kline_cache import _resolve_refresh_end_date

    # Arrange — fetch 返空 = 当日 bar 未就绪
    fetch_fn = lambda code, start, end: []
    monkeypatch.setattr("vr_paths.prev_trading_date_str", lambda: "2026-09-18")

    # Act
    end, skipped = _resolve_refresh_end_date("2026-09-19", fetch_fn)

    # Assert — 回退到前一交易日，不返 None/不跳过
    assert end == "2026-09-18"
    assert skipped is True
    assert end != "2026-09-19"  # 确认回退了


def test_resolve_end_date_falls_back_then_continues(monkeypatch):
    """回退后 end_date 供后续刷新用——前一天 bars 仍会补上（不 return 0）。"""
    from tools.refresh_kline_cache import _resolve_refresh_end_date

    fetch_fn = lambda code, start, end: []
    monkeypatch.setattr("vr_paths.prev_trading_date_str", lambda: "2026-09-18")

    end, skipped = _resolve_refresh_end_date("2026-09-19", fetch_fn)

    # end_date 非 None 非 empty → main 会继续刷新（不跳过整轮）
    assert end is not None
    assert end != ""
