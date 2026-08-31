# -*- coding: utf-8 -*-
"""S123 R4：backtest hit-rate degraded 诚实化测试。

钉死 _calc_next_day_return_meta 的 (float, fetch_ok) 语义 + win_rate 路径排除
!fetch_ok 出 hit_rate 分母 + _calc_next_day_return 向后兼容返 float。

对齐仓内 _meta sibling 范式（_calculate_concentration_risk_meta risk_models.py:488）。
零外呼（mock astock.kline / kline_from_mootdx / snapshot_store / wsr）。
"""
from __future__ import annotations

from datetime import date, timedelta
from types import SimpleNamespace

import pytest

import backtest_lite as bt
from routers.win_rate import _shadow_comparison_impl
from win_rate_tracker import WinRateTracker, WinRateRecord


@pytest.fixture
def tmp_tracker(tmp_path) -> WinRateTracker:
    return WinRateTracker(db_path=str(tmp_path / "winrate.db"))


def _fake_bar(date: str, close: float):
    return SimpleNamespace(date=date, close=close)


# ── R4.6 ① _calc_next_day_return_meta 四态 ──────────────────────────────────


class TestCalcNextDayReturnMeta:
    """_meta 返 (float, bool)：成功→(ret, True)；失败→(0.0, False)。"""

    def test_success_returns_real_return_and_true(self, monkeypatch):
        """有 bars + 日期命中 → (ret, True)，ret 为真实收益率。"""
        bars = (_fake_bar("2026-08-06", 10.0), _fake_bar("2026-08-07", 10.5))
        monkeypatch.setattr(bt.astock, "kline", lambda code, category=4, offset=5: {"raw": code})
        monkeypatch.setattr(bt, "kline_from_mootdx", lambda code, raw: SimpleNamespace(bars=bars))

        ret, fetch_ok = bt._calc_next_day_return_meta("600519", "2026-08-06")
        assert fetch_ok is True
        assert ret == pytest.approx(0.05)  # (10.5-10)/10

    def test_no_bars_returns_zero_and_false(self, monkeypatch):
        """无 bars → (0.0, False)。"""
        monkeypatch.setattr(bt.astock, "kline", lambda code, category=4, offset=5: {"raw": code})
        monkeypatch.setattr(bt, "kline_from_mootdx", lambda code, raw: SimpleNamespace(bars=()))

        ret, fetch_ok = bt._calc_next_day_return_meta("600519", "2026-08-06")
        assert fetch_ok is False
        assert ret == 0.0

    def test_date_not_found_returns_zero_and_false(self, monkeypatch):
        """日期未命中 → (0.0, False)。"""
        bars = (_fake_bar("2026-08-06", 10.0), _fake_bar("2026-08-07", 11.0))
        monkeypatch.setattr(bt.astock, "kline", lambda code, category=4, offset=5: {"raw": code})
        monkeypatch.setattr(bt, "kline_from_mootdx", lambda code, raw: SimpleNamespace(bars=bars))

        ret, fetch_ok = bt._calc_next_day_return_meta("600519", "2026-09-01")  # 不在 bars 中
        assert fetch_ok is False
        assert ret == 0.0

    def test_exception_returns_zero_and_false(self, monkeypatch):
        """astock.kline 抛异常 → (0.0, False) + logger.warning（不裸 except:pass）。"""
        def boom(*a, **k):
            raise RuntimeError("network down")
        monkeypatch.setattr(bt.astock, "kline", boom)

        ret, fetch_ok = bt._calc_next_day_return_meta("600519", "2026-08-06")
        assert fetch_ok is False
        assert ret == 0.0


# ── R4.6 ② win_rate 路径 !fetch_ok 排除出 hit_rate 分母 ─────────────────────

_D1 = (date.today() - timedelta(days=1)).strftime("%Y-%m-%d")


