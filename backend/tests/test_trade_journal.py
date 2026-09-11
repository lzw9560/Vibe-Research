# -*- coding: utf-8 -*-
"""S173 Trade Journal 闭环 ledger 测试。

覆盖验收标准：
  R1 trade_journal 表（schema + 迁移幂等 + CRUD）
  R3 跨臂聚合（is_dead_arm 不混入 + aggregate_by_arm）
  R6 诚实标注（is_realized / unrealized / is_dead_arm）
  C6 floor MTM（unrealized_pnl 每日更新）
  C7 winrate.db 隔离（trade_journal 独立写入）
  H8 coverage_rate 三指标
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
    PNL_UNIT_CNY,
)


@pytest.fixture
def tj(tmp_path):
    """隔离的 trade_journal DB（tmp_path，不污染生产 .vibe-research/）。"""
    return TradeJournal(db_path=tmp_path / "test_trade_journal.db")


class TestMigration:
    """R1 迁移幂等（memory migration-stubs-fresh-db-fix：v1 完整 CREATE 不做桩）。"""

    def test_fresh_db_creates_table_idempotent(self, tj):
        """fresh DB 建表幂等（跑 2 次不报错）。"""
        # 第一次建表（__init__ 已调 _ensure_table）
        records = tj.query_records(is_dead_arm=None)
        assert records == []

        # 第二次建表（幂等）
        tj._ensure_table()
        records = tj.query_records(is_dead_arm=None)
        assert records == []

    def test_table_schema_columns(self, tj):
        """schema 列 == spec §5.2。"""
        import sqlite3
        conn = sqlite3.connect(str(tj._db_path))
        cols = {r[1] for r in conn.execute("PRAGMA table_info(trade_journal)").fetchall()}
        conn.close()
        expected = {
            "signal_id", "arm", "stock_code", "entry_price", "entry_date",
            "exit_price", "exit_date", "exit_reason", "net_pnl", "pnl_unit",
            "cost_pct", "gross_return", "is_realized", "unrealized_pnl",
            "is_dead_arm", "fills_json", "created_at",
        }
        assert cols == expected

    def test_indexes_exist(self, tj):
        """2 个 index 存在。"""
        import sqlite3
        conn = sqlite3.connect(str(tj._db_path))
        indexes = {r[1] for r in conn.execute(
            "SELECT * FROM sqlite_master WHERE type='index' AND tbl_name='trade_journal'"
        ).fetchall()}
        conn.close()
        assert "idx_tj_arm" in indexes
        assert "idx_tj_entry_date" in indexes


class TestCRUD:
    """R1 CRUD。"""

    def test_insert_returns_signal_id(self, tj):
        """insert → 返 signal_id（UUID 格式）。"""
        record = JournalRecord.create(
            arm="breakout", stock_code="000001",
            entry_price=10.0, entry_date="2026-01-15",
            net_pnl=50.0, is_realized=1,
        )
        sid = tj.insert(record)
        assert sid == record.signal_id
        # S183: signal_id 改确定性（arm_date_code，len 26 非 UUID 36）

    def test_insert_then_query_roundtrip(self, tj):
        """insert → query 往返一致。"""
        record = JournalRecord.create(
            arm="breakout", stock_code="600000",
            entry_price=10.5, entry_date="2026-01-15",
            exit_price=11.0, exit_date="2026-01-18",
            exit_reason="take", net_pnl=35.0,
            cost_pct=0.75, gross_return=8.0, is_realized=1,
        )
        tj.insert(record)
        result = tj.query_records(arm="breakout", is_dead_arm=None)
        assert len(result) == 1
        assert result[0].arm == "breakout"
        assert result[0].stock_code == "600000"
        assert result[0].entry_price == 10.5
        assert result[0].net_pnl == 35.0
        assert result[0].exit_reason == "take"

    def test_update_unrealized_changes_pnl_only(self, tj):
        """update_unrealized 改 unrealized_pnl 不改其他字段（C6）。"""
        record = JournalRecord.create(
            arm="floor", stock_code="510300",
            entry_price=4.0, entry_date="2026-01-15",
            exit_reason="hold", is_realized=0,
            unrealized_pnl=0.0,
        )
        sid = tj.insert(record)
        # 更新 unrealized
        ok = tj.update_unrealized(sid, 25.0, 4.25)
        assert ok
        result = tj.query_records(arm="floor", is_dead_arm=None)
        assert len(result) == 1
        assert result[0].unrealized_pnl == 25.0
        assert result[0].entry_price == 4.0  # 其他字段不变
        assert result[0].exit_reason == "hold"

    def test_query_filters_dead_arm(self, tj):
        """is_dead_arm=1 不在默认 query 中（is_dead_arm 默认 0）。"""
        alive = JournalRecord.create(
            arm="breakout", stock_code="000001",
            entry_price=10.0, entry_date="2026-01-15",
            net_pnl=50.0, is_realized=1, is_dead_arm=0,
        )
        dead = JournalRecord.create(
            arm="gap", stock_code="mock_gap",
            entry_price=10.0, entry_date="2026-01-15",
            net_pnl=-5.0, is_realized=1, is_dead_arm=1,
        )
        tj.insert(alive)
        tj.insert(dead)

        # 默认只查存活臂
        result = tj.query_records(is_dead_arm=0)
        arms = {r.arm for r in result}
        assert "breakout" in arms
        assert "gap" not in arms

        # 查全部（含 dead_arm）
        all_records = tj.query_records(is_dead_arm=None)
        all_arms = {r.arm for r in all_records}
        assert "gap" in all_arms


class TestEquityCurve:
    """C4/C6 equity 曲线含 unrealized MTM。"""

    def test_equity_includes_unrealized(self, tj):
        """floor 持仓 unrealized_pnl 进 equity（A10）。"""
        # realized trade
        tj.insert(JournalRecord.create(
            arm="breakout", stock_code="000001",
            entry_price=10.0, entry_date="2026-01-15",
            exit_date="2026-01-18", exit_reason="take",
            net_pnl=100.0, is_realized=1,
        ))
        # unrealized floor
        tj.insert(JournalRecord.create(
            arm="floor", stock_code="510300",
            entry_price=4.0, entry_date="2026-01-15",
            exit_reason="hold", is_realized=0,
            unrealized_pnl=50.0,
        ))

        curve = tj.equity_curve()
        assert len(curve) >= 2
        # equity = initial_capital + 100 + 50 = 100150
        last = curve[-1]
        assert last["cum_pnl"] == 150.0
        assert last["equity"] == 100150.0

    def test_drawdown_cny_absolute(self, tj):
        """C4：drawdown = peak - current（绝对 CNY 非 (peak-current)/peak）。"""
        tj.insert(JournalRecord.create(
            arm="breakout", stock_code="A",
            entry_price=10.0, entry_date="2026-01-15",
            exit_date="2026-01-16", exit_reason="take",
            net_pnl=200.0, is_realized=1,
        ))
        tj.insert(JournalRecord.create(
            arm="breakout", stock_code="B",
            entry_price=10.0, entry_date="2026-01-17",
            exit_date="2026-01-18", exit_reason="stop",
            net_pnl=-100.0, is_realized=1,
        ))
        curve = tj.equity_curve()
        # peak cum = 200, then -100 → cum=100, drawdown=100
        assert curve[-1]["cum_pnl"] == 100.0
        assert curve[-1]["drawdown_cny"] == 100.0


class TestAggregate:
    """R3 跨臂聚合 + H8 coverage_rate。"""

    def test_dead_arm_not_in_aggregate(self, tj):
        """is_dead_arm=1 不混入聚合胜率。"""
        for i in range(10):
            tj.insert(JournalRecord.create(
                arm="breakout", stock_code=f"00{i:04d}",
                entry_price=10.0, entry_date="2026-01-15",
                exit_date="2026-01-16", exit_reason="take",
                net_pnl=50.0, is_realized=1, is_dead_arm=0,
            ))
        tj.insert(JournalRecord.create(
            arm="gap", stock_code="mock",
            entry_price=10.0, entry_date="2026-01-15",
            exit_date="2026-01-16", exit_reason="signal",
            net_pnl=-100.0, is_realized=1, is_dead_arm=1,
        ))

        agg = tj.aggregate_by_arm()
        assert "breakout" in agg
        assert "gap" not in agg  # dead_arm 不混入

    def test_coverage_rate_three_metrics(self, tj):
        """H8：coverage_rate + execution_winrate + unbuyable 三指标。"""
        # 3 buyable (2 win 1 loss) + 1 unbuyable
        tj.insert(JournalRecord.create(
            arm="breakout", stock_code="A",
            entry_price=10.0, entry_date="2026-01-15",
            exit_date="2026-01-16", exit_reason="take",
            net_pnl=50.0, is_realized=1,
        ))
        tj.insert(JournalRecord.create(
            arm="breakout", stock_code="B",
            entry_price=10.0, entry_date="2026-01-15",
            exit_date="2026-01-16", exit_reason="take",
            net_pnl=30.0, is_realized=1,
        ))
        tj.insert(JournalRecord.create(
            arm="breakout", stock_code="C",
            entry_price=10.0, entry_date="2026-01-15",
            exit_date="2026-01-16", exit_reason="stop",
            net_pnl=-20.0, is_realized=1,
        ))
        tj.insert(JournalRecord.create(
            arm="breakout", stock_code="D",
            entry_price=None, entry_date="2026-01-15",
            exit_reason="unbuyable", is_realized=1,
        ))

        agg = tj.aggregate_by_arm()
        stats = agg["breakout"]
        assert stats["n_picks"] == 3          # buyable
        assert stats["n_unbuyable"] == 1     # unbuyable
        assert stats["signal_coverage_rate"] == 0.75  # 3 buyable / 4 total
        assert stats["execution_winrate"] == pytest.approx(2/3, abs=0.01)  # 2 wins / 3 decided

    def test_underpowered_gate_n_below_30(self, tj):
        """H1/H4：n<30 → status='underpowered' 不出 kill。"""
        for i in range(5):
            tj.insert(JournalRecord.create(
                arm="breakout", stock_code=f"00{i:04d}",
                entry_price=10.0, entry_date="2026-01-15",
                exit_date="2026-01-16", exit_reason="take",
                net_pnl=50.0, is_realized=1,
            ))
        agg = tj.aggregate_by_arm()
        assert agg["breakout"]["status"] == "underpowered"


class TestStatsHelpers:
    """统计方法论层单测。"""

    def test_wilson_ci_empty_input(self):
        """空输入不崩。"""
        lo, hi = _wilson_ci(0, 0)
        assert lo == 0.0 and hi == 1.0  # S183: n=0 返 (0,1) 宽带诚实暴露无数据

    def test_wilson_ci_known_values(self):
        """10 wins / 20 total → CI 含 0.5。"""
        lo, hi = _wilson_ci(10, 20)
        assert 0.27 < lo < 0.32
        assert 0.68 < hi < 0.73

    def test_daily_aggregate_sharpe_groups_by_date(self):
        """H2：先日聚合再 ×sqrt252。"""
        # 2 trades same date + 1 trade different date → 2 daily points
        pnls = [100.0, 50.0, -30.0]
        dates = ["2026-01-16", "2026-01-16", "2026-01-17"]
        result = _daily_aggregate_sharpe(pnls, dates)
        assert result["n_days"] == 2  # 2 unique dates
        assert result["daily_mean"] == (150.0 + (-30.0)) / 2  # mean of daily sums

    def test_daily_aggregate_sharpe_empty(self):
        """空输入不崩。"""
        result = _daily_aggregate_sharpe([], [])
        assert result["sharpe"] is None
        assert result["n_days"] == 0


class TestS44VerdictAndDormantStubs:
    """S175 T9 — aggregate_by_arm 加 s44_verdict + dormant 臂 stub（limitup/trend）。"""

    def test_aggregate_emits_s44_verdict_per_arm(self, tmp_path):
        tj = TradeJournal(db_path=tmp_path / "s44.db")
        tj.insert(JournalRecord.create(
            arm="floor", stock_code="512890", entry_price=1.0, entry_date="2026-01-15",
            net_pnl=10.0, is_realized=1,
        ))
        tj.insert(JournalRecord.create(
            arm="breakout", stock_code="000001", entry_price=10.0, entry_date="2026-01-15",
            net_pnl=5.0, is_realized=1,
        ))
        agg = tj.aggregate_by_arm()
        # 存活臂带 s44_verdict（诚实标签）
        assert agg["floor"]["s44_verdict"] == "externally_validated"
        assert agg["breakout"]["s44_verdict"] == "§44_falsified"
        # dormant 臂 stub（limitup 无记录 → 显式 dormant stub；trend S181 升级实臂 exploratory 不 dormant）
        assert "limitup" in agg
        assert agg["limitup"]["s44_verdict"] == "mock_not_ready"
        assert agg["limitup"]["dormant"] is True
        assert agg["limitup"]["n_picks"] == 0

    def test_gap_dead_arm_not_in_aggregate(self, tmp_path):
        """gap 是 dead_arm（is_dead_arm=1 记录），不进 aggregate（防污染存活臂统计）——非 dormant stub。"""
        tj = TradeJournal(db_path=tmp_path / "gap.db")
        tj.insert(JournalRecord.create(
            arm="gap", stock_code="mock_gap", entry_price=10.0, entry_date="2026-01-15",
            net_pnl=1.3, is_realized=1, is_dead_arm=1,
        ))
        agg = tj.aggregate_by_arm()
        assert "gap" not in agg  # dead_arm 排除，不作为 dormant stub

    def test_dormant_stub_uses_empty_stats_shape(self, tmp_path):
        """dormant 臂 stub = _compute_arm_stats([]) shape + s44_verdict + dormant。"""
        tj = TradeJournal(db_path=tmp_path / "stub.db")
        agg = tj.aggregate_by_arm()
        stub = agg["limitup"]
        assert stub["status"] == "empty"  # _compute_arm_stats([]) 返 empty
        assert stub["s44_verdict"] == "mock_not_ready"
        assert stub["dormant"] is True
        assert "dormant_note" in stub
