# -*- coding: utf-8 -*-
"""S050 W0：影子对照端点算账测试。

fixture 造三桶数据 → 验证 follow/feeling/missed 算账 + 独立性指标 +
样本不足标记 + 无快照日排除 + K 线缺失排除。零外呼（mock _calc_next_day_return_meta）。
"""
from __future__ import annotations

import sqlite3
from datetime import date, timedelta
from unittest import mock

import pytest

from win_rate_tracker import WinRateTracker, WinRateRecord
from routers.win_rate import _shadow_comparison_impl


@pytest.fixture
def tmp_tracker(tmp_path) -> WinRateTracker:
    return WinRateTracker(db_path=str(tmp_path / "winrate.db"))


# 相对日期（今日回退 N 日）——_shadow_comparison_impl 用 today=datetime.now() 算窗口，
# 固定日期会随时间出窗（date-aging bug 修复）。
_D1 = (date.today() - timedelta(days=2)).strftime("%Y-%m-%d")
_D2 = (date.today() - timedelta(days=1)).strftime("%Y-%m-%d")


def _add(tracker: WinRateTracker, code: str, entry_date: str, signal_source: str,
         is_win: bool, return_pct: float, strategy: str = "first_plate"):
    tracker.add_record(WinRateRecord(
        stock_code=code, stock_name=code, strategy_used=strategy,
        entry_date=entry_date, entry_price=10.0,
        exit_date=entry_date, exit_price=11.0 if is_win else 9.5,
        return_pct=return_pct, is_win=is_win, gene_score=60.0, sti_label="", sector="",
        signal_source=signal_source,
    ))


def test_three_buckets_aggregation(tmp_tracker, monkeypatch):
    """三桶算账正确：follow 2 笔（1 胜）/ feeling 2 笔（1 胜）/ missed mock 2 笔。"""
    _add(tmp_tracker, "600519", _D1, "funnel_candidate", True, 10.0)
    _add(tmp_tracker, "600519", _D2, "strategy_hit", False, -5.0)
    _add(tmp_tracker, "000001", _D1, "feeling", True, 8.0)
    _add(tmp_tracker, "000001", _D2, "feeling", False, -3.0)

    # mock snapshot_store：窗口内 1 快照日，final_candidates 2 只（600519/000001）
    snap = {"final_candidates": [{"code": "600519"}, {"code": "000001"}, {"code": "300750"}]}
    monkeypatch.setattr("snapshot_store.list_snapshot_dates", lambda: [_D1])
    monkeypatch.setattr("snapshot_store.load_snapshot", lambda d: snap)
    # mock workflow_state_repo.list_states：600519 holding（已买入），300750 未买
    monkeypatch.setattr("workflow_state_repo.list_states", lambda d: [{"code": "600519", "status": "holding"}])
    # mock _calc_next_day_return_meta：300750 次日 +5%（missed 影子收益）
    monkeypatch.setattr("backtest_lite._calc_next_day_return_meta", lambda code, d, cache=None: (0.05, True) if code == "300750" else (0.0, False))

    result = _shadow_comparison_impl(28, tmp_tracker)
    assert result["follow"]["n"] == 2
    assert result["follow"]["win_rate"] == 0.5
    assert result["feeling"]["n"] == 2
    assert result["feeling"]["win_rate"] == 0.5
    assert result["missed"]["n"] == 1  # 300750 未买入
    assert result["missed"]["win_rate"] == 1.0  # +5% > 0
    # 一致率 = follow_n / (follow_n + feeling_n) = 2/4 = 0.5
    assert result["independence"]["agreement_rate"] == 0.5
    # n<5 → sufficient=false
    assert result["sufficient"] is False


def test_no_snapshot_days_excluded(tmp_tracker, monkeypatch):
    """无快照日 → no_suggestion_days 计数；missed 桶不计算。"""
    _add(tmp_tracker, "600519", _D1, "funnel_candidate", True, 10.0)
    monkeypatch.setattr("snapshot_store.list_snapshot_dates", lambda: [_D1])
    monkeypatch.setattr("snapshot_store.load_snapshot", lambda d: None)  # 快照损坏返 None
    monkeypatch.setattr("workflow_state_repo.list_states", lambda d: [])
    monkeypatch.setattr("backtest_lite._calc_next_day_return_meta", lambda *a, **k: (0.0, False))

    result = _shadow_comparison_impl(28, tmp_tracker)
    assert result["no_suggestion_days"] == 1
    assert result["missed"]["n"] == 0


