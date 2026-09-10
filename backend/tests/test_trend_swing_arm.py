# -*- coding: utf-8 -*-
"""S181 趋势波段臂测试——signal generator + journal_recorder _process_trend/settle.

覆盖 tasks T1.1-T2.4：
  T1.1 _identify_trending_sectors：phase 筛 启动/发酵 + fund_flow 复合排序
  T1.2 select_trend_candidates：复用 build_non_limitup_candidates → ≤5 候选正确 shape
  T2.1a _process_trend realized：arm="trend", is_realized=1, net_pnl 非 None, cost_pct ≠0
  T2.1b settle_pending_trend：hold → bars 增长 → INSERT OR REPLACE 同 signal_id
  T2.1c 截断 max_hold：bars 不足完整持仓期留 hold
  T2.1d unbuyable：涨停 fillability_check 拒 → exit_reason="unbuyable"
"""
from __future__ import annotations

import json
import sys
from pathlib import Path
from unittest.mock import patch

import pytest

backend_dir = Path(__file__).resolve().parent.parent
if str(backend_dir) not in sys.path:
    sys.path.insert(0, str(backend_dir))

from engine.trade_journal import TradeJournal, JournalRecord  # noqa: E402
from engine.executor import Executor  # noqa: E402
from strategies.journal_recorder import JournalRecorder  # noqa: E402
from strategies.trend_swing_arm import (  # noqa: E402
    _identify_trending_sectors,
    select_trend_candidates,
    TREND_TOP_N,
)


@pytest.fixture
def journal(tmp_path):
    return TradeJournal(db_path=tmp_path / "test_trend.db")


@pytest.fixture
def recorder(journal):
    return JournalRecorder(
        journal=journal,
        executor=Executor(),
        bars_provider=lambda _code: [],
    )


# ── T1.1 _identify_trending_sectors ──────────────────────────────────────


class TestIdentifyTrendingSectors:
    """T1.1 — phase 筛 启动/发酵 + fund_flow 复合排序 → top sectors。"""

    def test_filters_phase_and_ranks_by_composite(self):
        """启动/发酵 通过，退潮/冷门 排除；fund_flow net>0 复合分更高排前。"""
        # Arrange: 4 sectors — 2 启动/发酵（通过）+ 2 退潮/冷门（排除）
        mock_sectors = [
            {"industry": "半导体", "zt_count_today": 5, "zt_momentum": 1.5},
            {"industry": "新能源", "zt_count_today": 3, "zt_momentum": 2.0},
            {"industry": "白酒", "zt_count_today": 2, "zt_momentum": -1.0},
            {"industry": "煤炭", "zt_count_today": 0, "zt_momentum": 0},
        ]
        # classify_phase side_effect 按调用顺序对应 4 个 sector
        phase_returns = [
            ("启动", 1.1, "板块可能加速"),   # 半导体 → 通过
            ("发酵", 1.0, "板块正常升温"),   # 新能源 → 通过
            ("退潮", 0.7, "追入即套"),        # 白酒 → 排除
            ("冷门", 0.8, "无板块支撑"),      # 煤炭 → 排除
        ]
        mock_fund_flow = [
            {"name": "半导体", "net": 5.0},    # net>0 → fund_weight=1.5
            {"name": "新能源", "net": -2.0},  # net<=0 → fund_weight=0.5
            {"name": "白酒", "net": 3.0},      # 被 phase 排除
        ]

        with patch("strategies.sector_cycle.aggregate_sectors",
                   return_value=mock_sectors), \
             patch("strategies.sector_cycle.classify_phase",
                   side_effect=phase_returns), \
             patch("market._sectors", return_value=mock_fund_flow):
            # Act
            result = _identify_trending_sectors("2026-01-15")

        # Assert: 只返 启动/发酵（2 个），退潮/冷门排除
        assert len(result) == 2
        industries = [s["industry"] for s in result]
        assert "半导体" in industries
        assert "新能源" in industries
        assert "白酒" not in industries
        assert "煤炭" not in industries
        # 半导体 composite > 新能源（fund_flow net>0 加分 vs net<=0 降权）
        semi = next(s for s in result if s["industry"] == "半导体")
        newe = next(s for s in result if s["industry"] == "新能源")
        assert semi["composite_score"] > newe["composite_score"]
        assert semi["phase"] == "启动"
        assert newe["phase"] == "发酵"
        # 排序正确（composite 降序）
        assert result[0]["industry"] == "半导体"
        assert result[1]["industry"] == "新能源"
        # rank 赋值
        assert result[0]["rank"] == 1
        assert result[1]["rank"] == 2


