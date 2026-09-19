# -*- coding: utf-8 -*-
"""S218 daily_report / keypoint_notify run_date 默认值测试。

bug（2026-09-20 v3 审查发现）：daily_report cron 04:01（盘前）跑时用
``datetime.now()``（今天 09-19），但 regime cache 只到 09-18（前一交易日）→
``compute_regime_labels().get("09-19")`` → None → regime="unknown" → 全信号
"exploratory"，0 tradable。signal_report 显示 regime="unknown" 而实际 09-18
regime="range"。

fix：默认 run_date 改 ``prev_trading_date_str()``（前一已收盘交易日）→ cache 有
该日期 → regime 判对（range/bull/bear 非 unknown）。
"""
from __future__ import annotations

from datetime import datetime
from unittest.mock import MagicMock


def _mock_signals(target_date: str) -> dict:
    """get_consecutive_relay_signals 的最小 mock 返回值。"""
    return {
        "date": target_date,
        "arm": "consecutive_relay",
        "regime": {"current": "range"},
        "cap": {"effective": 0.5},
        "signals": [],
    }


def test_daily_report_default_run_date_uses_prev_trading_date(monkeypatch):
    """daily_report 不传 run_date → 默认前一交易日（盘前 cron 用昨天已收盘日，非今天）。

    bug：原 ``datetime.now()`` 在 04:01 盘前返今天，cache 只到昨天 → regime=unknown。
    fix：``prev_trading_date_str()`` 返前一已收盘交易日 → cache 有数据 → regime 判对。
    """
    # Arrange
    from scheduler.executors.signals import daily_report
    from vr_paths import prev_trading_date_str

    captured: dict = {}

    def _spy(target_date, *a, **kw):
        captured["target_date"] = target_date
        return _mock_signals(target_date)

    monkeypatch.setattr("scheduler.executors.signals.get_consecutive_relay_signals", _spy)
    monkeypatch.setattr("scheduler.executors.signals.render_daily_report", lambda s: "mock report")
    monkeypatch.setattr("scheduler.executors.signals._save_signal_record", lambda s: None)

    # Act — 不传 run_date，走默认值
    daily_report({})

    # Assert
    expected = prev_trading_date_str()
    assert captured["target_date"] == expected
    # 确保不是今天（盘前跑时 today 的 cache 还没数据）
    assert captured["target_date"] != datetime.now().strftime("%Y-%m-%d")


def test_daily_report_explicit_run_date_overrides_default(monkeypatch):
    """传 run_date → 用传入值，不走默认。"""
    from scheduler.executors.signals import daily_report

    captured: dict = {}

    def _spy(target_date, *a, **kw):
        captured["target_date"] = target_date
        return _mock_signals(target_date)

    monkeypatch.setattr("scheduler.executors.signals.get_consecutive_relay_signals", _spy)
    monkeypatch.setattr("scheduler.executors.signals.render_daily_report", lambda s: "mock report")
    monkeypatch.setattr("scheduler.executors.signals._save_signal_record", lambda s: None)

    daily_report({"run_date": "2026-09-18"})

    assert captured["target_date"] == "2026-09-18"


def test_keypoint_notify_default_run_date_uses_prev_trading_date(monkeypatch):
    """keypoint_notify 不传 run_date → 默认前一交易日（同 daily_report bug）。"""
    from scheduler.executors.signals import keypoint_notify
    import vr_paths

    captured: dict = {}

    def _spy(target_date, *a, **kw):
        captured["target_date"] = target_date
        return _mock_signals(target_date)

    monkeypatch.setattr("scheduler.executors.signals.get_consecutive_relay_signals", _spy)
    monkeypatch.setattr("scheduler.executors.signals.render_daily_report", lambda s: "mock report")
    # keypoint_notify 不调 _save_signal_record（它用自己的 _SIGNAL_DIR 写法）
    import scheduler.executors.signals as sig_mod
    monkeypatch.setattr(sig_mod, "_SIGNAL_DIR", __import__("pathlib").Path("/tmp/test_signal_dir_mock"))
    monkeypatch.setattr(sig_mod, "_render_d_close_entry", lambda s: "mock")
    monkeypatch.setattr(sig_mod, "_render_d1_open_exit", lambda s: "mock")
    monkeypatch.setattr(sig_mod, "_render_gapdown_honest_label", lambda s: "mock")
    # 防 polluter + 周日跑：mock signals.prev_trading_date_str（signals 顶部 from import
    # 绑定，mock vr_paths 不影响 signals 已绑定——须 mock signals 命名空间覆盖 polluter）
    monkeypatch.setattr("scheduler.executors.signals.prev_trading_date_str", lambda d=None: "2026-09-18")

    keypoint_notify({})

    assert captured["target_date"] == "2026-09-18"
    assert captured["target_date"] != datetime.now().strftime("%Y-%m-%d")
