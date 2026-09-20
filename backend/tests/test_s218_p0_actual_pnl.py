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

# 真实 _SIGNAL_DIR（模块级捕获，早于 autouse fixture patch，用于 sentinel 检测测试污染）
_REPO_ROOT = Path(__file__).resolve().parents[2]
_REAL_SIGNAL_DIR = _REPO_ROOT / ".vibe-research" / "signal_reports"


# ── fixtures ─────────────────────────────────────────────────────────────

@pytest.fixture(autouse=True)
def _patch_deps(monkeypatch, tmp_path):
    """Mock 外部依赖，防真 DB/真文件写入。"""
    # Mock _MANUAL_TRADES_FILE 到临时目录
    monkeypatch.setattr(
        "routers.signals._MANUAL_TRADES_FILE",
        tmp_path / "manual_trades.jsonl",
    )
    # Mock _SIGNAL_DIR 到临时目录——防 weekly_review 存报告污染生产 artifact
    # （P0 phantom 根因：测试数据 entry 10/exit 4 → -60% 泄漏进真实
    #  .vibe-research/signal_reports/2026-09-18_weekly_review.json，
    #  致 manual_trades.jsonl 0 字节但报告报 -60% n=1 幽灵交易）
    monkeypatch.setattr(
        "scheduler.executors.signals._SIGNAL_DIR",
        tmp_path / "signal_reports",
    )
    # Mock _get_reference_price_from_signal 避免读 DB（3-tuple: price, source, arm）
    # arm=consecutive_relay 让 followed_reference=True 的端点测试拿到 chrono edge +1.04%
    monkeypatch.setattr(
        "routers.signals._get_reference_price_from_signal",
        lambda sid: (10.0, "mock_test", "consecutive_relay"),
    )
    # Mock s203 harness main + TradeJournal——防 weekly_review 调 _compute_consecutive_relay_decay
    # 跑真 s203 harness hang（#2 gap，#10 agent 发现）
    from unittest.mock import MagicMock
    monkeypatch.setattr(
        "tools.s203_consecutive_relay_harness.main",
        MagicMock(return_value={"bull_chrono_oos": {"decision": "insufficient"}}),
    )
    _FakeTJ = MagicMock()
    _FakeTJ.return_value.query_records.return_value = []
    monkeypatch.setattr("engine.trade_journal.TradeJournal", _FakeTJ)
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

    def test_manual_trade_writes_to_manual_trades_jsonl(self):
        """v3 P0-4（2026-09-20）：record_t0_fill 死代码已删，manual_trade 走 manual_trades.jsonl。

        验 _post_manual_trade 真写 manual_trades.jsonl（actual P&L ingestion 闭环）。
        record_t0_fill 已删（零生产调用，manual_trade 不接 fills_json——原设计要求
        signal_id 在 trade_journal 表存在但 manual_trade 的 reference_signal_id 不在该表）。
        """
        from routers.signals import _post_manual_trade, ManualTradeInput, _load_manual_trades

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
        assert result["trade_id"].startswith("manual_")

        # 验真写 manual_trades.jsonl（actual P&L ingestion 闭环）
        trades = _load_manual_trades()
        last = trades[-1] if trades else {}
        assert last.get("code") == "000004"
        assert last.get("entry_price") == 10.0
        assert last.get("actual_pnl", {}).get("status") == "closed"


# ── test: actual vs reference P&L diff ────────────────────────────────

class TestActualVsReferencePnlDiff:
    """测试实际 vs 参考 P&L 差异计算。"""

    def test_diff_positive_actual_vs_reference(self):
        from routers.signals import _compute_actual_pnl, _compute_reference_implied_pnl, _compute_pnl_diff

        actual = _compute_actual_pnl({"entry_price": 10.0, "exit_price": 12.0})
        reference = _compute_reference_implied_pnl({"reference_price": 10.0, "reference_arm": "consecutive_relay"})
        diff = _compute_pnl_diff(actual, reference)

        assert diff["diff_pct"] == pytest.approx(18.96, abs=0.01)
        assert diff["delivery_leak"] is False

    def test_diff_negative_actual_vs_reference(self):
        from routers.signals import _compute_actual_pnl, _compute_reference_implied_pnl, _compute_pnl_diff

        actual = _compute_actual_pnl({"entry_price": 10.0, "exit_price": 8.0})
        reference = _compute_reference_implied_pnl({"reference_price": 10.0, "reference_arm": "consecutive_relay"})
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
        reference = _compute_reference_implied_pnl({"reference_price": 10.0, "reference_arm": "consecutive_relay"})
        diff = _compute_pnl_diff(actual, reference)

        assert diff["diff_pct"] is None
        assert diff["delivery_leak"] is False


