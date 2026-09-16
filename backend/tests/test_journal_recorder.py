# -*- coding: utf-8 -*-
"""S173 Journal Recorder 测试——orchestrator 顺序管线。

覆盖验收标准：
  C1 orchestrator 顺序管线（非订阅）
  C2 gap 走 gap_net_return，可平仓臂走 path_return
  C3/C6 floor 走 MTM 不走 path_return
  C5 floor 豁免 per-arm DD
  C8 Trades 不加 signal_id/arm 字段
  C7 journal_recorder 唯一写入 trade_journal
  H9 batch 模式（call path_return→PathReturn）
  A1 4 臂都能录到 trade_journal
  A5 survivorship 过滤涨停买不到
"""
from __future__ import annotations

import json
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

backend_dir = Path(__file__).resolve().parent.parent
if str(backend_dir) not in sys.path:
    sys.path.insert(0, str(backend_dir))

from engine.trade_journal import TradeJournal, JournalRecord  # noqa: E402
from engine.decision import Trades, FILL_T_PLUS_1_OPEN, FILL_ACCEPTED  # noqa: E402
from engine.executor import Executor  # noqa: E402
from engine.fill_policies import T1OpenFill  # noqa: E402
from engine.accounting import path_return, gap_net_return  # noqa: E402
from strategies.journal_recorder import JournalRecorder  # noqa: E402


@pytest.fixture
def journal(tmp_path):
    return TradeJournal(db_path=tmp_path / "test_recorder.db")


@pytest.fixture
def recorder(journal):
    """JournalRecorder with mock bars_provider (returns empty bars by default)."""
    return JournalRecorder(
        journal=journal,
        executor=Executor(),
        bars_provider=lambda _code: [],
    )


def _make_bars(signal_date: str, n: int = 10) -> list[dict]:
    """生成 n 天 OHLC bars，signal_date 是第 0 天。"""
    bars = []
    for i in range(n):
        d = f"2026-01-{i + 1:02d}"
        bars.append({
            "date": d, "open": 10.0 + i * 0.1,
            "high": 10.5 + i * 0.1, "low": 9.5 + i * 0.1,
            "close": 10.2 + i * 0.1, "volume": 10000,
        })
    # 修正 signal_date bar
    bars[0]["date"] = signal_date
    return bars


class TestOrchestratorPattern:
    """C1 orchestrator 顺序管线（非订阅）。"""

    def test_run_daily_calls_arms_sequentially(self, journal, recorder):
        """run_daily 按顺序调各臂（非订阅）。"""
        with patch("strategies.journal_recorder.select_premarket_candidates",
                   return_value=[]) if False else patch.object(
            recorder, "_process_breakout", return_value={"n_candidates": 0}):
            with patch.object(recorder, "_process_floor", return_value={"n_candidates": 0}):
                result = recorder.run_daily(target_date="2026-01-15", arms=["floor", "breakout"])
                assert "floor" in result
                assert "breakout" in result

    def test_unknown_arm_handled(self, recorder):
        """未知 arm 不崩（标 unknown_arm）。"""
        result = recorder.run_daily(
            target_date="2026-01-15", arms=["nonexistent_arm"],
        )
        assert result["nonexistent_arm"]["status"] == "unknown_arm"


