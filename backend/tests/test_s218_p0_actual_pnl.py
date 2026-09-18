# -*- coding: utf-8 -*-
"""S218 P0-1: 实际交易录入 + 实际 vs 参考 P&L 差异 + weekly_review 实际 P&L 闭环测试。

测试目标：
- test_manual_trade_record_t0_fill_exists_not_wired: POST /api/signals/manual-trade 记录交易；record_t0_fill **定义存在但零生产调用**（P0 用 manual_trades.jsonl path 未接入 fills_json，s218-reality-check 2026-09-18 P0-1 修正）
- test_actual_vs_reference_pnl_diff: 差异计算正确
- test_delivery_leak_flag: 差距 >50% 时 leak alert 触发
- test_weekly_review_reads_actual_pnl: C5 cap-down 触发器现在使用实际 P&L，而非 paper proxy
"""
from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest


# ── fixtures ─────────────────────────────────────────────────────────────

@pytest.fixture(autouse=True)
def _patch_deps(monkeypatch, tmp_path):
    """Mock 外部依赖，防真 DB/真文件写入。"""
    # Mock _MANUAL_TRADES_FILE 到临时目录
    monkeypatch.setattr(
        "routers.signals._MANUAL_TRADES_FILE",
        tmp_path / "manual_trades.jsonl",
    )
    # Mock _get_reference_price_from_signal 避免读 DB
    monkeypatch.setattr(
        "routers.signals._get_reference_price_from_signal",
        lambda sid: (10.0, "mock_test"),
    )
    yield


# ── test: manual trade recording ───────────────────────────────────────

class TestManualTradeRecording:
    """测试 POST /api/signals/manual-trade 记录手动交易。"""

    def test_post_manual_trade_returns_trade_id(self):
        from routers.signals import _post_manual_trade, ManualTradeInput

        body = ManualTradeInput(
            code="000001",
            entry_price=10.0,
            entry_time="2026-09-18T09:30:00",
            exit_price=12.0,
            exit_time="2026-09-18T14:00:00",
            followed_reference=True,
            reference_signal_id="consecutive_relay_2026-09-18_000001",
        )
        result = _post_manual_trade(body)

        assert "trade_id" in result
        assert result["trade_id"].startswith("manual_")
        assert result["code"] == "000001"
        assert result["actual_pnl"]["status"] == "closed"
        assert result["actual_pnl"]["pnl_pct"] == pytest.approx(20.0, rel=1e-4)
        assert result["delivery_leak"] is False

    def test_manual_trade_with_no_exit_is_open(self):
        from routers.signals import _post_manual_trade, ManualTradeInput

        body = ManualTradeInput(
            code="000002",
            entry_price=10.0,
            entry_time="2026-09-18T09:30:00",
            exit_price=None,
            exit_time=None,
            followed_reference=False,
        )
        result = _post_manual_trade(body)

        assert result["actual_pnl"]["status"] == "open"
        assert result["actual_pnl"]["pnl_pct"] is None

    def test_manual_trade_persists_to_jsonl(self):
        from routers.signals import _post_manual_trade, _load_manual_trades, ManualTradeInput

        body = ManualTradeInput(
            code="000003",
            entry_price=10.0,
            entry_time="2026-09-18T09:30:00",
            exit_price=11.0,
            exit_time="2026-09-18T14:00:00",
            followed_reference=False,
        )
        _post_manual_trade(body)

        trades = _load_manual_trades()
        assert len(trades) >= 1
        # 最后一条是我们刚写入的
        last = trades[-1]
        assert last["code"] == "000003"
        assert last["entry_price"] == 10.0
        assert last["exit_price"] == 11.0

    def test_manual_trade_record_t0_fill_exists_not_wired(self):
        """record_t0_fill 定义存在但零生产调用——P0 用并行 manual_trades.jsonl path 未接入 fills_json。

        诚实标注（2026-09-18 reality-check s218-reality-check P0-1 修正）：
        record_t0_fill（journal_recorder.py:114）grep 全仓零生产调用者。
        P0 actual-P&L ingestion 用并行新 path（manual_trades.jsonl via POST /api/signals/manual-trade），
        **未接入** 现有 trade_journal fills_json via record_t0_fill。
        commit effaa99 msg "record_t0_fill wired" overstated——原 test 名"_wired"误导。

        本 test 只验 JournalRecorder.record_t0_fill 方法存在（hasattr/callable）+
        manual-trade 端点不抛异常——**不验任何生产调用者**（因为零调用）。
        若未来真接入 fills_json，须加 assert 验 record_t0_fill 被调用 + manual_trades.jsonl 含 fills_json 字段。
        """
        from routers.signals import _post_manual_trade, ManualTradeInput
        from strategies.journal_recorder import JournalRecorder

        # 只验方法存在非 wiring——record_t0_fill 零生产调用（grep 核实，s218-reality-check 2026-09-18）
        assert hasattr(JournalRecorder, "record_t0_fill")
        assert callable(getattr(JournalRecorder, "record_t0_fill"))

        body = ManualTradeInput(
            code="000004",
            entry_price=10.0,
            entry_time="2026-09-18T09:30:00",
            exit_price=11.0,
            exit_time="2026-09-18T14:00:00",
            followed_reference=True,
            reference_signal_id="consecutive_relay_2026-09-18_000004",
        )
        result = _post_manual_trade(body)
        # 成功记录交易（manual_trades.jsonl path），record_t0_fill 仍零调用——本 test 不验 wiring
        assert result["trade_id"].startswith("manual_")