# ── test: reference_pnl arm-specific (F3) ────────────────────────────

class TestReferencePnlArmSpecific:
    """F3: reference_pnl arm-specific——仅 consecutive_relay 有 chrono edge +1.04%。

    其他 arm（floor/breakout/trend_swing/等）无 validated chrono edge，
    诚实返 None（不套 consecutive_relay 的 edge 当 universal）。
    """

    def test_consecutive_relay_arm_gets_chrono_edge(self):
        from routers.signals import _compute_reference_implied_pnl

        ref = _compute_reference_implied_pnl({
            "reference_price": 10.0,
            "reference_arm": "consecutive_relay",
        })
        assert ref["pnl_pct"] == pytest.approx(1.04, abs=0.01)
        assert ref["source"] == "chrono_test_mean_1.04pct"

    def test_floor_arm_no_chrono_edge(self):
        from routers.signals import _compute_reference_implied_pnl

        ref = _compute_reference_implied_pnl({
            "reference_price": 10.0,
            "reference_arm": "floor",
        })
        assert ref["pnl_pct"] is None
        assert ref["source"] == "no_chrono_edge_for_arm"

    def test_breakout_arm_no_chrono_edge(self):
        from routers.signals import _compute_reference_implied_pnl

        ref = _compute_reference_implied_pnl({
            "reference_price": 10.0,
            "reference_arm": "breakout",
        })
        assert ref["pnl_pct"] is None
        assert ref["source"] == "no_chrono_edge_for_arm"

    def test_no_arm_no_chrono_edge(self):
        from routers.signals import _compute_reference_implied_pnl

        # 无 arm 信息 → 诚实返 None（不默认套 +1.04%）
        ref = _compute_reference_implied_pnl({"reference_price": 10.0})
        assert ref["pnl_pct"] is None
        assert ref["source"] == "no_chrono_edge_for_arm"


# ── test: delivery leak flag (F4 one-sided) ──────────────────────────

