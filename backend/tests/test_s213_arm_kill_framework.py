# -*- coding: utf-8 -*-
"""S213 arm 级 kill switch 框架测试——arm_status 表 + lift_for_arm 读 override。

TDD：覆盖
  T1 arm_status 表建 + query/set（upsert + None 默认）
  T2 lift_for_arm override 优先：is_active=False 返 0.0 / weight_override 优先 / 默认走 registry
"""
import sys
from pathlib import Path
from unittest.mock import patch

import pytest

backend_dir = Path(__file__).resolve().parent.parent
if str(backend_dir) not in sys.path:
    sys.path.insert(0, str(backend_dir))


@pytest.fixture(autouse=True)
def _x1dot0_unlock_env(monkeypatch):
    """×1.0 unlock env 许可——bull regime_caps=1.0 须 VR_ALLOW_X1DOT0=1（deploy 时设）。

    S213 测 arm kill switch（override 优先级）非 ×1.0 unlock verdict 本身（后者在
    test_s218_freeze_guard 测）。此 fixture 模拟 deploy 时 env 许可，让 default/db-error
    fallback 走 registry bull=×1.0 路径在 test 环境（env 未设）下生效，防 freeze guard 降级 ×0.75。
    """
    monkeypatch.setenv("VR_ALLOW_X1DOT0", "1")


# ── T1 arm_status 表 + query/set ─────────────────────────────────────────


class TestArmStatusTable:
    def test_query_arm_status_none_default(self, tmp_path):
        """无记录返 None（=active，走 registry 默认）。"""
        from engine.trade_journal import TradeJournal
        tj = TradeJournal(db_path=tmp_path / "test.db")
        assert tj.query_arm_status("consecutive_relay") is None

    def test_set_arm_status_inactive_upsert(self, tmp_path):
        """set is_active=False → query 返 is_active=False + kill_reason + killed_at。"""
        from engine.trade_journal import TradeJournal
        tj = TradeJournal(db_path=tmp_path / "test.db")
        tj.set_arm_status("consecutive_relay", is_active=False, kill_reason="连亏5笔")
        s = tj.query_arm_status("consecutive_relay")
        assert s is not None
        assert s["is_active"] is False
        assert s["kill_reason"] == "连亏5笔"
        assert s["killed_at"] is not None

    def test_set_arm_status_weight_override(self, tmp_path):
        """set weight_override=0.1 → query 返 weight_override=0.1。"""
        from engine.trade_journal import TradeJournal
        tj = TradeJournal(db_path=tmp_path / "test.db")
        tj.set_arm_status("breakout", is_active=True, weight_override=0.1, kill_reason="provisional降权")
        s = tj.query_arm_status("breakout")
        assert s is not None
        assert s["is_active"] is True
        assert s["weight_override"] == 0.1
        assert s["killed_at"] is None  # active 时 killed_at=None

    def test_set_arm_status_upsert_overwrite(self, tmp_path):
        """重复 set 同 arm → upsert 覆盖（不插重复）。"""
        from engine.trade_journal import TradeJournal
        tj = TradeJournal(db_path=tmp_path / "test.db")
        tj.set_arm_status("trend", is_active=True, weight_override=0.5)
        tj.set_arm_status("trend", is_active=False, kill_reason="forward net_mean<0")
        s = tj.query_arm_status("trend")
        assert s["is_active"] is False
        assert s["kill_reason"] == "forward net_mean<0"
        # ON CONFLICT 更新 weight_override=excluded.weight_override；第二次 set 未传 → None 覆盖
        assert s["weight_override"] is None


# ── T2 lift_for_arm override 优先 ────────────────────────────────────────


class TestLiftForArmOverride:
    def test_lift_for_arm_inactive_returns_zero(self):
        """is_active=False → lift_for_arm 返 0.0（kill switch 生效，停交易）。"""
        from candidate_funnel.evaluation import lift_for_arm
        fake = {"arm": "consecutive_relay", "is_active": False,
                "weight_override": None, "kill_reason": "连亏5笔", "killed_at": "now"}
        with patch("engine.trade_journal.TradeJournal.query_arm_status", return_value=fake):
            mult, note = lift_for_arm("consecutive_relay", regime="bull")
        assert mult == 0.0
        assert "arm kill" in note

    def test_lift_for_arm_weight_override_priority(self):
        """weight_override 设值 → 优先于 registry（provisional 降权 / 手动 override）。"""
        from candidate_funnel.evaluation import lift_for_arm
        fake = {"arm": "consecutive_relay", "is_active": True,
                "weight_override": 0.1, "kill_reason": None, "killed_at": None}
        with patch("engine.trade_journal.TradeJournal.query_arm_status", return_value=fake):
            mult, note = lift_for_arm("consecutive_relay", regime="bull")
        assert mult == 0.1
        assert "arm override" in note

    def test_lift_for_arm_default_walks_registry(self):
        """无 arm_status（query 返 None）→ lift_for_arm 走 registry（consecutive_relay bull ×1.0 unlock）。"""
        from candidate_funnel.evaluation import lift_for_arm
        with patch("engine.trade_journal.TradeJournal.query_arm_status", return_value=None):
            mult, _ = lift_for_arm("consecutive_relay", regime="bull")
        assert mult == 1.0  # registry bull ×1.0（2026-09-19 ×1.0 unlock，bear chrono 三条件 MET）

    def test_lift_for_arm_db_error_falls_back_to_registry(self):
        """arm_status 读失败（表未建/db 异常）→ 走 registry fallback（不阻塞，backward compat）。"""
        from candidate_funnel.evaluation import lift_for_arm
        with patch("engine.trade_journal.TradeJournal.query_arm_status", side_effect=Exception("db error")):
            mult, _ = lift_for_arm("consecutive_relay", regime="bull")
        assert mult == 1.0  # fallback registry bull ×1.0（×1.0 unlock）