# ── test: actual vs reference P&L diff ────────────────────────────────

class TestActualVsReferencePnlDiff:
    """测试实际 vs 参考 P&L 差异计算。"""

    def test_diff_positive_actual_vs_reference(self):
        from routers.signals import _compute_actual_pnl, _compute_reference_implied_pnl, _compute_pnl_diff

        actual = _compute_actual_pnl({"entry_price": 10.0, "exit_price": 12.0})
        reference = _compute_reference_implied_pnl({"reference_price": 10.0})
        diff = _compute_pnl_diff(actual, reference)

        assert diff["diff_pct"] == pytest.approx(18.96, abs=0.01)
        assert diff["delivery_leak"] is False

    def test_diff_negative_actual_vs_reference(self):
        from routers.signals import _compute_actual_pnl, _compute_reference_implied_pnl, _compute_pnl_diff

        actual = _compute_actual_pnl({"entry_price": 10.0, "exit_price": 8.0})
        reference = _compute_reference_implied_pnl({"reference_price": 10.0})
        diff = _compute_pnl_diff(actual, reference)

        assert diff["diff_pct"] == pytest.approx(-21.04, abs=0.01)
        assert diff["delivery_leak"] is False

    def test_diff_no_reference_price(self):
        from routers.signals import _compute_actual_pnl, _compute_reference_implied_pnl, _compute_pnl_diff

        actual = _compute_actual_pnl({"entry_price": 10.0, "exit_price": 12.0})
        reference = _compute_reference_implied_pnl({})  # 无 reference_price
        diff = _compute_pnl_diff(actual, reference)

        assert diff["diff_pct"] is None
        assert diff["delivery_leak"] is False

    def test_diff_open_trade(self):
        from routers.signals import _compute_actual_pnl, _compute_reference_implied_pnl, _compute_pnl_diff

        actual = _compute_actual_pnl({"entry_price": 10.0})  # 未平仓
        reference = _compute_reference_implied_pnl({"reference_price": 10.0})
        diff = _compute_pnl_diff(actual, reference)

        assert diff["diff_pct"] is None
        assert diff["delivery_leak"] is False


# ── test: delivery leak flag ───────────────────────────────────────────

