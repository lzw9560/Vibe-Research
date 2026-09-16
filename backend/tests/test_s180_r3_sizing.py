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
    """T4（S209 §4）：PaperPortfolio.final_size 4-layer = arm×port×lift×intraday。

    mock DrawdownBreaker.size_multiplier/portfolio_multiplier 返 1.0（underpowered），
    验 lift_for_arm 真接通（§44 cap 真咬仓位，不再是 decorative）。
    """

    def _make_pp(self, monkeypatch):
        from engine.paper_portfolio import PaperPortfolio
        pp = PaperPortfolio()
        monkeypatch.setattr(pp._breaker, "size_multiplier", lambda arm=None: (1.0, "ok"))
        monkeypatch.setattr(pp._breaker, "portfolio_multiplier", lambda: (1.0, "ok"))
        return pp

    def test_final_size_breakout_applies_lift_cap(self, tmp_path, monkeypatch):
        """breakout lift_for_arm=0.5 → final_size = 10000 × 1.0 × 1.0 × 0.5 × 1.0 = 5000。"""
        pp = self._make_pp(monkeypatch)
        result = pp.final_size("breakout", 10000)
        assert result == 5000, f"breakout lift=0.5 应 halve，got {result}"

    def test_final_size_floor_lift_1(self, tmp_path, monkeypatch):
        """floor lift=1.0（N/A cap 不作用）→ final_size 不缩。"""
        pp = self._make_pp(monkeypatch)
        result = pp.final_size("floor", 5000)
        assert result == 5000, f"floor lift=1.0 应不缩，got {result}"

    def test_final_size_explicit_lift_override(self, tmp_path, monkeypatch):
        """显式传 lift_multiplier=0.1 覆盖 lift_for_arm。"""
        pp = self._make_pp(monkeypatch)
        result = pp.final_size("breakout", 10000, lift_multiplier=0.1)
        assert result == 1000, f"显式 lift=0.1 应 ×0.1，got {result}"

    def test_final_size_intraday_zero_blocks_trade(self, tmp_path, monkeypatch):
        """T4 第 4 层 intraday_mult=0 → final_size=0（禁交易，吃大面熔断）。"""
        pp = self._make_pp(monkeypatch)
        result = pp.final_size("breakout", 10000, intraday_mult=0.0)
        assert result == 0, f"intraday_mult=0 应禁交易，got {result}"

    def test_final_size_intraday_half(self, tmp_path, monkeypatch):
        """T4 第 4 层 intraday_mult=0.5 → final_size 再 ×0.5。"""
        pp = self._make_pp(monkeypatch)
        # 10000 × 1.0 × 1.0 × 0.5(lift) × 0.5(intraday) = 2500
        result = pp.final_size("breakout", 10000, intraday_mult=0.5)
        assert result == 2500, f"intraday=0.5 应再 halve，got {result}"

    def test_final_size_arm_mult_bites(self, tmp_path, monkeypatch):
        """arm_mult（per-arm DD）→ final_size 缩（DrawdownBreaker.size_multiplier 0.5）。"""
        from engine.paper_portfolio import PaperPortfolio
        pp = PaperPortfolio()
        monkeypatch.setattr(pp._breaker, "size_multiplier", lambda arm=None: (0.5, "enforced"))
        monkeypatch.setattr(pp._breaker, "portfolio_multiplier", lambda: (1.0, "ok"))
        # 10000 × 0.5(arm) × 1.0(port) × 0.5(lift) × 1.0(intraday) = 2500
        result = pp.final_size("breakout", 10000)
        assert result == 2500, f"arm_mult=0.5 应缩，got {result}"
