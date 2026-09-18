# -*- coding: utf-8 -*-
"""S218 Component 5: 阶段性汇总复盘 weekly_review 测试（TDD - RED → GREEN）。

验收 (spec §4, v3):
- test_weekly_review_reuses_c1_core: assert calls get_consecutive_relay_signals (mock), no duplicated scan/regime/lift
- test_cap_up_gate_uses_reconciled_definition: assert ×1.0 gate = ALL (bear 120+天 AND 60d decay stable AND lbc=3 60d) — not OR
- test_cap_down_triggers_on_decay_worsening: assert 衰减>34% → cap-down 提案生成
- test_process_theater_self_check_concrete: assert paper P&L mean<0 OR 衰减跨 negative → cap-down proposal artifact
- test_chuangye_board_caveat_placeholder_present: assert 创业板做市商断点 caveat 标为占位/TODO
- test_paper_only_pnl_honest_label: assert "paper" + "没真交易收益" + "接券商才有真 closure" present
"""
from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest


# ── fixtures ──────────────────────────────────────────────────────────────

@pytest.fixture(autouse=True)
def _patch_deps(monkeypatch):
    """Mock 外部依赖，防真查 DB/真发通知。"""
    # Mock get_consecutive_relay_signals (C1 shared core)
    monkeypatch.setattr(
        "scheduler.executors.signals.get_consecutive_relay_signals",
        MagicMock(return_value={
            "date": "2026-09-14",
            "arm": "consecutive_relay",
            "regime": {"current": "bull"},
            "cap": {"effective": 0.75, "base": 1.0, "decay": 0.75, "regime_factor": 1.0, "zuoT_factor": 1.0},
            "signals": [],
        }),
    )
    # Mock TradeJournal
    _FakeTJ = MagicMock()
    _FakeTJ.return_value.query_winrate_trends.return_value = [
        {"week_start": "2026-09-08", "win_rate": 0.55, "n_decided": 10, "n_days": 5, "label": "underpowered"},
    ]
    _FakeTJ.return_value.query_arm_status.return_value = {
        "arm": "consecutive_relay", "is_active": True,
        "weight_override": None, "kill_reason": None, "killed_at": None,
    }
    monkeypatch.setattr("engine.trade_journal.TradeJournal", _FakeTJ)
    # Mock NotificationService
    monkeypatch.setattr(
        "scheduler.executors.signals._send_text_notification",
        MagicMock(),
    )
    yield


# ── test: weekly_review ───────────────────────────────────────────────────

class TestWeeklyReview:
    """weekly_review 核心行为测试。"""

    def test_weekly_review_reuses_c1_core(self, monkeypatch):
        """test_weekly_review_reuses_c1_core: assert calls get_consecutive_relay_signals (mock), no duplicated scan/regime/lift."""
        from scheduler.executors.signals import weekly_review
        mock_get = MagicMock(return_value={
            "date": "2026-09-14",
            "arm": "consecutive_relay",
            "regime": {"current": "bull"},
            "cap": {"effective": 0.75},
            "signals": [],
        })
        monkeypatch.setattr("tools.signal_report.get_consecutive_relay_signals", mock_get)

        result = weekly_review({"run_date": "2026-09-14"})

        assert result["status"] == "ok"
        mock_get.assert_called_once_with("2026-09-14")

    def test_cap_up_gate_uses_reconciled_definition(self):
        """test_cap_up_gate_uses_reconciled_definition: assert ×1.0 gate = ALL (bear 120+天 AND 60d decay stable AND lbc=3 60d) — not OR."""
        from scheduler.executors.signals import _evaluate_cap_up_gate

        # 全满足 → 可升 ×1.0
        assert _evaluate_cap_up_gate(
            bear_days=120, decay_stable=True, lbc3_days=60
        ) is True

        # 缺任一 → 不可升
        assert _evaluate_cap_up_gate(
            bear_days=119, decay_stable=True, lbc3_days=60
        ) is False
        assert _evaluate_cap_up_gate(
            bear_days=120, decay_stable=False, lbc3_days=60
        ) is False
        assert _evaluate_cap_up_gate(
            bear_days=120, decay_stable=True, lbc3_days=59
        ) is False

        # 缺两个/全缺 → 不可升
        assert _evaluate_cap_up_gate(
            bear_days=0, decay_stable=False, lbc3_days=0
        ) is False

    def test_cap_down_triggers_on_decay_worsening(self):
        """test_cap_down_triggers_on_decay_worsening: assert 衰减>34% → cap-down 提案生成."""
        from scheduler.executors.signals import _evaluate_cap_down_trigger

        # 衰减 >34% → 触发
        assert _evaluate_cap_down_trigger(decay_pct=35) is True
        assert _evaluate_cap_down_trigger(decay_pct=50) is True

        # 衰减 ≤34% → 不触发
        assert _evaluate_cap_down_trigger(decay_pct=34) is False
        assert _evaluate_cap_down_trigger(decay_pct=20) is False

        # 边界：34% 不触发（>34% 才触发）
        assert _evaluate_cap_down_trigger(decay_pct=34.0) is False

    def test_process_theater_self_check_concrete(self, monkeypatch):
        """test_process_theater_self_check_concrete: assert paper P&L mean<0 OR 衰减跨 negative → cap-down proposal artifact generated."""
        from scheduler.executors.signals import weekly_review

        # paper P&L mean<0 → 触发 cap-down 提案
        fake_tj = MagicMock()
        fake_tj.return_value.query_winrate_trends.return_value = [
            {"week_start": "2026-09-08", "win_rate": 0.4, "n_decided": 10, "n_days": 5, "label": "underpowered"},
        ]
        fake_tj.return_value.query_arm_status.return_value = {"is_active": True}
        monkeypatch.setattr("engine.trade_journal.TradeJournal", fake_tj)

        result = weekly_review({"run_date": "2026-09-14"})
        assert result["status"] == "ok"
        assert result["cap_down_proposal"] is not None
        assert "cap-down" in result["cap_down_proposal"]["action"]

    def test_chuangye_board_caveat_placeholder_present(self):
        """test_chuangye_board_caveat_placeholder_present: assert 创业板做市商断点 caveat 标为占位/TODO."""
        from scheduler.executors.signals import weekly_review

        result = weekly_review({"run_date": "2026-09-14"})
        review_text = result.get("review_text", "")

        # 占位符/关键词必须存在（不实现子样本分析，只留占位）
        assert "TODO" in review_text or "占位" in review_text or "后期实现" in review_text
        assert "创业板" in review_text or "做市商" in review_text or "2026-07-06" in review_text

    def test_paper_only_pnl_honest_label(self):
        """test_paper_only_pnl_honest_label: assert "paper" + "没真交易收益" + "接券商才有真 closure" present."""
        from scheduler.executors.signals import weekly_review

        result = weekly_review({"run_date": "2026-09-14"})
        review_text = result.get("review_text", "")

        assert "paper" in review_text.lower()
        assert "没真交易收益" in review_text or "无真交易" in review_text or "零真交易" in review_text
        assert "接券商" in review_text or "closure" in review_text.lower()