class TestDeliveryLeakFlag:
    """测试 |actual - reference| > 50% 时 leak alert 触发。"""

    def test_leak_flag_true_when_gap_exceeds_50pct(self):
        from routers.signals import _compute_actual_pnl, _compute_reference_implied_pnl, _compute_pnl_diff

        # 实际 +80%，参考 +1.04% → 差距 78.96% > 50%
        actual = _compute_actual_pnl({"entry_price": 10.0, "exit_price": 18.0})
        reference = _compute_reference_implied_pnl({"reference_price": 10.0})
        diff = _compute_pnl_diff(actual, reference)

        assert diff["delivery_leak"] is True
        assert abs(diff["diff_pct"]) > 50.0
        assert "78.96" in diff["leak_reason"] or "实际" in diff["leak_reason"]

    def test_leak_flag_false_when_gap_within_50pct(self):
        from routers.signals import _compute_actual_pnl, _compute_reference_implied_pnl, _compute_pnl_diff

        # 实际 +30%，参考 +1.04% → 差距 28.96% < 50%
        actual = _compute_actual_pnl({"entry_price": 10.0, "exit_price": 13.0})
        reference = _compute_reference_implied_pnl({"reference_price": 10.0})
        diff = _compute_pnl_diff(actual, reference)

        assert diff["delivery_leak"] is False

    def test_leak_flag_boundary_at_exactly_50pct(self):
        from routers.signals import _compute_actual_pnl, _compute_reference_implied_pnl, _compute_pnl_diff

        # 差距 = 50% 时刚好不触发（> 50% 才触发）
        # 参考 +1.04%, 要差距 = 50 → 实际 = 51.04% → exit = 15.104
        actual = _compute_actual_pnl({"entry_price": 10.0, "exit_price": 15.104})
        reference = _compute_reference_implied_pnl({"reference_price": 10.0})
        diff = _compute_pnl_diff(actual, reference)

        # diff_pct = 51.04 - 1.04 = 50.0, |50.0| = 50.0 NOT > 50.0 → False
        assert diff["delivery_leak"] is False


# ── test: weekly_review reads actual P&L ──────────────────────────────

