# -*- coding: utf-8 -*-
"""S059：因子 IC 评估——_calc_factor_ic 纯函数 + 端点扩展 + BacktestResult 字段。

续 S043 模式：同 scatter、同端点、同 Tab。纯标准库实现 Pearson + Spearman 秩相关，
样本<20 返 None（诚实标注，不补零）。
"""

from backtest_lite import (
    BacktestResult,
    _calc_factor_ic,
)


def _p(factor: float, ret: float) -> dict:
    return {"factor_premium_rate": factor, "next_day_return": ret}


class TestCalcFactorIc:
    def test_perfect_positive_correlation(self):
        scatter = [{"factor_premium_rate": float(i), "next_day_return": float(i) * 0.01} for i in range(20)]
        result = _calc_factor_ic(scatter, "factor_premium_rate")
        assert result is not None
        assert result["n"] == 20
        assert abs(result["ic"] - 1.0) < 1e-4
        assert abs(result["rank_ic"] - 1.0) < 1e-4

    def test_perfect_negative_correlation(self):
        scatter = [
            {"factor_premium_rate": float(i), "next_day_return": float(19 - i) * 0.01}
            for i in range(20)
        ]
        result = _calc_factor_ic(scatter, "factor_premium_rate")
        assert result is not None
        assert abs(result["ic"] + 1.0) < 1e-4
        assert abs(result["rank_ic"] + 1.0) < 1e-4

    def test_zero_correlation_orthogonal(self):
        # x 单调递增，y 交替正负——期望 IC 接近 0
        n = 40
        scatter = [
            {"factor_premium_rate": float(i), "next_day_return": 0.05 if i % 2 == 0 else -0.05}
            for i in range(n)
        ]
        result = _calc_factor_ic(scatter, "factor_premium_rate")
        assert result is not None
        assert result["n"] == n
        assert abs(result["ic"]) < 0.3
        assert abs(result["rank_ic"]) < 0.3

    def test_small_sample_returns_none(self):
        scatter = [_p(float(i), 0.01) for i in range(19)]
        result = _calc_factor_ic(scatter, "factor_premium_rate")
        assert result is None

    def test_missing_factor_value_excluded(self):
        pairs = [_p(float(i), float(i) * 0.01) for i in range(25)]
        pairs[5] = {"next_day_return": 0.01}  # 缺 factor_premium_rate
        result = _calc_factor_ic(pairs, "factor_premium_rate")
        assert result is not None
        assert result["n"] == 24

    def test_missing_return_excluded(self):
        pairs = [_p(float(i), float(i) * 0.01) for i in range(25)]
        pairs[5] = {"factor_premium_rate": 50.0}  # 缺 next_day_return
        result = _calc_factor_ic(pairs, "factor_premium_rate")
        assert result is not None
        assert result["n"] == 24

    def test_ties_use_average_rank(self):
        # 并列值用平均秩——对 Spearman 稳健
        scatter = [
            {"factor_premium_rate": 50.0, "next_day_return": 0.01},
            {"factor_premium_rate": 50.0, "next_day_return": 0.01},
            {"factor_premium_rate": 50.0, "next_day_return": 0.01},
        ] * 10  # 30 对完全并列
        result = _calc_factor_ic(scatter, "factor_premium_rate")
        assert result is not None
        # 变异为 0 → denom=0 → IC 兜底 0.0
        assert result["ic"] == 0.0
        assert result["rank_ic"] == 0.0

    def test_empty_scatter_returns_none(self):
        assert _calc_factor_ic([], "factor_premium_rate") is None

    def test_rounding_to_4_decimal(self):
        scatter = [{"factor_premium_rate": float(i), "next_day_return": float(i) * 0.001} for i in range(25)]
        result = _calc_factor_ic(scatter, "factor_premium_rate")
        assert result is not None
        # round(..., 4) 后小数位数 ≤ 4
        for key in ("ic", "rank_ic"):
            val = result[key]
            assert round(val, 4) == val


class TestBacktestResultField:
    def test_factor_ic_analysis_default_none(self):
        r = BacktestResult(
            period="2026-01-01 ~ 2026-01-31",
            total_signals=1,
            hit_count=1,
            hit_rate=1.0,
            avg_return=0.01,
            max_drawdown=0.0,
            sharpe_ratio=0.0,
            scatter_data=[],
            percentile_analysis={},
        )
        assert r.factor_ic_analysis is None

    def test_factor_ic_analysis_populated(self):
        ic = {"ic": 0.123, "rank_ic": 0.234, "n": 100}
        r = BacktestResult(
            period="2026-01-01 ~ 2026-01-31",
            total_signals=1,
            hit_count=1,
            hit_rate=1.0,
            avg_return=0.01,
            max_drawdown=0.0,
            sharpe_ratio=0.0,
            scatter_data=[],
            percentile_analysis={},
            factor_ic_analysis=ic,
        )
        assert r.factor_ic_analysis == ic


# ===========================================================================
# 端点扩展：GET /api/backtest/factor-analysis 响应并入 ic_analysis
# ===========================================================================


class TestFactorAnalysisIcEndpoint:
    def _scatter_large(self):
        # 30 对正相关样本，够 n>=20 阈值
        return [
            {"factor_premium_rate": float(i) * 3, "next_day_return": float(i) * 0.002, "code": f"c{i}", "date": "2026-08-01"}
            for i in range(30)
        ]

    def _scatter_tiny(self):
        # 5 对样本——不够 n>=20 阈值，ic_analysis 应为 null
        return [
            {"factor_premium_rate": float(i) * 3, "next_day_return": 0.01, "code": f"c{i}", "date": "2026-08-01"}
            for i in range(5)
        ]

    def test_ic_analysis_present_when_sample_sufficient(self, monkeypatch, isolated_market_db):
        from fastapi.testclient import TestClient
        import app as appmod
        import routers.backtest as bt_router

        async def _fake_scatter(date_range):
            return self._scatter_large()

        monkeypatch.setattr(bt_router, "generate_scatter_data", _fake_scatter)

        client = TestClient(appmod.app)
        r = client.get(
            "/api/backtest/factor-analysis",
            params={"start": "2026-08-01", "end": "2026-08-05", "factor": "premium_rate"},
        )
        assert r.status_code == 200, r.text
        data = r.json()["data"]
        assert "ic_analysis" in data
        ic = data["ic_analysis"]
        assert ic is not None
        assert set(ic.keys()) == {"ic", "rank_ic", "n"}
        assert ic["n"] == 30

    def test_ic_analysis_null_when_sample_insufficient(self, monkeypatch, isolated_market_db):
        from fastapi.testclient import TestClient
        import app as appmod
        import routers.backtest as bt_router

        async def _fake_scatter(date_range):
            return self._scatter_tiny()

        monkeypatch.setattr(bt_router, "generate_scatter_data", _fake_scatter)

        client = TestClient(appmod.app)
        r = client.get(
            "/api/backtest/factor-analysis",
            params={"start": "2026-08-01", "end": "2026-08-05", "factor": "premium_rate"},
        )
        assert r.status_code == 200, r.text
        data = r.json()["data"]
        assert data["ic_analysis"] is None
