# -*- coding: utf-8 -*-
"""S218 /signals/status regime fallback 测试——today 休市/周末 null → 最后交易日 regime。

2026-09-20 诊断：/signals/status 返 regime current=null，但 signal_report 09-18
有 regime=range + 8 picks。根因：_signals_status 的 regime_map.get(today) 对周日
休市日期返 None（compute_regime_labels 只标交易日）。修：null 时 fallback 最后
有 label 的交易日 regime，对齐 signal_report，非 null 误导前端显示空。
"""
from __future__ import annotations

from datetime import datetime as _real_dt


def _patch_common(monkeypatch, regime_map, today_str):
    """Mock _signals_status 依赖：datetime.now→today_str,
    compute_regime_labels→regime_map, _regime_freshness, TradeJournal→None。"""
    from routers import signals as sig

    class _FakeDT:
        @staticmethod
        def now():
            y, m, d = today_str.split("-")
            return _real_dt(int(y), int(m), int(d))

    monkeypatch.setattr(sig, "datetime", _FakeDT)
    monkeypatch.setattr(sig, "compute_regime_labels", lambda: regime_map)
    monkeypatch.setattr(
        "tools.signal_report._regime_freshness",
        lambda: {"last_cache_date": "2026-09-18", "stale": False,
                 "days_since": 0, "n_dates": 5498},
    )

    class _FakeTJ:
        def query_arm_status(self, arm):
            return None

    monkeypatch.setattr(sig, "TradeJournal", _FakeTJ)


def test_regime_falls_back_to_last_trading_day_when_today_null(monkeypatch):
    """today 周日休市 → compute_regime_labels[today]=None → fallback 最后有 label 交易日。"""
    from routers import signals as sig
    _patch_common(monkeypatch,
                  regime_map={"2026-09-18": "range", "2026-09-20": None},
                  today_str="2026-09-20")
    result = sig._signals_status()
    assert result["regime"]["current"] == "range"  # fallback，非 null


def test_regime_uses_today_when_present(monkeypatch):
    """today 交易日有 label → 直接用，不 fallback。"""
    from routers import signals as sig
    _patch_common(monkeypatch,
                  regime_map={"2026-09-18": "bull", "2026-09-17": "range"},
                  today_str="2026-09-18")
    result = sig._signals_status()
    assert result["regime"]["current"] == "bull"


def test_regime_all_null_returns_none_honest(monkeypatch):
    """regime_map 全 None（edge case）→ regime null 诚实返（不臆造）。"""
    from routers import signals as sig
    _patch_common(monkeypatch,
                  regime_map={"2026-09-20": None, "2026-09-18": None},
                  today_str="2026-09-20")
    result = sig._signals_status()
    assert result["regime"]["current"] is None  # 全 null 不 fallback 臆造