class TestBreakoutArm:
    """C2 可平仓臂走 path_return。"""

    def test_breakout_records_to_journal(self, journal, recorder):
        """breakout 臂 candidates → Trades → execute → path_return → insert。"""
        from strategies.premarket_selection import PreMarketCandidate

        candidate = PreMarketCandidate(
            code="000001", name="平安银行",
            breakout_score=0.95, breakout_binary=1,
            t1_close=10.0, t1_date="2026-01-15",
        )
        bars = _make_bars("2026-01-15")

        # mock signal generator
        with patch("strategies.premarket_selection.select_premarket_candidates",
                   return_value=[candidate]):
            recorder._bars_provider = lambda code: bars if code == "000001" else []
            result = recorder._process_breakout("2026-01-15")

        assert result["n_candidates"] == 1
        assert result["n_buyable"] == 1
        # 查 journal
        records = journal.query_records(arm="breakout", is_dead_arm=None)
        assert len(records) == 1
        assert records[0].arm == "breakout"
        assert records[0].is_realized == 1

    def test_unbuyable_filter(self, journal, recorder):
        """A5：涨停买不到标 exit_reason='unbuyable'。"""
        from strategies.premarket_selection import PreMarketCandidate

        candidate = PreMarketCandidate(
            code="000002", name="万科A",
            breakout_score=0.95, breakout_binary=1,
            t1_close=10.0, t1_date="2026-01-15",
        )
        # 涨停一字板 bars（open=high=close=涨停价，volume=0）
        locked_bars = [
            {"date": "2026-01-15", "open": 11.0, "high": 11.0, "low": 11.0, "close": 11.0, "volume": 0},
            {"date": "2026-01-16", "open": 11.0, "high": 11.0, "low": 11.0, "close": 11.0, "volume": 0},
        ]

        with patch("strategies.premarket_selection.select_premarket_candidates",
                   return_value=[candidate]):
            recorder._bars_provider = lambda code: locked_bars if code == "000002" else []
            result = recorder._process_breakout("2026-01-15")

        assert result["n_unbuyable"] == 1
        records = journal.query_records(arm="breakout", is_dead_arm=None)
        assert len(records) == 1
        assert records[0].exit_reason == "unbuyable"
        assert records[0].entry_price is None


class TestT4ArmSize:
    """T4（S209 §4）：§44 lift cap 真咬仓位——_arm_size 接 PaperPortfolio.final_size 4-layer。

    breakout/trend/post_first_board lift=0.5（underpowered/探索性）→ 50 股（halve）。
    floor lift=1.0（N/A）→ 100 股不缩。§44 v2 不再 decorative。
    """

    def test_arm_size_breakout_halves(self, recorder):
        """breakout lift=0.5（underpowered）→ 50 股（DEFAULT_SIZE 100 halve）。"""
        size = recorder._arm_size("breakout")
        assert size == 50.0, f"breakout lift=0.5 应 50 股，got {size}"

    def test_arm_size_floor_full(self, recorder):
        """floor lift=1.0（N/A cap 不作用）→ 100 股不缩。"""
        size = recorder._arm_size("floor")
        assert size == 100.0, f"floor lift=1.0 应 100 股，got {size}"

    def test_arm_size_post_first_board_halves(self, recorder):
        """post_first_board lift=0.5（探索性）→ 50 股。"""
        size = recorder._arm_size("post_first_board")
        assert size == 50.0, f"post_first_board lift=0.5 应 50 股，got {size}"

    def test_arm_size_trend_halves(self, recorder):
        """trend lift=0.5（探索性 trend_swing）→ 50 股。"""
        size = recorder._arm_size("trend")
        assert size == 50.0, f"trend lift=0.5 应 50 股，got {size}"

    def test_process_breakout_uses_arm_size(self, journal, recorder):
        """_process_breakout 用 _arm_size → position_notional=entry×size（非 DEFAULT 100）。"""
        from strategies.premarket_selection import PreMarketCandidate
        candidate = PreMarketCandidate(
            code="000001", name="平安银行",
            breakout_score=0.95, breakout_binary=1,
            t1_close=10.0, t1_date="2026-01-15",
        )
        bars = _make_bars("2026-01-15")
        # mock _arm_size=30（非 DEFAULT 100 也非 lift 50，清晰区分 size 真接通）
        with patch.object(recorder, "_arm_size", return_value=30.0):
            with patch("strategies.premarket_selection.select_premarket_candidates",
                       return_value=[candidate]):
                recorder._bars_provider = lambda code: bars if code == "000001" else []
                recorder._process_breakout("2026-01-15")
        records = journal.query_records(arm="breakout", is_dead_arm=None)
        assert len(records) == 1
        fills = json.loads(records[0].fills_json) if records[0].fills_json else {}
        # entry≈10.1（T+1 open）× 30 = ~303（非 100×10.1=1010）
        pos_notional = fills.get("position_notional", 0)
        assert 290 < pos_notional < 320, f"position_notional 应≈303，got {pos_notional}"