# ── T1.2 select_trend_candidates ─────────────────────────────────────────


class TestSelectTrendCandidates:
    """T1.2 — 复用 build_non_limitup_candidates → ≤5 候选正确 shape。"""

    def test_returns_candidates_with_correct_shape(self):
        """select_trend_candidates 返 ≤5 候选带 {code,name,sector,sector_rank,pattern,strategy_score}。"""
        # Arrange
        mock_top = [
            {"industry": "半导体", "phase": "启动", "modifier": 1.1,
             "zt_count_today": 5, "fund_flow_net": 5.0,
             "composite_score": 1.65, "phase_note": "加速", "rank": 1},
        ]
        mock_candidates = [
            {"code": "000001", "name": "平安银行", "sector": "半导体",
             "sector_rank": 1, "close": 10.0},
            {"code": "600519", "name": "贵州茅台", "sector": "半导体",
             "sector_rank": 2, "close": 1500.0},
        ]

        with patch("strategies.trend_swing_arm._identify_trending_sectors",
                   return_value=mock_top), \
             patch("strategies.pattern_scan.load_industry_map",
                   return_value={}), \
             patch("strategies.first_board_filter._get_kline_cache",
                   return_value={}), \
             patch("strategies.market_scan.build_non_limitup_candidates",
                   return_value=mock_candidates), \
             patch("candidate_funnel.sources._filters.classify_tradability",
                   return_value=(True, None, None)), \
             patch("candidate_funnel.sources.st_play_radar.load_st_play_radar",
                   return_value={}):
            # Act
            result = select_trend_candidates("2026-01-15")

        # Assert: ≤5 候选
        assert len(result) <= TREND_TOP_N
        assert len(result) == 2
        # 每个候选带正确 shape
        for cand in result:
            assert "code" in cand
            assert "name" in cand
            assert "sector" in cand
            assert "sector_rank" in cand
            assert "pattern" in cand
            assert "strategy_score" in cand
        # pattern=None（不跑 §44 falsified 形态扫描）
        assert all(c["pattern"] is None for c in result)
        # strategy_score=板块 composite（非 None）
        assert all(c["strategy_score"] is not None for c in result)


# ── T2.1a _process_trend realized ────────────────────────────────────────


class TestProcessTrendRealized:
    """T2.1a — _process_trend 产 realized（arm="trend", is_realized=1, net_pnl 非 None, cost_pct ≠0）。"""

    def test_realized_take_exit(self, journal, recorder):
        """bars 延伸到 T+2 + take 触发 → realized, exit_reason=take, cost_pct 含 5 元 min。"""
        # Arrange: bars 触发 take exit
        # entry=10.0 (T+1 open), take level=10*1.15=11.5, bars[2].high=11.6 >= 11.5 → take
        bars = [
            {"date": "2026-01-15", "open": 10.0, "high": 10.5,
             "low": 9.5, "close": 10.2, "volume": 10000},
            {"date": "2026-01-16", "open": 10.0, "high": 10.5,
             "low": 9.5, "close": 10.3, "volume": 10000},  # entry=T+1 open=10.0
            {"date": "2026-01-17", "open": 10.3, "high": 11.6,
             "low": 10.2, "close": 11.5, "volume": 10000},  # high=11.6 → take
        ]
        mock_candidates = [{"code": "000001", "name": "平安银行"}]

        with patch("strategies.trend_swing_arm.select_trend_candidates",
                   return_value=mock_candidates):
            recorder._bars_provider = lambda code: bars if code == "000001" else []
            # Act
            result = recorder._process_trend("2026-01-15")

        # Assert
        assert result["n_candidates"] == 1
        assert result["n_buyable"] == 1
        assert result["n_realized"] == 1
        records = journal.query_records(arm="trend", is_dead_arm=None)
        assert len(records) == 1
        r = records[0]
        assert r.arm == "trend"
        assert r.is_realized == 1
        assert r.net_pnl is not None
        # cost_pct 含 5 元 min 佣金（notional=1000, commission=10/1000*100=1.0 → total>1.0）
        assert r.cost_pct is not None
        assert r.cost_pct > 1.0  # 5 元 min 贡献 ~1.0pp，无佣金仅 0.75pp
        assert r.exit_reason in ("stop", "take", "max_hold")
        assert r.exit_reason == "take"  # 本次 bars 触发 take


# ── T2.1d _process_trend unbuyable ──────────────────────────────────────


