# -*- coding: utf-8 -*-
"""S043 阶段 A+B：泛化因子分位分析 + scatter 因子扩展 + BacktestResult 新字段。"""

from backtest_lite import (
    BacktestResult,
    _PREMIUM_BUCKETS,
    _GENE_SCORE_BUCKETS,
    _calc_factor_percentile_analysis,
    _calc_percentile_analysis,
)


def _p(factor: float, ret: float) -> dict:
    return {"factor_x": factor, "next_day_return": ret}


class TestCalcFactorPercentileAnalysis:
    def test_gene_score_three_bucket_split(self):
        scatter = [
            {"gene_score": 80, "next_day_return": 0.05},
            {"gene_score": 65, "next_day_return": -0.02},
            {"gene_score": 50, "next_day_return": 0.01},
        ]
        result = _calc_factor_percentile_analysis(scatter, "gene_score", _GENE_SCORE_BUCKETS)
        assert set(result) == {"0-60", "60-75", "75-100"}
        assert result["75-100"]["count"] == 1
        assert result["60-75"]["count"] == 1
        assert result["0-60"]["count"] == 1

    def test_premium_four_bucket_split(self):
        scatter = [_p(v, 0.01) for v in (10, 40, 60, 80)]
        result = _calc_factor_percentile_analysis(scatter, "factor_x", _PREMIUM_BUCKETS)
        counts = [result[k]["count"] for k in ("0-30", "30-50", "50-70", "70-100")]
        assert counts == [1, 1, 1, 1]

    def test_boundary_belongs_to_upper_bucket(self):
        # 半开区间 [lo, hi)：v == 边界归入上一档
        result = _calc_factor_percentile_analysis([_p(50.0, 0.02)], "factor_x", _PREMIUM_BUCKETS)
        assert result["30-50"]["count"] == 0
        assert result["50-70"]["count"] == 1

    def test_right_endpoint_inf_bucket(self):
        result = _calc_factor_percentile_analysis([_p(100.0, 0.03)], "factor_x", _PREMIUM_BUCKETS)
        assert result["70-100"]["count"] == 1

    def test_missing_field_defaults_zero_low_bucket(self):
        result = _calc_factor_percentile_analysis([{"next_day_return": 0.01}], "factor_x", _PREMIUM_BUCKETS)
        assert result["0-30"]["count"] == 1

    def test_empty_scatter_all_buckets_zero(self):
        result = _calc_factor_percentile_analysis([], "factor_x", _PREMIUM_BUCKETS)
        assert len(result) == 4
        assert all(v == {"count": 0, "avg_return": 0.0, "hit_rate": 0.0} for v in result.values())

    def test_metrics_calculation(self):
        scatter = [_p(80, 0.04), _p(82, -0.02), _p(79, 0.02)]
        b = _calc_factor_percentile_analysis(scatter, "factor_x", _PREMIUM_BUCKETS)["70-100"]
        assert b["count"] == 3
        assert b["avg_return"] == round((0.04 - 0.02 + 0.02) / 3, 4)
        assert b["hit_rate"] == round(2 / 3, 4)

    def test_legacy_wrapper_behavior_unchanged(self):
        scatter = [
            {"gene_score": 90, "next_day_return": 0.06},
            {"gene_score": 70, "next_day_return": -0.01},
            {"gene_score": 40, "next_day_return": 0.0},
        ]
        result = _calc_percentile_analysis(scatter)
        assert set(result) == {"0-60", "60-75", "75-100"}
        assert result["75-100"] == {"count": 1, "avg_return": 0.06, "hit_rate": 1.0}
        assert result["60-75"]["count"] == 1
        # 0.0 不 >0，不算命中（与原实现一致）
        assert result["0-60"]["hit_rate"] == 0.0


class TestBacktestResult:
    def test_new_field_default_none_backward_compatible(self):
        # 旧缓存（无 factor_percentile_analysis 键）反序列化不报错
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
        assert r.factor_percentile_analysis is None


# ===========================================================================
# R4：GET /api/backtest/factor-analysis 端点（mock generate_scatter_data，不碰外部源）
# ===========================================================================


class TestFactorAnalysisEndpoint:
    def _scatter(self):
        return [
            {"factor_premium_rate": 80, "next_day_return": 0.04, "code": "a", "date": "2026-08-01"},
            {"factor_premium_rate": 82, "next_day_return": -0.02, "code": "b", "date": "2026-08-01"},
            {"factor_premium_rate": 10, "next_day_return": 0.01, "code": "c", "date": "2026-08-02"},
        ]

    def test_returns_four_buckets(self, monkeypatch, isolated_market_db):
        from fastapi.testclient import TestClient
        import app as appmod
        import routers.backtest as bt_router

        async def _fake_scatter(date_range):
            return self._scatter()

        monkeypatch.setattr(bt_router, "generate_scatter_data", _fake_scatter)

        client = TestClient(appmod.app)
        r = client.get(
            "/api/backtest/factor-analysis",
            params={"start": "2026-08-01", "end": "2026-08-05", "factor": "premium_rate"},
        )
        assert r.status_code == 200, r.text
        data = r.json()["data"]
        assert data["factor"] == "premium_rate"
        assert data["period"] == "2026-08-01 ~ 2026-08-05"
        assert data["sample_size"] == 3
        assert set(data["buckets"]) == {"0-30", "30-50", "50-70", "70-100"}
        hi = data["buckets"]["70-100"]
        assert hi["count"] == 2
        assert hi["avg_return"] == round((0.04 - 0.02) / 2, 4)
        assert hi["hit_rate"] == 0.5

    def test_factor_default_premium_rate(self, monkeypatch, isolated_market_db):
        from fastapi.testclient import TestClient
        import app as appmod
        import routers.backtest as bt_router

        async def _fake_scatter(date_range):
            return self._scatter()

        monkeypatch.setattr(bt_router, "generate_scatter_data", _fake_scatter)

        client = TestClient(appmod.app)
        r = client.get(
            "/api/backtest/factor-analysis",
            params={"start": "2026-08-01", "end": "2026-08-05"},
        )
        assert r.status_code == 200, r.text
        assert r.json()["data"]["factor"] == "premium_rate"

    def test_unknown_factor_400(self, isolated_market_db):
        from fastapi.testclient import TestClient
        import app as appmod

        client = TestClient(appmod.app)
        r = client.get(
            "/api/backtest/factor-analysis",
            params={"start": "2026-08-01", "end": "2026-08-05", "factor": "bogus"},
        )
        assert r.status_code == 400