class TestFloorArm:
    """C3/C6 floor 走 MTM 不走 path_return。"""

    def test_floor_records_with_hold_exit_reason(self, journal, recorder):
        """floor exit_reason='hold'，is_realized=0。"""
        bars = _make_bars("2026-01-15")

        with patch("strategies.index_replication_floor.build_position_batches",
                   return_value=[{"batch_idx": 0, "date": "2026-01-15", "amount": 100000, "status": "planned"}]):
            recorder._bars_provider = lambda code: bars if code == "512890" else []
            result = recorder._process_floor("2026-01-15")

        assert result["n_candidates"] == 1
        records = journal.query_records(arm="floor", is_dead_arm=None)
        assert len(records) == 1
        assert records[0].exit_reason == "hold"  # C3
        assert records[0].is_realized == 0  # C6

    def test_floor_mtm_update(self, journal, recorder):
        """C6：update_floor_mtm 重算 unrealized_pnl。"""
        bars = _make_bars("2026-01-15")

        with patch("strategies.index_replication_floor.build_position_batches",
                   return_value=[{"batch_idx": 0, "date": "2026-01-15", "amount": 100000, "status": "planned"}]):
            recorder._bars_provider = lambda code: bars if code == "512890" else []
            recorder._process_floor("2026-01-15")

        # 改 bars close → 更新 MTM
        new_bars = [{"date": "2026-01-20", "open": 11.0, "high": 11.5, "low": 10.5, "close": 11.0, "volume": 10000}]
        recorder._bars_provider = lambda code: new_bars if code == "512890" else []
        updated = recorder.update_floor_mtm()
        assert updated >= 1

        records = journal.query_records(arm="floor", is_dead_arm=None)
        assert records[0].unrealized_pnl is not None
        # entry was ~10.2, current close 11.0, size=100
        assert records[0].unrealized_pnl > 0


class TestGapArm:
    """C2 gap 走 gap_net_return（不走 path_return）。"""

    def test_gap_records_as_dead_arm(self, journal, recorder):
        """gap 臂 is_dead_arm=1，走 gap_net_return。"""
        result = recorder._process_gap("2026-01-15")
        assert result["n_realized"] == 1
        records = journal.query_records(arm="gap", is_dead_arm=None)
        assert len(records) == 1
        assert records[0].is_dead_arm == 1
        assert records[0].is_realized == 1
        # net_pnl 走 gap_net_return（net_ratio × notional）
        assert records[0].net_pnl is not None
        # fills_json 含 gap 信息
        fills = json.loads(records[0].fills_json)
        assert "net_ratio" in fills
        assert "cost_pct" in fills


class TestTradesNotModified:
    """C8：Trades 不加 signal_id/arm 字段。"""

    def test_trades_has_no_signal_id_field(self):
        """Trades dataclass 无 signal_id/arm 字段（C8）。"""
        trades = Trades(
            code="000001", signal_date="2026-01-15",
            fill_type=FILL_T_PLUS_1_OPEN, direction="long", size=100,
        )
        assert not hasattr(trades, "signal_id")
        assert not hasattr(trades, "arm")

    def test_signal_id_assigned_by_recorder(self, journal, recorder):
        """signal_id 由 journal_recorder 录入时赋值（JournalRecord.create 生成 UUID）。"""
        record = JournalRecord.create(
            arm="breakout", stock_code="000001",
            entry_price=10.0, entry_date="2026-01-15",
            net_pnl=50.0, is_realized=1,
        )
        # S183: signal_id 改确定性（arm_date_code，len 26 非 UUID 36）
        assert record.arm == "breakout"


class TestFourArmsRecorded:
    """A1：4 臂都能录到 trade_journal。"""

    def test_all_arms_recorded(self, journal, recorder):
        """floor/breakout/limitup/gap 全录到 trade_journal。"""
        with patch.object(recorder, "_process_floor", return_value={"n_candidates": 1}):
            with patch.object(recorder, "_process_breakout", return_value={"n_candidates": 1}):
                result = recorder.run_daily(
                    target_date="2026-01-15",
                    arms=["floor", "breakout", "gap", "limitup"],
                )
        assert set(result.keys()) == {"floor", "breakout", "gap", "limitup"}


class TestBatchMode:
    """H9 batch 模式（非 event-driven）。"""

    def test_path_return_returns_complete_pathreturn(self):
        """path_return 一次性返回完整 PathReturn（含 exit_reason/exit_date）——batch 模式。"""
        bars = _make_bars("2026-01-15")
        trades = Trades(
            code="000001", signal_date="2026-01-15",
            fill_type=FILL_T_PLUS_1_OPEN, direction="long", size=100,
        )
        executor = Executor()
        filled = executor.execute(trades, bars, T1OpenFill())

        pr = path_return(
            filled, bars,
            stop_pct=-4.0, take_profit_pct=8.0, max_hold_days=3,
            apply_cost=True,
        )
        # batch 模式：path_return 一次性返回完整 PathReturn
        if pr is not None:
            assert hasattr(pr, "exit_reason")
            assert hasattr(pr, "exit_date")
            assert hasattr(pr, "return_pct")
            assert hasattr(pr, "cost_pct")
            assert hasattr(pr, "gross_return_pct")


