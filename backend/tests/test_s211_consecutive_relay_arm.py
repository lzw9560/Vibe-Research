# -*- coding: utf-8 -*-
"""S211 consecutive_relay arm 接线测试——overnight gap path + regime-stratified §44 cap。

TDD：test 先 RED → 实现 GREEN。覆盖：
  T1 evaluation: DIMENSION_LIFT_REGISTRY consecutive_relay + lift_for_arm regime 参数
  T2 paper_portfolio: final_size regime 参数
  T3 journal_recorder: _process_consecutive_relay overnight gap + D 日一字板 filter + regime cap bite
"""
import json
import sys
from pathlib import Path
from unittest.mock import patch

import pytest

backend_dir = Path(__file__).resolve().parent.parent
if str(backend_dir) not in sys.path:
    sys.path.insert(0, str(backend_dir))

from engine.trade_journal import TradeJournal  # noqa: E402
from engine.executor import Executor  # noqa: E402
from strategies.journal_recorder import JournalRecorder, DEFAULT_SIZE  # noqa: E402


@pytest.fixture
def journal(tmp_path):
    return TradeJournal(db_path=tmp_path / "test_s211.db")


@pytest.fixture
def recorder(journal):
    return JournalRecorder(
        journal=journal, executor=Executor(),
        bars_provider=lambda _code: [],
    )


def _make_gap_bars(signal_date: str = "2026-01-15") -> list[dict]:
    """2 天 bars: D=signal_date close=10.0, D+1 open=10.2（gap +2%, 非一字板）。"""
    return [
        {"date": signal_date, "open": 10.0, "high": 10.5, "low": 9.5,
         "close": 10.0, "volume": 10000, "pctChg": 0.5},
        {"date": "2026-01-16", "open": 10.2, "high": 10.8, "low": 9.8,
         "close": 10.5, "volume": 10000, "pctChg": 5.0},
    ]


# ── T1 evaluation: regime-stratified cap ─────────────────────────────────


class TestLiftForArmRegime:
    def test_registry_has_consecutive_relay(self):
        from candidate_funnel.evaluation import DIMENSION_LIFT_REGISTRY
        d = DIMENSION_LIFT_REGISTRY.get("consecutive_relay")
        assert d is not None, "consecutive_relay 应在 DIMENSION_LIFT_REGISTRY"
        assert hasattr(d, "regime_caps") and d.regime_caps is not None

    def test_lift_for_arm_consecutive_relay_bull(self):
        """bull regime ×1.0（2026-09-19 ×1.0 unlock——bear chrono cross-regime 三条件 MET）。"""
        from candidate_funnel.evaluation import lift_for_arm
        mult, _ = lift_for_arm("consecutive_relay", regime="bull")
        assert mult == 1.0, f"bull 应 ×1.0（×1.0 unlock）, got {mult}"

    def test_lift_for_arm_consecutive_relay_bear(self):
        """bear regime ×0.5（underpowered）。"""
        from candidate_funnel.evaluation import lift_for_arm
        mult, _ = lift_for_arm("consecutive_relay", regime="bear")
        assert mult == 0.5, f"bear 应 ×0.5, got {mult}"

    def test_lift_for_arm_consecutive_relay_range(self):
        """range regime ×0.5（underpowered）。"""
        from candidate_funnel.evaluation import lift_for_arm
        mult, _ = lift_for_arm("consecutive_relay", regime="range")
        assert mult == 0.5, f"range 应 ×0.5, got {mult}"

    def test_lift_for_arm_consecutive_relay_no_regime_conservative(self):
        """regime=None → 保守 ×0.5（bear/range underpowered 不误放全权重）。"""
        from candidate_funnel.evaluation import lift_for_arm
        mult, _ = lift_for_arm("consecutive_relay")
        assert mult == 0.5, f"regime=None 应保守 ×0.5, got {mult}"

    def test_lift_for_arm_backward_compat_no_regime(self):
        """regime 参数 default None — 旧 caller lift_for_arm('breakout') 仍 work。"""
        from candidate_funnel.evaluation import lift_for_arm
        mult, _ = lift_for_arm("breakout")  # 不传 regime
        assert mult == 0.5  # breakout days<60 → ×0.5 不变