class TestDeliveryLeakFlag:
    """F4: one-sided leak——actual 远低于 reference（edge 没交付）才 leak。

    over-performance（actual >> reference，diff > 0）不标 leak。
    """

    def test_leak_flag_true_when_under_performance_exceeds_50pct(self):
        from routers.signals import _compute_actual_pnl, _compute_reference_implied_pnl, _compute_pnl_diff

        # 实际 -60%，参考 +1.04% → diff = -61.04 < -50 → leak（edge 没交付）
        actual = _compute_actual_pnl({"entry_price": 10.0, "exit_price": 4.0})
        reference = _compute_reference_implied_pnl({"reference_price": 10.0, "reference_arm": "consecutive_relay"})
        diff = _compute_pnl_diff(actual, reference)

        assert diff["delivery_leak"] is True
        assert diff["diff_pct"] < -50.0
        assert "实际" in diff["leak_reason"]

    def test_leak_flag_false_when_over_performance(self):
        from routers.signals import _compute_actual_pnl, _compute_reference_implied_pnl, _compute_pnl_diff

        # 实际 +80%，参考 +1.04% → diff = +78.96，over-performance → NOT leak
        actual = _compute_actual_pnl({"entry_price": 10.0, "exit_price": 18.0})
        reference = _compute_reference_implied_pnl({"reference_price": 10.0, "reference_arm": "consecutive_relay"})
        diff = _compute_pnl_diff(actual, reference)

        assert diff["delivery_leak"] is False
        assert diff["diff_pct"] == pytest.approx(78.96, abs=0.01)

    def test_leak_flag_false_when_gap_within_50pct(self):
        from routers.signals import _compute_actual_pnl, _compute_reference_implied_pnl, _compute_pnl_diff

        # 实际 +30%，参考 +1.04% → diff = +28.96，未低于 reference → NOT leak
        actual = _compute_actual_pnl({"entry_price": 10.0, "exit_price": 13.0})
        reference = _compute_reference_implied_pnl({"reference_price": 10.0, "reference_arm": "consecutive_relay"})
        diff = _compute_pnl_diff(actual, reference)

        assert diff["delivery_leak"] is False

    def test_leak_flag_boundary_at_exactly_50_below(self):
        from routers.signals import _compute_actual_pnl, _compute_reference_implied_pnl, _compute_pnl_diff

        # 边界：diff = -50.0 刚好不触发（< -50 才触发）
        # 参考 +1.04%，要 diff=-50 → actual = 1.04 - 50 = -48.96 → exit = 5.104
        actual = _compute_actual_pnl({"entry_price": 10.0, "exit_price": 5.104})
        reference = _compute_reference_implied_pnl({"reference_price": 10.0, "reference_arm": "consecutive_relay"})
        diff = _compute_pnl_diff(actual, reference)

        # diff_pct = -48.96 - 1.04 = -50.0，NOT < -50.0 → False
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

        # 录一笔 under-performance 交易（实际 -60%，参考 +1.04% → diff=-61.04 < -50 → leak）
        # F4 one-sided：over-performance 不 leak，只有 actual 远低于 reference 才 leak
        body = ManualTradeInput(
            code="000007",
            entry_price=10.0,
            entry_time="2026-09-18T09:30:00",
            exit_price=4.0,
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


# ── test: weekly_review artifact isolation (P0 phantom root cause) ──────

class TestWeeklyReviewArtifactIsolation:
    """P0 幽灵交易根因修复：weekly_review 测试不得污染生产报告 artifact。

    根因（诊断 2026-09-20）：autouse fixture 隔离了 _MANUAL_TRADES_FILE
    （测试交易写 tmp_path），但未隔离 _SIGNAL_DIR（weekly_review 存报告到真实
    repo-root .vibe-research/signal_reports/）。测试数据（entry 10/exit 4 →
    -60%）泄漏进生产 2026-09-18_weekly_review.json，造成 manual_trades.jsonl
    0 字节但报告报 -60% n=1 的幽灵交易。生产 weekly_review 代码本身正确
    （读 manual_trades.jsonl，空则 None/0），幽灵来自测试污染。
    """

    def test_weekly_review_saves_to_isolated_dir_not_real_signal_dir(self, monkeypatch):
        """weekly_review 须存到隔离 tmp_path，不写真实 _SIGNAL_DIR。"""
        from routers.signals import _post_manual_trade, ManualTradeInput
        from scheduler.executors.signals import weekly_review

        # sentinel：未来日期，保证真实 _SIGNAL_DIR 无此文件
        sentinel_date = "2099-01-01"
        sentinel_real_path = _REAL_SIGNAL_DIR / f"{sentinel_date}_weekly_review.json"
        if sentinel_real_path.exists():
            sentinel_real_path.unlink()
        assert not sentinel_real_path.exists(), "前置：sentinel 不该存在"

        # 录一笔测试交易（写隔离 tmp_path，autouse 已 patch _MANUAL_TRADES_FILE）
        body = ManualTradeInput(
            code="999999",
            entry_price=10.0,
            entry_time="2026-09-18T09:30:00",
            exit_price=4.0,  # → -60%，复现幽灵数值
            exit_time="2026-09-18T14:00:00",
            followed_reference=True,
            reference_signal_id="consecutive_relay_2026-09-18_999999",
        )
        _post_manual_trade(body)

        monkeypatch.setattr(
            "scheduler.executors.signals.get_consecutive_relay_signals",
            MagicMock(return_value={
                "date": sentinel_date,
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

        result = weekly_review({"run_date": sentinel_date})
        assert result["status"] == "ok"

        # 核心断言：真实 _SIGNAL_DIR 不得出现 sentinel（测试数据不泄漏到生产）
        assert not sentinel_real_path.exists(), (
            "weekly_review 污染生产报告 artifact：测试数据写进真实 _SIGNAL_DIR "
            f"（{sentinel_real_path}），这是 -60% 幽灵交易的根因"
        )

        # 报告应写到隔离的 _SIGNAL_DIR（autouse fixture patch 后 = tmp_path）
        from scheduler.executors.signals import _SIGNAL_DIR as isolated_dir
        isolated_path = isolated_dir / f"{sentinel_date}_weekly_review.json"
        assert isolated_path.exists(), "weekly_review 未存到隔离 _SIGNAL_DIR"

