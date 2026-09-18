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
    # decay 函数调 query_records——默认返 []（bear_days=0）
    _FakeTJ.return_value.query_records.return_value = []
    monkeypatch.setattr("engine.trade_journal.TradeJournal", _FakeTJ)
    # Mock s203 harness main（benign underpowered chrono）——防 weekly_review 跑真 harness
    monkeypatch.setattr(
        "tools.s203_consecutive_relay_harness.main",
        MagicMock(return_value={"bull_chrono_oos": {"decision": "insufficient"}}),
    )
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


# ── test: _compute_consecutive_relay_decay (S218 #2 cap gate 真衰减) ──────

class TestComputeDecay:
    """_compute_consecutive_relay_decay 真衰减 stats 测试（替 weekly_review 硬编码）。"""

    def test_compute_decay_from_s203_chrono(self, monkeypatch):
        """test_compute_decay_from_s203_chrono: s203 chrono → decay_pct≈33.8 / decay_stable=False / bear_days=0."""
        mock_main = MagicMock(return_value={
            "bull_chrono_oos": {
                "train_day_mean": 0.0157,
                "test_day_mean": 0.0104,
                "test_day_std": 0.0259,
                "n_test_days": 57,
                "decision": "oos_supporting",
            },
        })
        monkeypatch.setattr("tools.s203_consecutive_relay_harness.main", mock_main)

        from tools.signal_report import _compute_consecutive_relay_decay
        stats = _compute_consecutive_relay_decay()

        # decay_pct = (0.0157 - 0.0104) / 0.0157 * 100 ≈ 33.76
        assert stats["decay_pct"] == pytest.approx(33.76, abs=0.05)
        # test_std 0.0259 > 0.02 (decimal=2.0pct) → 不稳定 → False（诚实标 borderline）
        assert stats["decay_stable"] is False
        assert stats["bear_days"] == 0
        assert stats["lbc3_days"] == 0
        assert stats["n_test_days"] == 57
        assert stats["source"] == "s203_chrono"

    def test_compute_decay_s203_error_fallback(self, monkeypatch):
        """test_compute_decay_s203_error_fallback: s203 跑失败 → fallback decay_stable=False / source 含 'error'."""
        mock_main = MagicMock(side_effect=RuntimeError("s203 boom"))
        monkeypatch.setattr("tools.s203_consecutive_relay_harness.main", mock_main)

        from tools.signal_report import _compute_consecutive_relay_decay
        stats = _compute_consecutive_relay_decay()

        assert stats["decay_stable"] is False
        assert "error" in stats["source"]
        assert stats["bear_days"] == 0
        assert stats["lbc3_days"] == 0

    def test_compute_decay_s203_timeout_fallback(self, monkeypatch):
        """test_compute_decay_s203_timeout_fallback: s203 跑超 timeout → fallback source='timeout' decay_stable=False（不 hang）。

        模拟 Sep-21 weekly_review cron 调真 s203 harness 可能 hang 的场景：
        mock s203_main sleep > timeout，assert 主线程不被 join 阻塞，返 timeout fallback
        （保守 decay_stable=False，cap gate 不 fire 升 ×1.0）。
        """
        import time
        # 缩短 timeout 到 0.1s（测试快跑），s203_main sleep 0.3s > 0.1s → timeout
        monkeypatch.setattr("tools.signal_report._S203_TIMEOUT_SEC", 0.1)
        mock_main = MagicMock(side_effect=lambda: time.sleep(0.3))
        monkeypatch.setattr("tools.s203_consecutive_relay_harness.main", mock_main)

        from tools.signal_report import _compute_consecutive_relay_decay
        stats = _compute_consecutive_relay_decay()

        assert stats["decay_stable"] is False
        assert stats["source"] == "timeout"
        assert stats["bear_days"] == 0
        assert stats["lbc3_days"] == 0