# ── T2 paper_portfolio: final_size regime ────────────────────────────────


class TestFinalSizeRegime:
    def _make_pp(self, monkeypatch):
        from engine.paper_portfolio import PaperPortfolio
        pp = PaperPortfolio()
        monkeypatch.setattr(pp._breaker, "size_multiplier", lambda arm=None: (1.0, "ok"))
        monkeypatch.setattr(pp._breaker, "portfolio_multiplier", lambda: (1.0, "ok"))
        return pp

    def test_final_size_consecutive_relay_bull(self, tmp_path, monkeypatch):
        """bull regime ×1.0（2026-09-19 ×1.0 unlock）→ final_size = 10000×1.0=10000。"""
        pp = self._make_pp(monkeypatch)
        result = pp.final_size("consecutive_relay", 10000, regime="bull")
        assert result == 10000, f"bull ×1.0 应 10000, got {result}"

    def test_final_size_consecutive_relay_bear(self, tmp_path, monkeypatch):
        """bear regime ×0.5 → final_size halve。"""
        pp = self._make_pp(monkeypatch)
        result = pp.final_size("consecutive_relay", 10000, regime="bear")
        assert result == 5000, f"bear ×0.5 应 5000, got {result}"

    def test_final_size_consecutive_relay_no_regime(self, tmp_path, monkeypatch):
        """regime=None → 保守 ×0.5。"""
        pp = self._make_pp(monkeypatch)
        result = pp.final_size("consecutive_relay", 10000)
        assert result == 5000, f"regime=None 应保守 ×0.5=5000, got {result}"


# ── T3 journal_recorder: _process_consecutive_relay ─────────────────────


class TestProcessConsecutiveRelay:
    def test_overnight_gap_recorded(self, journal, recorder):
        """_process_consecutive_relay: D 收买入→D+1 开卖出, gap_net_return 记 net_pnl。"""
        bars = _make_gap_bars("2026-01-15")
        recorder._bars_provider = lambda code: bars if code == "000001" else []
        with patch("pre_limitup_scanner.scan_consecutive_relay",
                   return_value=[{"code": "000001", "lbc": 2}]):
            result = recorder._process_consecutive_relay("2026-01-15")
        assert result["n_realized"] == 1
        records = journal.query_records(arm="consecutive_relay", is_dead_arm=None)
        assert len(records) == 1
        r = records[0]
        assert r.is_realized == 1
        # entry=close[D]=10.0, exit=open[D+1]=10.2 → gap +2%
        assert r.entry_price == 10.0
        assert r.exit_price == 10.2
        fills = json.loads(r.fills_json) if r.fills_json else {}
        # net_pnl = net_ratio × position_notional（net_ratio~0.02-cost, notional~10×size）
        assert "net_ratio" in fills
        assert fills.get("arm_path") == "overnight_gap"

    def test_d_day_unbuyable_filter(self, journal, recorder):
        """D 日一字板（close 买不到）→ 'unbuyable' survivorship 过滤。"""
        # D 日一字板: open=high=low=close=10.5, pctChg=9.8%（涨停封死）
        bars = [
            {"date": "2026-01-15", "open": 10.5, "high": 10.5, "low": 10.5,
             "close": 10.5, "volume": 100, "pctChg": 9.8},
            {"date": "2026-01-16", "open": 10.6, "high": 10.8, "low": 9.8,
             "close": 10.5, "volume": 100, "pctChg": 0.95},
        ]
        recorder._bars_provider = lambda code: bars if code == "000001" else []
        with patch("pre_limitup_scanner.scan_consecutive_relay",
                   return_value=[{"code": "000001", "lbc": 2}]):
            recorder._process_consecutive_relay("2026-01-15")
        records = journal.query_records(arm="consecutive_relay", is_dead_arm=None)
        assert len(records) == 1
        assert records[0].exit_reason == "unbuyable"
        assert records[0].is_realized == 1

    def test_hold_when_d1_bar_missing(self, journal, recorder):
        """D+1 bar 缺（T+1 guard）→ 'hold' is_realized=0。"""
        bars = [{"date": "2026-01-15", "open": 10.0, "high": 10.5, "low": 9.5,
                 "close": 10.0, "volume": 100, "pctChg": 0.5}]  # 只 D 日, 无 D+1
        recorder._bars_provider = lambda code: bars if code == "000001" else []
        with patch("pre_limitup_scanner.scan_consecutive_relay",
                   return_value=[{"code": "000001", "lbc": 2}]):
            recorder._process_consecutive_relay("2026-01-15")
        records = journal.query_records(arm="consecutive_relay", is_dead_arm=None)
        assert len(records) == 1
        assert records[0].exit_reason == "hold"
        assert records[0].is_realized == 0

    def test_arm_size_consecutive_relay_bull_bite(self, recorder):
        """_arm_size('consecutive_relay', regime='bull') → 100 股（×1.0 2026-09-19 unlock）。"""
        size = recorder._arm_size("consecutive_relay", regime="bull")
        assert size == 100.0, f"bull ×1.0 应 100 股, got {size}"

    def test_arm_size_consecutive_relay_bear_bite(self, recorder):
        """_arm_size('consecutive_relay', regime='bear') → 50 股（×0.5）。"""
        size = recorder._arm_size("consecutive_relay", regime="bear")
        assert size == 50.0, f"bear ×0.5 应 50 股, got {size}"

    def test_arm_size_consecutive_relay_no_regime_conservative(self, recorder):
        """_arm_size('consecutive_relay') regime=None → 50 股（保守 ×0.5）。"""
        size = recorder._arm_size("consecutive_relay")
        assert size == 50.0, f"regime=None 应保守 ×0.5=50 股, got {size}"