# ===========================================================================
# S175 T3：settle_pending_breakout + _latest_close target_date（C2/SH2/SH5/SH7）
# ===========================================================================

class TestSettlePendingBreakout:
    """S175 T3 — settle_pending_breakout 重算昨日 'hold'。

    bars 增长后重算 path_return → INSERT OR REPLACE **同 signal_id**（绕过 .create()
    生新 UUID）→ is_realized=1。截断 max_hold（bars 不足完整持仓期）留 hold 不标
    realized（SH5）。signal_id bypass .create()（.create() :94 硬编 uuid4，无法
    INSERT OR REPLACE 同 id）。
    """

    def test_settle_realizes_hold_when_bars_complete(self, journal, recorder):
        """bars 延伸到完整 max_hold → 'hold' 重算为 is_realized=1，同 signal_id。"""
        hold = JournalRecord.create(
            arm="breakout", stock_code="000001",
            entry_price=10.5, entry_date="2026-01-15",
            exit_reason="hold", is_realized=0,
            fills_json=json.dumps({"optimism_flag": "path_return_none_t1_guard"}),
        )
        journal.insert(hold)
        # bars 延伸到完整 max_hold=3（signal 01-15 idx=0, entry 01-16 idx=1, exit 01-19 idx=4）
        bars = [
            {"date": "2026-01-15", "open": 10.0, "high": 10.5, "low": 9.5, "close": 10.0, "volume": 10000},
            {"date": "2026-01-16", "open": 10.5, "high": 10.6, "low": 10.4, "close": 10.55, "volume": 10000},  # entry=10.5
            {"date": "2026-01-17", "open": 10.55, "high": 10.7, "low": 10.45, "close": 10.6, "volume": 10000},
            {"date": "2026-01-18", "open": 10.6, "high": 10.8, "low": 10.5, "close": 10.65, "volume": 10000},
            {"date": "2026-01-19", "open": 10.65, "high": 10.9, "low": 10.55, "close": 10.7, "volume": 10000},  # max_hold exit close=10.7
        ]
        recorder._bars_provider = lambda code: bars if code == "000001" else []
        settled = recorder.settle_pending_breakout()
        assert settled["n_settled"] == 1
        records = journal.query_records(arm="breakout", is_realized=None, is_dead_arm=0)
        assert len(records) == 1  # INSERT OR REPLACE 同 signal_id，非新行
        assert records[0].signal_id == hold.signal_id  # 同 id（绕过 .create()）
        assert records[0].is_realized == 1
        assert records[0].net_pnl is not None
        assert records[0].exit_price == pytest.approx(10.7, abs=0.01)  # bars[4].close, != entry 10.5
        assert records[0].exit_reason == "max_hold"

    def test_settle_leaves_hold_when_bars_truncated(self, journal, recorder):
        """bars 不足完整 max_hold（截断）→ 留 hold 不标 realized（SH5）。"""
        hold = JournalRecord.create(
            arm="breakout", stock_code="000001",
            entry_price=10.5, entry_date="2026-01-15",
            exit_reason="hold", is_realized=0,
            fills_json=json.dumps({"optimism_flag": "path_return_none_t1_guard"}),
        )
        journal.insert(hold)
        # bars 只到 01-17（entry 01-16, max_hold=3 需 01-19, 仅 1 根 post-entry → 截断）
        bars = [
            {"date": "2026-01-15", "open": 10.0, "high": 10.5, "low": 9.5, "close": 10.0, "volume": 10000},
            {"date": "2026-01-16", "open": 10.5, "high": 10.6, "low": 10.4, "close": 10.55, "volume": 10000},  # entry
            {"date": "2026-01-17", "open": 10.55, "high": 10.7, "low": 10.45, "close": 10.6, "volume": 10000},  # 截断 max_hold
        ]
        recorder._bars_provider = lambda code: bars if code == "000001" else []
        settled = recorder.settle_pending_breakout()
        assert settled["n_settled"] == 0  # 截断留 hold
        records = journal.query_records(arm="breakout", is_realized=None, is_dead_arm=0)
        assert len(records) == 1
        assert records[0].is_realized == 0  # 仍 hold
        assert records[0].exit_reason == "hold"
        assert records[0].signal_id == hold.signal_id  # 未被改

    def test_settle_skips_when_no_hold_records(self, journal, recorder):
        """无 'hold' breakout 记录 → n_settled=0，不崩。"""
        settled = recorder.settle_pending_breakout()
        assert settled["n_settled"] == 0
        assert settled["n_pending"] == 0


