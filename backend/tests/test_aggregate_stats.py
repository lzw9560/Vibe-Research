# -*- coding: utf-8 -*-
"""S173 aggregate_stats 测试——统计方法论层（H1/H2）。

覆盖验收标准：
  H1 净超额走 day_clustered_t_test + CI
  H1 4 臂多重检验走 bonferroni_bh（K cap 8）
  H2 Sharpe 先日聚合再 ×sqrt252 或 compute_dsr 出 DSR+MinTRL
  H4 underpowered gate（n<30 或 days<60 → exploratory 不 kill）
  H8 coverage_rate + execution_winrate + unbuyable 三指标
  A3 跨臂聚合产出 + is_dead_arm=1 不混入 + underpowered 不 kill
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

backend_dir = Path(__file__).resolve().parent.parent
if str(backend_dir) not in sys.path:
    sys.path.insert(0, str(backend_dir))

from engine.trade_journal import (  # noqa: E402
    TradeJournal,
    JournalRecord,
    _wilson_ci,
    _daily_aggregate_sharpe,
    _compute_arm_stats,
    MIN_PICKS_FOR_KILL,
    MIN_DAYS_FOR_KILL,
)

# s44_verifier 统计函数
from s44_verifier.stats import day_clustered_t_test, bonferroni_bh  # noqa: E402
from s44_verifier.wiring import compute_dsr, compute_haircut  # noqa: E402


@pytest.fixture
def tj(tmp_path):
    return TradeJournal(db_path=tmp_path / "test_aggregate.db")


def _make_records(n: int, arm: str = "breakout", win_rate: float = 0.6) -> list[JournalRecord]:
    """生成 n 条 realized records，胜率 win_rate。"""
    records = []
    for i in range(n):
        is_win = (i / n) < win_rate
        pnl = 50.0 if is_win else -40.0
        day = f"2026-01-{(i % 28) + 1:02d}"
        records.append(JournalRecord.create(
            arm=arm, stock_code=f"00{i:04d}",
            entry_price=10.0, entry_date=f"2026-01-{(i % 28) + 1:02d}",
            exit_date=day, exit_reason="take" if is_win else "stop",
            net_pnl=pnl, is_realized=1,
        ))
    return records


class TestDayClusteredTTest:
    """H1：净超额走 day_clustered_t_test。"""

    def test_day_clustered_prevents_n_inflation(self):
        """1000 picks across 14 days → effective n ~14（非 1000）。"""
        import random
        random.seed(42)
        returns = [random.gauss(0.001, 0.02) for _ in range(1000)]
        dates = [f"2026-01-{(i % 14) + 1:02d}" for i in range(1000)]
        result = day_clustered_t_test(returns, dates)
        assert result is not None
        assert result.n_days == 14  # 非 1000
        assert 0 <= result.p_one_sided <= 1.0

    def test_day_clustered_n_below_2_returns_none(self):
        """n_days < 2 → None。"""
        result = day_clustered_t_test([0.01], ["2026-01-01"])
        assert result is None


class TestBonferroniBH:
    """H1：4 臂多重检验走 bonferroni_bh。"""

    def test_bh_correction_multiple_p_values(self):
        """4 个 p_values → BH adjusted。"""
        p_vals = [0.01, 0.04, 0.03, 0.10]
        adjusted = bonferroni_bh(p_vals, n=4, method="BH")
        assert len(adjusted) == 4
        # BH adjusted >= raw p
        for raw, adj in zip(p_vals, adjusted):
            assert adj >= raw

    def test_bonferroni_k_cap_8(self):
        """K cap 8（§44v2，不 K=20）。"""
        p_vals = [0.01] * 20
        adjusted = bonferroni_bh(p_vals, n=20, method="bonferroni")
        # bonferroni: p * min(K, 8) = 0.01 * 8 = 0.08
        assert all(a == 0.08 for a in adjusted)


class TestComputeDSR:
    """H2：Sharpe 走 compute_dsr 出 DSR+MinTRL。"""

    def test_dsr_returns_tuple(self):
        """compute_dsr 返 (dsr, method, min_trl)。"""
        import numpy as np
        returns = np.array([0.01, -0.005, 0.008, 0.002, -0.003, 0.015], dtype=float)
        dsr, method, min_trl = compute_dsr(returns, n_trials=4)
        assert isinstance(dsr, float) or dsr is None
        assert method in ("cross_trial_variance", "lenient_single_estimate", "N/A")

    def test_dsr_empty_returns_none(self):
        """空/单元素 → None。"""
        import numpy as np
        dsr, method, _ = compute_dsr(np.array([0.01]), n_trials=4)
        assert dsr is None
        assert method == "N/A"


class TestComputeHaircut:
    """H1：Sharpe haircut。"""

    def test_haircut_returns_float_or_none(self):
        """compute_haircut 返 float 或 None。"""
        import numpy as np
        returns = np.array([0.01, -0.005, 0.008, 0.002], dtype=float)
        h = compute_haircut(returns, n_obs=4, n_tests=1, method="bonferroni")
        assert h is None or isinstance(h, float)


class TestWilsonCI:
    """H1：胜率 Wilson CI。"""

    def test_wilson_ci_contains_true_rate(self):
        """CI 含真实胜率。"""
        wins, total = 15, 20
        lo, hi = _wilson_ci(wins, total)
        true_rate = wins / total  # 0.75
        assert lo <= true_rate <= hi

    def test_wilson_ci_total_zero(self):
        lo, hi = _wilson_ci(0, 0)
        assert lo == 0.0 and hi == 1.0  # S183: n=0 返 (0,1) 宽带诚实暴露无数据


class TestDailyAggregateSharpe:
    """H2：先日聚合再 ×sqrt252。"""

    def test_groups_by_date_then_annualizes(self):
        pnls = [100.0, 200.0, -50.0, 75.0]
        dates = ["2026-01-16", "2026-01-16", "2026-01-17", "2026-01-17"]
        result = _daily_aggregate_sharpe(pnls, dates)
        assert result["n_days"] == 2
        # daily sums: day1=300, day2=25
        assert result["daily_mean"] == (300.0 + 25.0) / 2
        # Sharpe = mean/std * sqrt(252)
        assert result["sharpe"] is not None

    def test_single_day_no_sharpe(self):
        """1 day → std undefined → sharpe=None。"""
        result = _daily_aggregate_sharpe([100.0, 50.0], ["2026-01-16"])
        assert result["sharpe"] is None
        assert result["n_days"] == 1


class TestUnderpoweredGate:
    """H4：n<30 或 days<60 → underpowered 不出 kill。"""

    def test_n_picks_below_30_underpowered(self):
        records = _make_records(10)
        stats = _compute_arm_stats(records)
        assert stats["status"] == "underpowered"
        assert stats["n_picks"] < MIN_PICKS_FOR_KILL

    def test_n_picks_above_30_enforced(self):
        records = _make_records(35)
        stats = _compute_arm_stats(records)
        # 35 picks across ~28 days → n_days likely < 60 → still underpowered
        # But n_picks >= 30, so depends on n_days
        # Let's verify the logic: status is underpowered if n_picks<30 OR n_days<60
        # 35 picks → n_picks>=30; but n_days<60 → underpowered
        assert stats["status"] == "underpowered"  # because days<60

    def test_dead_arm_excluded_from_aggregate(self, tj):
        """is_dead_arm=1 不混入聚合。"""
        for i in range(5):
            tj.insert(JournalRecord.create(
                arm="breakout", stock_code=f"A{i}",
                entry_price=10.0, entry_date="2026-01-15",
                exit_date="2026-01-16", exit_reason="take",
                net_pnl=50.0, is_realized=1, is_dead_arm=0,
            ))
        tj.insert(JournalRecord.create(
            arm="gap", stock_code="X",
            entry_price=10.0, entry_date="2026-01-15",
            exit_date="2026-01-16", exit_reason="signal",
            net_pnl=-100.0, is_realized=1, is_dead_arm=1,
        ))
        agg = tj.aggregate_by_arm()
        assert "breakout" in agg
        assert "gap" not in agg


class TestCoverageRate:
    """H8：coverage_rate + execution_winrate + unbuyable 三指标。"""

    def test_three_metrics_produced(self, tj):
        tj.insert(JournalRecord.create(
            arm="breakout", stock_code="A",
            entry_price=10.0, entry_date="2026-01-15",
            exit_date="2026-01-16", exit_reason="take",
            net_pnl=50.0, is_realized=1,
        ))
        tj.insert(JournalRecord.create(
            arm="breakout", stock_code="B",
            entry_price=10.0, entry_date="2026-01-15",
            exit_date="2026-01-16", exit_reason="stop",
            net_pnl=-40.0, is_realized=1,
        ))
        tj.insert(JournalRecord.create(
            arm="breakout", stock_code="C",
            entry_price=None, entry_date="2026-01-15",
            exit_reason="unbuyable", is_realized=1,
        ))
        agg = tj.aggregate_by_arm()
        stats = agg["breakout"]
        assert "signal_coverage_rate" in stats
        assert "execution_winrate" in stats
        assert "n_unbuyable" in stats
        assert stats["signal_coverage_rate"] == pytest.approx(2/3, abs=0.01)  # 2 buyable / 3 total
        assert stats["execution_winrate"] == 0.5  # 1 win / 2 decided
        assert stats["n_unbuyable"] == 1
