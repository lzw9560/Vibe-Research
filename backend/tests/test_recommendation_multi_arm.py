# -*- coding: utf-8 -*-
"""S175 T7 — 多臂 RecommendationEngine 测试（R9↔R10 接线 SH1 + honest_label C7）。"""
import sys
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest

backend_dir = Path(__file__).resolve().parent.parent
if str(backend_dir) not in sys.path:
    sys.path.insert(0, str(backend_dir))


@pytest.fixture
def mock_pp():
    """Mock PaperPortfolio，equity() 返 100000。"""
    pp = MagicMock()
    pp.equity.return_value = 100000.0
    return pp


class TestMultiArmRecommendation:
    """S175 R9 — 多臂推荐 honest_label + floor 读 equity sizing。"""

    def test_floor_actionable_with_equity_sizing(self, tmp_path, monkeypatch, mock_pp):
        monkeypatch.setenv("VR_DATA_DIR", str(tmp_path))
        from recommendation_engine import get_multi_arm_recommendations, ArmHonestLabel
        batches = [{"batch_idx": i, "date": "2026-01-15", "amount": 10000, "status": "planned"} for i in range(5)]
        with patch("strategies.index_replication_floor.build_position_batches", return_value=batches):
            recs = get_multi_arm_recommendations(paper_portfolio=mock_pp)
        floor = next(r for r in recs if r.arm == "floor")
        assert floor.honest_label == ArmHonestLabel.EXTERNALLY_VALIDATED
        assert floor.action_type == "batch_buy"
        assert floor.code == "512890"
        assert "100000" in floor.sizing_suggestion  # equity 透传 sizing
        assert floor.validated is True

    def test_breakout_marked_section44_falsified_not_weak(self, tmp_path, monkeypatch, mock_pp):
        """grill C7：breakout=§44_falsified 非 weak 非 underpowered_tracking。"""
        monkeypatch.setenv("VR_DATA_DIR", str(tmp_path))
        from recommendation_engine import get_multi_arm_recommendations, ArmHonestLabel
        with patch("strategies.index_replication_floor.build_position_batches", return_value=[]):
            recs = get_multi_arm_recommendations(paper_portfolio=mock_pp)
        bo = next(r for r in recs if r.arm == "breakout")
        assert bo.honest_label == ArmHonestLabel.SECTION44_FALSIFIED
        assert bo.action_type == "paper_track"
        assert bo.validated is False
        assert "§44" in bo.note

    def test_gap_dead_arm_not_recommended(self, tmp_path, monkeypatch, mock_pp):
        monkeypatch.setenv("VR_DATA_DIR", str(tmp_path))
        from recommendation_engine import get_multi_arm_recommendations, ArmHonestLabel
        with patch("strategies.index_replication_floor.build_position_batches", return_value=[]):
            recs = get_multi_arm_recommendations(paper_portfolio=mock_pp)
        gap = next(r for r in recs if r.arm == "gap")
        assert gap.honest_label == ArmHonestLabel.DEAD_ARM
        assert gap.action_type == "none"  # 不推荐

    def test_limitup_trend_mock_not_ready(self, tmp_path, monkeypatch, mock_pp):
        monkeypatch.setenv("VR_DATA_DIR", str(tmp_path))
        from recommendation_engine import get_multi_arm_recommendations, ArmHonestLabel
        with patch("strategies.index_replication_floor.build_position_batches", return_value=[]):
            recs = get_multi_arm_recommendations(paper_portfolio=mock_pp)
        arms = {r.arm: r for r in recs}
        assert arms["limitup"].honest_label == ArmHonestLabel.MOCK_NOT_READY
        assert arms["trend"].honest_label == ArmHonestLabel.MOCK_NOT_READY
        assert arms["limitup"].action_type == "none"

    def test_floor_reads_equity_r10_wiring(self, tmp_path, monkeypatch, mock_pp):
        """R9↔R10 接线（SH1 fix）：floor sizing 读 PaperPortfolio.equity()（非空转）。"""
        monkeypatch.setenv("VR_DATA_DIR", str(tmp_path))
        from recommendation_engine import get_multi_arm_recommendations
        mock_pp.equity.return_value = 200000.0
        with patch("strategies.index_replication_floor.build_position_batches",
                   return_value=[{"batch_idx": i} for i in range(4)]):
            recs = get_multi_arm_recommendations(paper_portfolio=mock_pp)
        floor = next(r for r in recs if r.arm == "floor")
        mock_pp.equity.assert_called()  # R9 读 equity（R10 接线，非空转）
        assert "200000" in floor.sizing_suggestion

    def test_returns_five_arms(self, tmp_path, monkeypatch, mock_pp):
        """返 floor/breakout/limitup/trend/gap 5 臂。"""
        monkeypatch.setenv("VR_DATA_DIR", str(tmp_path))
        from recommendation_engine import get_multi_arm_recommendations
        with patch("strategies.index_replication_floor.build_position_batches", return_value=[]):
            recs = get_multi_arm_recommendations(paper_portfolio=mock_pp)
        arms = {r.arm for r in recs}
        assert arms == {"floor", "breakout", "limitup", "trend", "gap"}