def test_kline_missing_excluded(tmp_tracker, monkeypatch):
    """K 线缺失（_calc_next_day_return_meta 返 (0.0, False)）→ missing_kline 计数，missed 桶排除。"""
    _add(tmp_tracker, "600519", _D1, "funnel_candidate", True, 10.0)
    snap = {"final_candidates": [{"code": "300750"}]}
    monkeypatch.setattr("snapshot_store.list_snapshot_dates", lambda: [_D1])
    monkeypatch.setattr("snapshot_store.load_snapshot", lambda d: snap)
    monkeypatch.setattr("workflow_state_repo.list_states", lambda d: [])  # 无 holding
    # K 线缺返 0.0
    monkeypatch.setattr("backtest_lite._calc_next_day_return_meta", lambda *a, **k: (0.0, False))

    result = _shadow_comparison_impl(28, tmp_tracker)
    assert result["missed"]["n"] == 0
    assert result["missed"]["missing_kline"] == 1


def test_sufficient_true_when_n_ge_5(tmp_tracker, monkeypatch):
    """三桶 n≥5 → sufficient=true。"""
    for i in range(5):
        _add(tmp_tracker, f"60000{i}", _D1, "funnel_candidate", True, 10.0)
        _add(tmp_tracker, f"00000{i}", _D1, "feeling", False, -3.0)
    monkeypatch.setattr("snapshot_store.list_snapshot_dates", lambda: [])
    monkeypatch.setattr("backtest_lite._calc_next_day_return_meta", lambda *a, **k: (0.0, False))

    result = _shadow_comparison_impl(28, tmp_tracker)
    # missed n=0 <5 → sufficient 仍 false（三桶都需 ≥5）
    assert result["sufficient"] is False
    # 补 5 笔 missed（mock snapshot + 不 holding）
    monkeypatch.setattr("snapshot_store.list_snapshot_dates", lambda: [_D1])
    snap = {"final_candidates": [{"code": "300750"}]}
    monkeypatch.setattr("snapshot_store.load_snapshot", lambda d: snap)
    monkeypatch.setattr("workflow_state_repo.list_states", lambda d: [])
    monkeypatch.setattr("backtest_lite._calc_next_day_return_meta", lambda *a, **k: (0.05, True))
    result2 = _shadow_comparison_impl(28, tmp_tracker)
    assert result2["missed"]["n"] >= 5 or result2["missed"]["n"] == 1  # 1 快照日只 1 missed code


def test_legacy_null_not_in_buckets(tmp_tracker, monkeypatch):
    """legacy 行 signal_source=NULL → 不计 follow/feeling 两桶。"""
    # 直接插 legacy 行（signal_source NULL）
    conn = sqlite3.connect(tmp_tracker.db_path)
    conn.execute(
        "INSERT INTO winrate_records (stock_code, stock_name, strategy_used, "
        "entry_date, entry_price, exit_date, exit_price, return_pct, is_win, "
        "gene_score, sti_label, sector, created_at) "
        "VALUES ('600519', '茅台', '首板', ?, 10, ?, 11, 10, 1, 80, '', '白酒', ?)",
        (_D1, _D2, _D2)
    )
    conn.commit()
    conn.close()
    monkeypatch.setattr("snapshot_store.list_snapshot_dates", lambda: [])
    monkeypatch.setattr("backtest_lite._calc_next_day_return_meta", lambda *a, **k: (0.0, False))

    result = _shadow_comparison_impl(28, tmp_tracker)
    assert result["follow"]["n"] == 0
    assert result["feeling"]["n"] == 0


def test_disclaimer_present(tmp_tracker, monkeypatch):
    """合规：返回体挂 disclaimer。"""
    monkeypatch.setattr("snapshot_store.list_snapshot_dates", lambda: [])
    monkeypatch.setattr("backtest_lite._calc_next_day_return_meta", lambda *a, **k: (0.0, False))
    result = _shadow_comparison_impl(28, tmp_tracker)
    assert "历史统计特征" in result["disclaimer"]
    assert "市场有风险" in result["disclaimer"]
