# -*- coding: utf-8 -*-
"""S175 T6 — P0 e2e 集成验收（spec grill SH3：A1/A2 可复现）。

mock bars_provider（A股 mock bars + ETF 512890 mock bars 含 open/high/low/close 延伸到
T+2+max_hold），跑 run_daily(target_date=T-1)，断言：
  A1: trade_journal.db 有 floor 512890 记录（unrealized_pnl 非 None，_latest_close target_date
      过滤无前视）+ breakout is_realized=1 记录（net_pnl 非 None，exit_price != entry_price）
  A2: aggregate_by_arm('breakout') 非 empty（n_picks>0）+ floor aggregate 恒 empty by design
      （floor 永远 is_realized=0）+ floor MTM 非 None

离线 mock，不走 akshare/不读真 cache。
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
from strategies.journal_recorder import JournalRecorder  # noqa: E402


# A股 breakout bars：signal 01-15, entry 01-16 (open=10.5), max_hold=3 → exit 01-19 close=10.7
STOCK_BARS = [
    {"date": "2026-01-15", "open": 10.0, "high": 10.5, "low": 9.5, "close": 10.0, "volume": 10000},
    {"date": "2026-01-16", "open": 10.5, "high": 10.6, "low": 10.4, "close": 10.55, "volume": 10000},  # entry=10.5
    {"date": "2026-01-17", "open": 10.55, "high": 10.7, "low": 10.45, "close": 10.6, "volume": 10000},  # 无触发
    {"date": "2026-01-18", "open": 10.6, "high": 10.8, "low": 10.5, "close": 10.65, "volume": 10000},
    {"date": "2026-01-19", "open": 10.65, "high": 10.9, "low": 10.55, "close": 10.7, "volume": 10000},  # max_hold exit
]
# ETF 512890 bars：signal 01-15, entry 01-16 (open=1.05)；净值口径 open=high=low，close 略不同
ETF_BARS = [
    {"date": "2026-01-15", "open": 1.00, "high": 1.00, "low": 1.00, "close": 1.10, "volume": 10000},  # signal close=1.10
    {"date": "2026-01-16", "open": 1.05, "high": 1.05, "low": 1.05, "close": 1.06, "volume": 10000},  # entry=1.05
    {"date": "2026-01-17", "open": 1.06, "high": 1.06, "low": 1.06, "close": 1.07, "volume": 10000},
    {"date": "2026-01-18", "open": 1.07, "high": 1.07, "low": 1.07, "close": 1.08, "volume": 10000},
    {"date": "2026-01-19", "open": 1.08, "high": 1.08, "low": 1.08, "close": 1.09, "volume": 10000},
]


@pytest.fixture
def e2e_recorder(tmp_path):
    """JournalRecorder with mock bars_provider（A股 000001 → STOCK_BARS, ETF 512890 → ETF_BARS）。"""
    journal = TradeJournal(db_path=tmp_path / "test_s175_e2e.db")

    def mock_bars_provider(code):
        if code == "000001":
            return STOCK_BARS
        if code == "512890":
            return ETF_BARS
        return []

    return JournalRecorder(
        journal=journal,
        executor=Executor(),
        bars_provider=mock_bars_provider,
    )


class TestS175E2E:
    """P0 e2e：run_daily 闭环跑通（A1/A2 验收）。"""

    def test_a1_floor_and_breakout_records(self, e2e_recorder):
        """A1: run_daily 后 trade_journal 有 floor 512890 + breakout is_realized=1。"""
        from strategies.premarket_selection import PreMarketCandidate

        candidate = PreMarketCandidate(
            code="000001", name="平安银行",
            breakout_score=0.95, breakout_binary=1,
            t1_close=10.0, t1_date="2026-01-15",
        )
        batch = [{"batch_idx": 0, "date": "2026-01-15", "amount": 100000, "status": "planned"}]

        with patch("strategies.premarket_selection.select_premarket_candidates",
                   return_value=[candidate]):
            with patch("strategies.index_replication_floor.build_position_batches",
                       return_value=batch):
                result = e2e_recorder.run_daily(target_date="2026-01-15", arms=["floor", "breakout"])

        # floor 臂：512890 记录，is_realized=0（hold），unrealized_pnl 非 None
        floor_records = e2e_recorder._journal.query_records(arm="floor", is_realized=None, is_dead_arm=0)
        assert len(floor_records) == 1
        assert floor_records[0].stock_code == "512890"
        assert floor_records[0].is_realized == 0  # floor 永远 hold（C3）
        assert floor_records[0].exit_reason == "hold"
        assert floor_records[0].unrealized_pnl is not None  # _latest_close target_date 过滤无前视

        # breakout 臂：is_realized=1（path_return 完成，max_hold exit），net_pnl 非 None，exit_price != entry
        breakout_records = e2e_recorder._journal.query_records(arm="breakout", is_realized=None, is_dead_arm=0)
        assert len(breakout_records) == 1
        assert breakout_records[0].is_realized == 1
        assert breakout_records[0].net_pnl is not None
        assert breakout_records[0].exit_price is not None
        assert breakout_records[0].exit_price != breakout_records[0].entry_price  # SH7 fix
        assert breakout_records[0].exit_reason == "max_hold"
        assert breakout_records[0].exit_price == pytest.approx(10.7, abs=0.01)  # bars[4].close
        assert breakout_records[0].entry_price == pytest.approx(10.5, abs=0.01)  # bars[1].open

    def test_a2_aggregate_breakout_nonempty_floor_empty_by_design(self, e2e_recorder):
        """A2: aggregate('breakout') 非 empty（n_picks>0）；floor aggregate 恒 empty by design。"""
        from strategies.premarket_selection import PreMarketCandidate

        candidate = PreMarketCandidate(
            code="000001", name="平安银行",
            breakout_score=0.95, breakout_binary=1,
            t1_close=10.0, t1_date="2026-01-15",
        )
        batch = [{"batch_idx": 0, "date": "2026-01-15", "amount": 100000, "status": "planned"}]

        with patch("strategies.premarket_selection.select_premarket_candidates",
                   return_value=[candidate]):
            with patch("strategies.index_replication_floor.build_position_batches",
                       return_value=batch):
                e2e_recorder.run_daily(target_date="2026-01-15", arms=["floor", "breakout"])

        aggregate = e2e_recorder._journal.aggregate_by_arm()
        # breakout 臂有 stats（is_realized=1 记录 → n_picks>0）
        assert "breakout" in aggregate
        assert aggregate["breakout"]["n_picks"] > 0
        # floor 臂 aggregate 恒 empty by design（floor 永远 is_realized=0，aggregate 查 is_realized=1）
        floor_stats = aggregate.get("floor", {})
        assert floor_stats.get("status") == "empty" or floor_stats.get("n_picks", 0) == 0

    def test_a2_floor_mtm_non_none(self, e2e_recorder):
        """A2 补充：floor MTM（unrealized_pnl）非 None，独立于 winrate aggregate。"""
        batch = [{"batch_idx": 0, "date": "2026-01-15", "amount": 100000, "status": "planned"}]
        with patch("strategies.index_replication_floor.build_position_batches",
                   return_value=batch):
            e2e_recorder.run_daily(target_date="2026-01-15", arms=["floor"])

        floor_records = e2e_recorder._journal.query_records(arm="floor", is_realized=None, is_dead_arm=0)
        assert len(floor_records) == 1
        assert floor_records[0].unrealized_pnl is not None  # MTM 非 None
        # ETF 01-15 close=1.10, entry=01-16 open=1.05 → unrealized=(1.10-1.05)*100=5.0
        assert floor_records[0].unrealized_pnl == pytest.approx(5.0, abs=0.5)

    def test_settle_pending_runs_at_run_daily_start(self, e2e_recorder):
        """run_daily 开头调 settle_pending_breakout（R3，即使无 hold 也不崩）。"""
        with patch.object(e2e_recorder, "settle_pending_breakout",
                          return_value={"n_pending": 0, "n_settled": 0}) as mock_settle:
            with patch.object(e2e_recorder, "_process_floor", return_value={"n_candidates": 0}):
                with patch.object(e2e_recorder, "_process_breakout", return_value={"n_candidates": 0}):
                    e2e_recorder.run_daily(target_date="2026-01-15", arms=["floor", "breakout"])
        mock_settle.assert_called_once()  # run_daily 开头调 settle_pending