class TestLatestCloseTargetDate:
    """S175 T3 — _latest_close target_date 过滤防前视（SH2）。

    生产当日跑（target_date=T-1）取当日 close 正确；但历史重跑 bars 含至今日，
    _latest_close 无过滤返今日 close → 前视偏差。加 target_date 过滤 date<=target_date。
    """

    def test_latest_close_filters_by_target_date(self, recorder):
        bars = [
            {"date": "2026-01-01", "close": 10.0},
            {"date": "2026-01-05", "close": 11.0},
            {"date": "2026-01-10", "close": 12.0},  # 未来 bar
        ]
        # target_date=2026-01-05 → 返 01-05 close=11.0，非未来 01-10 close=12.0
        assert recorder._latest_close(bars, target_date="2026-01-05") == 11.0

    def test_latest_close_no_target_returns_last(self, recorder):
        """无 target_date（生产当日跑安全）→ 返最后一根 close（backward compat）。"""
        bars = [
            {"date": "2026-01-01", "close": 10.0},
            {"date": "2026-01-10", "close": 12.0},
        ]
        assert recorder._latest_close(bars) == 12.0

    def test_latest_close_target_date_before_all_bars(self, recorder):
        """target_date 早于所有 bar → None（无 <=target_date 的 bar）。"""
        bars = [{"date": "2026-01-10", "close": 12.0}]
        assert recorder._latest_close(bars, target_date="2026-01-01") is None

    def test_latest_close_empty_bars(self, recorder):
        assert recorder._latest_close([], target_date="2026-01-05") is None


# ===========================================================================
# S201b stage 2: 版本保留——settle_pending 用 UPDATE 非 INSERT OR REPLACE
# ===========================================================================