class TestSettlePendingConsecutiveRelay:
    def test_settle_realizes_hold_when_d1_bar_arrives(self, journal, recorder):
        """settle_pending_consecutive_relay: D+1 bar 到达后 'hold'→realized。"""
        # 先建 hold（D+1 缺）
        bars_d_only = [{"date": "2026-01-15", "open": 10.0, "high": 10.5, "low": 9.5,
                        "close": 10.0, "volume": 100, "pctChg": 0.5}]
        recorder._bars_provider = lambda code: bars_d_only if code == "000001" else []
        with patch("pre_limitup_scanner.scan_consecutive_relay",
                   return_value=[{"code": "000001", "lbc": 2}]):
            recorder._process_consecutive_relay("2026-01-15")
        holds = journal.query_records(arm="consecutive_relay", is_realized=0, is_dead_arm=None)
        assert len(holds) == 1 and holds[0].exit_reason == "hold"

        # D+1 bar 到达
        bars_full = _make_gap_bars("2026-01-15")
        recorder._bars_provider = lambda code: bars_full if code == "000001" else []
        result = recorder.settle_pending_consecutive_relay()
        assert result["n_settled"] == 1
        realized = journal.query_records(arm="consecutive_relay", is_realized=1, is_dead_arm=None)
        assert len(realized) == 1
        assert realized[0].exit_price == 10.2  # open[D+1]


class TestRunDailyConsecutiveRelayWired:
    """S211 run_daily 接线——consecutive_relay arm active 生产验证。"""

    def test_run_daily_calls_process_consecutive_relay(self, recorder):
        """run_daily(arms=["consecutive_relay"]) 调 _process_consecutive_relay + result key。"""
        with patch.object(recorder, "_process_consecutive_relay",
                           return_value={"n_candidates": 1, "n_buyable": 1, "n_unbuyable": 0, "n_realized": 0}) as mock_process:
            with patch.object(recorder, "settle_pending_consecutive_relay"):
                result = recorder.run_daily(target_date="2026-01-15", arms=["consecutive_relay"])
        mock_process.assert_called_once_with("2026-01-15")
        assert "consecutive_relay" in result
        assert result["consecutive_relay"]["n_candidates"] == 1

    def test_default_arms_includes_consecutive_relay(self):
        """DEFAULT_ARMS 含 consecutive_relay（arm 默认生产 active）。"""
        from strategies.journal_recorder import DEFAULT_ARMS
        assert "consecutive_relay" in DEFAULT_ARMS
