# -*- coding: utf-8 -*-
"""真实数据链路单测（S023 C4）：last_trading_date + 采集失败标记。"""

from __future__ import annotations

from datetime import date
from unittest.mock import patch

from candidate_funnel import funnel, sources
from candidate_funnel.models import ThresholdConfig
from vr_paths import is_trading_day, last_trading_date, last_trading_date_str


# ---------- last_trading_date ----------


def test_is_trading_day_weekday():
    # 2026-08-03 是周一
    assert is_trading_day(date(2026, 8, 3)) is True


def test_is_trading_day_weekend():
    # 2026-08-01 是周六
    assert is_trading_day(date(2026, 8, 1)) is False
    # 2026-08-02 是周日
    assert is_trading_day(date(2026, 8, 2)) is False


def test_is_trading_day_holiday():
    # 2026-10-01 国庆
    assert is_trading_day(date(2026, 10, 1)) is False


def test_last_trading_date_on_trading_day_returns_itself():
    d = date(2026, 8, 3)  # 周一
    assert last_trading_date(d) == d


def test_last_trading_date_on_weekend_returns_friday():
    # 2026-08-02 周日 → 回退到 2026-07-31 周五
    assert last_trading_date(date(2026, 8, 2)) == date(2026, 7, 31)


def test_last_trading_date_str_format():
    s = last_trading_date_str(date(2026, 8, 2))
    assert s == "2026-07-31"


# ---------- 采集失败标记 data_status ----------


def _make_cfg():
    return ThresholdConfig(mode="manual")


def test_r1_source_failure_marks_data_status():
    """gene.fetch_genes 抛异常 → R1 层标 data_status=未取得。"""
    with patch("candidate_funnel.funnel.sources.gene.fetch_genes", side_effect=RuntimeError("连不上")):
        with patch("candidate_funnel.funnel.sources.board_ladder.fetch_board_ladder", return_value={}):
            result = funnel.run_funnel("all", "2026-08-01", _make_cfg())
    r1 = next(l for l in result.layers if l.layer_id == "R1")
    assert r1.data_status == "未取得"
    assert "连不上" in (r1.data_reason or "")


def test_r2_source_failure_marks_data_status():
    """activity.fetch_activity 抛异常 → R2 层标 data_status=未取得。"""
    with patch("candidate_funnel.funnel.sources.gene.fetch_genes", return_value={"600519": {"name": "茅台"}}):
        with patch("candidate_funnel.funnel.sources.board_ladder.fetch_board_ladder", return_value={}):
            with patch("candidate_funnel.funnel.sources.activity.fetch_activity", side_effect=RuntimeError("超时")):
                with patch("candidate_funnel.funnel.sources.fund_flow.fetch_fund_flow", return_value={}):
                    result = funnel.run_funnel("all", "2026-08-01", _make_cfg())
    r2 = next(l for l in result.layers if l.layer_id == "R2")
    assert r2.data_status == "未取得"
    assert "超时" in (r2.data_reason or "")


def test_normal_run_no_data_status():
    """正常采集时 layer.data_status 为 None。"""
    with patch("candidate_funnel.funnel.sources.gene.fetch_genes", return_value={}):
        with patch("candidate_funnel.funnel.sources.board_ladder.fetch_board_ladder", return_value={}):
            with patch("candidate_funnel.funnel.sources.activity.fetch_activity", return_value={}):
                with patch("candidate_funnel.funnel.sources.fund_flow.fetch_fund_flow", return_value={}):
                    with patch("candidate_funnel.funnel.sources.auction.fetch_auction", return_value={}):
                        with patch("candidate_funnel.funnel.sources.catalyst.fetch_catalyst", return_value={}):
                            with patch("candidate_funnel.funnel.sources.watchlist_in.get_watchlist_codes", return_value=[]):
                                result = funnel.run_funnel("all", "2026-08-01", _make_cfg())
    for layer in result.layers:
        assert layer.data_status is None  # 采集到 0 个 ≠ 采集失败