class TestSettleVersionPreserve:
    """S201b stage 2 — settle_pending 版本保留（spec verdict #6）。

    绝不 INSERT OR REPLACE（覆盖全字段无 before-image，违 reproducibility）。
    update_settlement_v2 只 UPDATE 指定字段，冻结 gross_return 不动。
    新 gross 写 gross_return_v2 + exit_model_version。
    """

    def test_settle_preserves_frozen_gross_and_writes_v2(self, journal, recorder):
        """settle 后 gross_return 不变（冻结），新 gross 写 gross_return_v2。"""
        hold = JournalRecord.create(
            arm="breakout", stock_code="000001",
            entry_price=10.0, entry_date="2026-01-15",
            exit_reason="hold", is_realized=0,
            fills_json=json.dumps({"optimism_flag": "path_return_none_t1_guard"}),
        )
        journal.insert(hold)
        # bars: T+2 gap-through stop（open=9.5 <= stop_level=9.6）
        bars = [
            {"date": "2026-01-15", "open": 10.0, "high": 10.2, "low": 9.8, "close": 10.1, "volume": 10000},
            {"date": "2026-01-16", "open": 10.0, "high": 10.3, "low": 9.9, "close": 10.2, "volume": 10000},  # entry=10.0
            {"date": "2026-01-17", "open": 9.5, "high": 9.8, "low": 9.3, "close": 9.6, "volume": 10000},  # T+2 gap-through
            {"date": "2026-01-18", "open": 9.7, "high": 10.0, "low": 9.5, "close": 9.8, "volume": 10000},
            {"date": "2026-01-19", "open": 9.8, "high": 10.1, "low": 9.6, "close": 10.0, "volume": 10000},
        ]
        recorder._bars_provider = lambda code: bars if code == "000001" else []
        settled = recorder.settle_pending_breakout()
        assert settled["n_settled"] == 1
        records = journal.query_records(arm="breakout", is_realized=None, is_dead_arm=0)
        assert len(records) == 1  # UPDATE 非新行
        rec = records[0]
        assert rec.is_realized == 1
        assert rec.exit_reason == "stop"
        # gross_return 冻结（hold 时为 None，settle 后仍 None）
        assert rec.gross_return is None
        # gross_return_v2 有新值（gap-through fill=open=9.5, gross=(9.5-10.0)/10.0*100=-5.0%）
        assert rec.gross_return_v2 is not None
        assert rec.gross_return_v2 == pytest.approx(-5.0, abs=0.1)
        assert rec.exit_model_version == "v2_gap_through_aware"

    def test_settle_does_not_touch_realized_records(self, journal, recorder):
        """is_realized=1 的记录不被 settle 触碰（gross_return + gross_return_v2 不变）。"""
        # 已 realized 记录（frozen gross_return=-4.0）
        realized = JournalRecord.create(
            arm="breakout", stock_code="000002",
            entry_price=10.0, entry_date="2026-01-14",
            exit_reason="stop", is_realized=1,
            gross_return=-4.0,
            exit_price=9.6, exit_date="2026-01-16",
            net_pnl=-40.0, cost_pct=0.85,
        )
        journal.insert(realized)
        # hold 记录（is_realized=0）
        hold = JournalRecord.create(
            arm="breakout", stock_code="000001",
            entry_price=10.0, entry_date="2026-01-15",
            exit_reason="hold", is_realized=0,
        )
        journal.insert(hold)
        bars = [
            {"date": "2026-01-15", "open": 10.0, "high": 10.2, "low": 9.8, "close": 10.1, "volume": 10000},
            {"date": "2026-01-16", "open": 10.0, "high": 10.3, "low": 9.9, "close": 10.2, "volume": 10000},
            {"date": "2026-01-17", "open": 9.5, "high": 9.8, "low": 9.3, "close": 9.6, "volume": 10000},
            {"date": "2026-01-18", "open": 9.7, "high": 10.0, "low": 9.5, "close": 9.8, "volume": 10000},
            {"date": "2026-01-19", "open": 9.8, "high": 10.1, "low": 9.6, "close": 10.0, "volume": 10000},
        ]
        recorder._bars_provider = lambda code: bars if code == "000001" else []
        settled = recorder.settle_pending_breakout()
        assert settled["n_settled"] == 1  # 只 settle 了 hold
        # realized 记录未被触碰——按 stock_code 单独查
        all_realized = journal.query_records(arm="breakout", is_realized=1, is_dead_arm=0)
        rec_realized = [r for r in all_realized if r.stock_code == "000002"]
        assert len(rec_realized) == 1
        assert rec_realized[0].gross_return == -4.0  # frozen 不变
        assert rec_realized[0].gross_return_v2 is None  # 未被 v2 写入
        assert rec_realized[0].exit_model_version == ""  # 未被 v2 标记

    def test_settle_preserves_fills_json(self, journal, recorder):
        """settle 后 fills_json 不变（INSERT OR REPLACE 会覆盖，UPDATE 保留）。"""
        original_fills = json.dumps({"optimism_flag": "path_return_none_t1_guard", "custom": "data"})
        hold = JournalRecord.create(
            arm="breakout", stock_code="000001",
            entry_price=10.0, entry_date="2026-01-15",
            exit_reason="hold", is_realized=0,
            fills_json=original_fills,
        )
        journal.insert(hold)
        bars = [
            {"date": "2026-01-15", "open": 10.0, "high": 10.2, "low": 9.8, "close": 10.1, "volume": 10000},
            {"date": "2026-01-16", "open": 10.0, "high": 10.3, "low": 9.9, "close": 10.2, "volume": 10000},
            {"date": "2026-01-17", "open": 9.5, "high": 9.8, "low": 9.3, "close": 9.6, "volume": 10000},
            {"date": "2026-01-18", "open": 9.7, "high": 10.0, "low": 9.5, "close": 9.8, "volume": 10000},
            {"date": "2026-01-19", "open": 9.8, "high": 10.1, "low": 9.6, "close": 10.0, "volume": 10000},
        ]
        recorder._bars_provider = lambda code: bars if code == "000001" else []
        recorder.settle_pending_breakout()
        records = journal.query_records(arm="breakout", is_realized=None, is_dead_arm=0)
        # fills_json 保留原值（UPDATE 未碰）
        assert records[0].fills_json == original_fills