class TestWeeklyReviewReadsActualPnl:
    """C5 cap-down 触发器现在使用实际 P&L，而非 paper proxy。"""

    def test_weekly_review_prefers_actual_pnl_when_available(self, monkeypatch):
        from routers.signals import _post_manual_trade, ManualTradeInput
        from scheduler.executors.signals import weekly_review

        # 先录一笔盈利交易
        body = ManualTradeInput(
            code="000005",
            entry_price=10.0,
            entry_time="2026-09-18T09:30:00",
            exit_price=15.0,
            exit_time="2026-09-18T14:00:00",
            followed_reference=True,
            reference_signal_id="consecutive_relay_2026-09-18_000005",
        )
        _post_manual_trade(body)

        # Mock get_consecutive_relay_signals
        monkeypatch.setattr(
            "scheduler.executors.signals.get_consecutive_relay_signals",
            MagicMock(return_value={
                "date": "2026-09-18",
                "arm": "consecutive_relay",
                "regime": {"current": "bull"},
                "cap": {"effective": 0.75},
                "signals": [],
            }),
        )
        # Mock TradeJournal
        _FakeTJ = MagicMock()
        _FakeTJ.return_value.query_winrate_trends.return_value = []
        _FakeTJ.return_value.query_arm_status.return_value = {
            "is_active": True, "weight_override": None, "kill_reason": None, "killed_at": None,
        }
        monkeypatch.setattr("engine.trade_journal.TradeJournal", _FakeTJ)
        monkeypatch.setattr("scheduler.executors.signals._send_text_notification", MagicMock())

        result = weekly_review({"run_date": "2026-09-18"})

        assert result["status"] == "ok"
        # 有实际 P&L 且 mean > 0 → 不应触发 cap-down
        assert result["cap_down_proposal"] is None
        # review_text 中应包含实际 P&L 信息
        assert "实际 P&L" in result["review_text"] or "手动交易" in result["review_text"]

    def test_weekly_review_cap_down_on_actual_pnl_negative(self, monkeypatch):
        from routers.signals import _post_manual_trade, ManualTradeInput
        from scheduler.executors.signals import weekly_review

        # 先录一笔亏损交易（实际 P&L -20%）
        body = ManualTradeInput(
            code="000006",
            entry_price=10.0,
            entry_time="2026-09-18T09:30:00",
            exit_price=8.0,
            exit_time="2026-09-18T14:00:00",
            followed_reference=True,
            reference_signal_id="consecutive_relay_2026-09-18_000006",
        )
        _post_manual_trade(body)

        monkeypatch.setattr(
            "scheduler.executors.signals.get_consecutive_relay_signals",
            MagicMock(return_value={
                "date": "2026-09-18",
                "arm": "consecutive_relay",
                "regime": {"current": "bull"},
                "cap": {"effective": 0.75},
                "signals": [],
            }),
        )
        _FakeTJ = MagicMock()
        _FakeTJ.return_value.query_winrate_trends.return_value = []
        _FakeTJ.return_value.query_arm_status.return_value = {
            "is_active": True, "weight_override": None, "kill_reason": None, "killed_at": None,
        }
        monkeypatch.setattr("engine.trade_journal.TradeJournal", _FakeTJ)
        monkeypatch.setattr("scheduler.executors.signals._send_text_notification", MagicMock())

        result = weekly_review({"run_date": "2026-09-18"})

        assert result["status"] == "ok"
        # 实际 P&L 为负 → 应触发 cap-down
        assert result["cap_down_proposal"] is not None
        assert result["cap_down_proposal"]["action"] == "cap-down"
        assert "实际 P&L" in result["cap_down_proposal"]["reason"]

    def test_weekly_review_falls_back_to_paper_when_no_actual_trades(self, monkeypatch):
        from scheduler.executors.signals import weekly_review

        monkeypatch.setattr(
            "scheduler.executors.signals.get_consecutive_relay_signals",
            MagicMock(return_value={
                "date": "2026-09-18",
                "arm": "consecutive_relay",
                "regime": {"current": "bull"},
                "cap": {"effective": 0.75},
                "signals": [],
            }),
        )
        _FakeTJ = MagicMock()
        _FakeTJ.return_value.query_winrate_trends.return_value = [
            {"week_start": "2026-09-08", "win_rate": 0.4, "n_decided": 10, "n_days": 5, "label": "underpowered"},
        ]
        _FakeTJ.return_value.query_arm_status.return_value = {
            "is_active": True, "weight_override": None, "kill_reason": None, "killed_at": None,
        }
        monkeypatch.setattr("engine.trade_journal.TradeJournal", _FakeTJ)
        monkeypatch.setattr("scheduler.executors.signals._send_text_notification", MagicMock())

        result = weekly_review({"run_date": "2026-09-18"})

        assert result["status"] == "ok"
        # paper P&L mean < 0.5 → cap-down
        assert result["cap_down_proposal"] is not None
        assert "paper" in result["cap_down_proposal"]["reason"]

    def test_weekly_review_leak_alert_in_review_text(self, monkeypatch):
        from routers.signals import _post_manual_trade, ManualTradeInput
        from scheduler.executors.signals import weekly_review

        # 录一笔差距巨大的交易（实际 +80%，参考 +1.04% → leak）
        body = ManualTradeInput(
            code="000007",
            entry_price=10.0,
            entry_time="2026-09-18T09:30:00",
            exit_price=18.0,
            exit_time="2026-09-18T14:00:00",
            followed_reference=True,
            reference_signal_id="consecutive_relay_2026-09-18_000007",
        )
        _post_manual_trade(body)

        monkeypatch.setattr(
            "scheduler.executors.signals.get_consecutive_relay_signals",
            MagicMock(return_value={
                "date": "2026-09-18",
                "arm": "consecutive_relay",
                "regime": {"current": "bull"},
                "cap": {"effective": 0.75},
                "signals": [],
            }),
        )
        _FakeTJ = MagicMock()
        _FakeTJ.return_value.query_winrate_trends.return_value = []
        _FakeTJ.return_value.query_arm_status.return_value = {
            "is_active": True, "weight_override": None, "kill_reason": None, "killed_at": None,
        }
        monkeypatch.setattr("engine.trade_journal.TradeJournal", _FakeTJ)
        monkeypatch.setattr("scheduler.executors.signals._send_text_notification", MagicMock())

        result = weekly_review({"run_date": "2026-09-18"})

        assert result["status"] == "ok"
        # review_text 中应包含 delivery leak 警告
        assert "delivery leak" in result["review_text"] or "执行偏差" in result["review_text"]