def _add(tracker: WinRateTracker, code: str, entry_date: str, signal_source: str,
         is_win: bool, return_pct: float, strategy: str = "first_plate"):
    tracker.add_record(WinRateRecord(
        stock_code=code, stock_name=code, strategy_used=strategy,
        entry_date=entry_date, entry_price=10.0,
        exit_date=entry_date, exit_price=11.0 if is_win else 9.5,
        return_pct=return_pct, is_win=is_win, gene_score=60.0, sti_label="", sector="",
        signal_source=signal_source,
    ))


def test_degraded_excluded_from_hitrate_denominator(tmp_tracker, monkeypatch):
    """win_rate 路径 !fetch_ok 样本排除出 hit_rate 分母 + missing_kline 计数。

    场景：4 只 missed codes
    - A 600001: (0.05, True)  → win，进分母
    - B 600002: (-0.03, True) → miss，进分母
    - C 600003: (0.0, False)  → degraded，排除出分母，计 missing_kline
    - D 600004: (0.0, True)   → 真 0%，进分母（miss）——旧逻辑会误排为 missing

    hit_rate = 1 / (1+2) = 0.3333（不含 C）；missing_kline = 1（仅 C）。
    """
    _add(tmp_tracker, "600519", _D1, "funnel_candidate", True, 10.0)

    # 4 只候选，1 只 holding，3 只 missed → 但我们放 4 只候选让 4 只都 missed
    snap = {"final_candidates": [
        {"code": "600001"}, {"code": "600002"},
        {"code": "600003"}, {"code": "600004"},
    ]}
    monkeypatch.setattr("snapshot_store.list_snapshot_dates", lambda: [_D1])
    monkeypatch.setattr("snapshot_store.load_snapshot", lambda d: snap)
    monkeypatch.setattr("workflow_state_repo.list_states", lambda d: [])  # 无 holding，全 missed

    returns_map = {
        "600001": (0.05, True),    # win
        "600002": (-0.03, True),   # miss
        "600003": (0.0, False),    # degraded — 排除
        "600004": (0.0, True),     # 真 0% — 进分母（miss，非 missing_kline）
    }
    monkeypatch.setattr("backtest_lite._calc_next_day_return_meta",
                        lambda code, d, cache=None: returns_map.get(code, (0.0, False)))

    result = _shadow_comparison_impl(28, tmp_tracker)
    missed = result["missed"]

    # C 排除：n = 3（A/B/D），不含 C
    assert missed["n"] == 3
    # hit_rate = 1 win / 3 total = 0.3333（C 不进分母）
    assert missed["win_rate"] == round(1 / 3, 4)
    # missing_kline = 1（仅 C，D 不计——D 是 fetch_ok=True 的真 0%）
    assert missed["missing_kline"] == 1


# ── R4.6 ③ _calc_next_day_return 向后兼容返 float ───────────────────────────


def test_calc_next_day_return_backward_compat_float(monkeypatch):
    """_calc_next_day_return 仍返 float（0.0 on failure），不返 tuple。

    既有 5+ 直调方（run_backtest_async / backfill_winrate_samples / test mock）不破。
    """
    # 异常路径 → 0.0（float，非 tuple）
    def boom(*a, **k):
        raise RuntimeError("down")
    monkeypatch.setattr(bt.astock, "kline", boom)
    result = bt._calc_next_day_return("600519", "2026-08-06")
    assert isinstance(result, float)
    assert result == 0.0

    # 无 bars 路径 → 0.0（float）
    monkeypatch.setattr(bt.astock, "kline", lambda code, category=4, offset=5: {"raw": code})
    monkeypatch.setattr(bt, "kline_from_mootdx", lambda code, raw: SimpleNamespace(bars=()))
    result2 = bt._calc_next_day_return("600519", "2026-08-06")
    assert isinstance(result2, float)
    assert result2 == 0.0

    # 成功路径 → 真实收益率（float）
    bars = (_fake_bar("2026-08-06", 10.0), _fake_bar("2026-08-07", 11.0))
    monkeypatch.setattr(bt, "kline_from_mootdx", lambda code, raw: SimpleNamespace(bars=bars))
    result3 = bt._calc_next_day_return("600519", "2026-08-06")
    assert isinstance(result3, float)
    assert result3 == pytest.approx(0.1)
