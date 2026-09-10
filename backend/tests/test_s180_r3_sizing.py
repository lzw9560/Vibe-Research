# -*- coding: utf-8 -*-
"""S180 R3-R4: r3 sizing 接线测试。lift_for_arm + paper_portfolio.final_size 接 lift_to_multiplier。"""
import sys
from pathlib import Path

backend_dir = Path(__file__).resolve().parent.parent
if str(backend_dir) not in sys.path:
    sys.path.insert(0, str(backend_dir))


class TestLiftForArm:
    def test_breakout_days_lt_60_halves(self):
        """breakout 维度 days<60 → ×0.5（provisional cap）。"""
        from candidate_funnel.evaluation import lift_for_arm, DIMENSION_LIFT_REGISTRY
        d = DIMENSION_LIFT_REGISTRY.get("breakout")
        assert d is not None and d.days_robust < 60, "breakout 维度应 days<60"
        mult, note = lift_for_arm("breakout")
        assert mult == 0.5, f"breakout days<60 应 ×0.5，got {mult}（{note}）"

    def test_floor_na_returns_1(self):
        """floor N/A → 1.0 cap 不作用。"""
        from candidate_funnel.evaluation import lift_for_arm
        mult, note = lift_for_arm("floor")
        assert mult == 1.0, f"floor N/A 应 1.0，got {mult}（{note}）"
        assert "N/A" in note

    def test_gap_dead_arm_returns_1(self):
        """gap dead_arm → 1.0（不 sizing）。"""
        from candidate_funnel.evaluation import lift_for_arm
        mult, _ = lift_for_arm("gap")
        assert mult == 1.0

    def test_unknown_arm_returns_1(self):
        """未知臂 → 1.0（保守不误杀）。"""
        from candidate_funnel.evaluation import lift_for_arm
        mult, _ = lift_for_arm("nonexistent_arm")
        assert mult == 1.0


class TestPaperPortfolioFinalSizeWiring:
    def _make_pp(self, monkeypatch):
        from engine.paper_portfolio import PaperPortfolio
        return PaperPortfolio()

    def test_final_size_breakout_applies_lift_cap(self, tmp_path, monkeypatch):
        """paper_portfolio.final_size('breakout',...) 默认 None → 调 lift_for_arm ×0.5。"""
        pp = self._make_pp(monkeypatch)
        captured = {}

        def fake_final_size(arm, arm_size, lift_multiplier):
            captured["arm"] = arm
            captured["lift_multiplier"] = lift_multiplier
            return arm_size * lift_multiplier

        monkeypatch.setattr(pp._breaker, "final_size", fake_final_size)
        result = pp.final_size("breakout", 10000)
        assert captured["lift_multiplier"] == 0.5, f"breakout 应调 lift_for_arm ×0.5，got {captured['lift_multiplier']}"
        assert result == 5000  # 10000 × 0.5

    def test_final_size_floor_lift_1(self, tmp_path, monkeypatch):
        """floor final_size lift_multiplier=1.0（N/A cap 不作用）。"""
        pp = self._make_pp(monkeypatch)
        captured = {}

        def fake_final_size(arm, arm_size, lift_multiplier):
            captured["lift_multiplier"] = lift_multiplier
            return arm_size * lift_multiplier

        monkeypatch.setattr(pp._breaker, "final_size", fake_final_size)
        pp.final_size("floor", 5000)
        assert captured["lift_multiplier"] == 1.0

    def test_final_size_explicit_lift_override(self, tmp_path, monkeypatch):
        """显式传 lift_multiplier 覆盖 lift_for_arm。"""
        pp = self._make_pp(monkeypatch)
        captured = {}

        def fake_final_size(arm, arm_size, lift_multiplier):
            captured["lift_multiplier"] = lift_multiplier
            return arm_size * lift_multiplier

        monkeypatch.setattr(pp._breaker, "final_size", fake_final_size)
        pp.final_size("breakout", 10000, lift_multiplier=0.1)
        assert captured["lift_multiplier"] == 0.1