class TestProcessTrendUnbuyable:
    """T2.1d — 涨停 fillability_check 拒 → exit_reason="unbuyable"。"""

    def test_unbuyable_limit_up_locked(self, journal, recorder):
        """涨停一字板 → Executor 拒 → exit_reason=unbuyable, is_realized=1, entry_price=None。"""
        # Arrange: 涨停封死 bars（open=high=close=涨停价, volume=0 → halted）
        locked_bars = [
            {"date": "2026-01-15", "open": 11.0, "high": 11.0,
             "low": 11.0, "close": 11.0, "volume": 0},
            {"date": "2026-01-16", "open": 11.0, "high": 11.0,
             "low": 11.0, "close": 11.0, "volume": 0},
        ]
        mock_candidates = [{"code": "000002", "name": "万科A"}]

        with patch("strategies.trend_swing_arm.select_trend_candidates",
                   return_value=mock_candidates):
            recorder._bars_provider = lambda code: locked_bars if code == "000002" else []
            # Act
            result = recorder._process_trend("2026-01-15")

        # Assert
        assert result["n_unbuyable"] == 1
        assert result["n_realized"] == 0
        records = journal.query_records(arm="trend", is_dead_arm=None)
        assert len(records) == 1
        r = records[0]
        assert r.exit_reason == "unbuyable"
        assert r.is_realized == 1
        assert r.entry_price is None


# ── T2.1b/c settle_pending_trend ─────────────────────────────────────────


class TestSettlePendingTrend:
    """T2.1b/c — settle_pending_trend 重算 hold（仿 settle_pending_breakout，换 TREND_* params）。"""

    def test_hold_realizes_when_bars_complete(self, journal, recorder):
        """T2.1b: hold → bars 增长到完整 max_hold → INSERT OR REPLACE 同 signal_id → is_realized=1。"""
        # Arrange: 先插一条 hold 记录
        hold = JournalRecord.create(
            arm="trend", stock_code="000001",
            entry_price=10.5, entry_date="2026-01-15",
            exit_reason="hold", is_realized=0,
            fills_json=json.dumps({"optimism_flag": "path_return_none_t1_guard"}),
        )
        journal.insert(hold)
        # bars 延伸到完整 max_hold=10（需 12 根：signal idx=0 + entry idx=1 + 10 天 = idx 11）
        # 微涨不触发 stop(-7%)/take(+15%)，走 max_hold exit
        bars = []
        for i in range(12):
            d = f"2026-01-{i + 15:02d}"
            price = 10.5 + i * 0.02
            bars.append({
                "date": d, "open": price - 0.1,
                "high": price + 0.1, "low": price - 0.2,
                "close": price, "volume": 10000,
            })
        recorder._bars_provider = lambda code: bars if code == "000001" else []

        # Act
        settled = recorder.settle_pending_trend()

        # Assert: settled=1, 同 signal_id, is_realized=1
        assert settled["n_settled"] == 1
        records = journal.query_records(arm="trend", is_realized=None, is_dead_arm=0)
        assert len(records) == 1  # INSERT OR REPLACE 同 signal_id（非新行）
        assert records[0].signal_id == hold.signal_id  # 同 id（bypass .create()）
        assert records[0].is_realized == 1
        assert records[0].net_pnl is not None
        assert records[0].exit_reason == "max_hold"

    def test_hold_stays_when_bars_truncated(self, journal, recorder):
        """T2.1c: bars 不足完整 max_hold → 截断检测留 hold 不标 realized。"""
        # Arrange
        hold = JournalRecord.create(
            arm="trend", stock_code="000001",
            entry_price=10.5, entry_date="2026-01-15",
            exit_reason="hold", is_realized=0,
            fills_json=json.dumps({"optimism_flag": "path_return_none_t1_guard"}),
        )
        journal.insert(hold)
        # bars 只 3 根（max_hold=10 需 12 根 → 截断）
        bars = [
            {"date": "2026-01-15", "open": 10.0, "high": 10.5,
             "low": 9.5, "close": 10.2, "volume": 10000},
            {"date": "2026-01-16", "open": 10.5, "high": 10.6,
             "low": 10.4, "close": 10.55, "volume": 10000},
            {"date": "2026-01-17", "open": 10.55, "high": 10.7,
             "low": 10.45, "close": 10.6, "volume": 10000},
        ]
        recorder._bars_provider = lambda code: bars if code == "000001" else []

        # Act
        settled = recorder.settle_pending_trend()

        # Assert: 截断留 hold
        assert settled["n_settled"] == 0
        records = journal.query_records(arm="trend", is_realized=None, is_dead_arm=0)
        assert len(records) == 1
        assert records[0].is_realized == 0  # 仍 hold
        assert records[0].exit_reason == "hold"
        assert records[0].signal_id == hold.signal_id  # 未被改
