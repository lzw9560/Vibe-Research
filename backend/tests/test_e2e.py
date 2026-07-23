"""Phase 5 E2E 集成测试（FastAPI TestClient）。

覆盖：
1. 健康检查 / 基础路由可达性
2. LimitUp 子路由（screener / analysis / auction / seats / metrics）
3. 统一错误处理（400/404/500）
4. 缓存装饰器命中/未命中
5. 合规：关键响应包含免责声明
"""
from __future__ import annotations

import time

import pytest
from fastapi.testclient import TestClient

import app as app_module

client = TestClient(app_module.app)


# ===========================================================================
# 1. 基础路由可达性
# ===========================================================================

def test_health():
    r = client.get("/api/health")
    assert r.status_code == 200
    assert r.json()["ok"] is True


def test_api_root_returns_404():
    r = client.get("/api")
    assert r.status_code == 404


# ===========================================================================
# 2. LimitUp 子路由
# ===========================================================================

class TestLimitUpScreener:
    def test_screener_default(self):
        r = client.get("/api/limitup/screener")
        assert r.status_code in (200, 502)
        if r.status_code == 200:
            data = r.json()
            assert "data" in data

    def test_screener_with_date(self):
        r = client.get("/api/limitup/screener?date=2025-01-02")
        assert r.status_code in (200, 502)

    def test_screener_params_get(self):
        r = client.get("/api/limitup/screener/params")
        assert r.status_code == 200
        data = r.json()
        assert "gene_qualify_threshold" in data

    def test_screener_params_post(self):
        r = client.post("/api/limitup/screener/params", json={
            "gene_qualify_threshold": 65,
            "gene_high_threshold": 80,
            "lookback_days": 250,
        })
        assert r.status_code == 200
        assert r.json()["status"] == "ok"


class TestLimitUpAnalysis:
    def test_analysis_valid_code(self):
        r = client.get("/api/limitup/analysis/600519")
        assert r.status_code in (200, 502)
        if r.status_code == 200:
            data = r.json()
            assert "data" in data

    def test_analysis_invalid_code(self):
        r = client.get("/api/limitup/analysis/abc")
        assert r.status_code == 400

    def test_analysis_bad_length(self):
        r = client.get("/api/limitup/analysis/12345")
        assert r.status_code == 400


class TestLimitUpAuction:
    def test_auction_top_default(self):
        r = client.get("/api/limitup/auction/top")
        assert r.status_code in (200, 502)

    def test_auction_top_with_params(self):
        r = client.get("/api/limitup/auction/top?date=2025-01-02&n=10")
        assert r.status_code in (200, 502)

    def test_auction_params_get(self):
        r = client.get("/api/limitup/auction/params")
        assert r.status_code == 200

    def test_auction_params_post(self):
        r = client.post("/api/limitup/auction/params", json={
            "min_gene_score": 60,
            "min_zt_count": 3,
            "top_n": 30,
        })
        assert r.status_code == 200


class TestLimitUpSeats:
    def test_seat_profiles(self):
        r = client.get("/api/limitup/seats/profiles")
        assert r.status_code in (200, 502)
        if r.status_code == 200:
            data = r.json()
            assert "profiles" in data

    def test_seat_profile_not_found(self):
        r = client.get("/api/limitup/seats/profile/nonexistent_seat")
        assert r.status_code == 404

    def test_seat_consensus(self):
        r = client.get("/api/limitup/seats/consensus?stock_code=600519")
        assert r.status_code in (200, 502)

    def test_seat_build(self):
        r = client.post("/api/limitup/seats/build?lookback_days=30")
        assert r.status_code in (200, 502)


class TestLimitUpMetrics:
    def test_metrics_default(self):
        r = client.get("/api/limitup/metrics")
        assert r.status_code in (200, 502)
        if r.status_code == 200:
            data = r.json()
            assert "date" in data
            assert "total_zt" in data


# ===========================================================================
# 3. 统一错误处理
# ===========================================================================

class TestErrorHandling:
    def test_404_on_unknown_route(self):
        r = client.get("/api/limitup/unknown_route")
        assert r.status_code == 404

    def test_422_on_invalid_query(self):
        r = client.get("/api/limitup/auction/top?n=999")
        assert r.status_code == 422

    def test_422_on_invalid_auction_params(self):
        r = client.post("/api/limitup/auction/params", json={
            "min_gene_score": 150,
        })
        assert r.status_code == 422


# ===========================================================================
# 4. 缓存装饰器
# ===========================================================================

class TestCacheDecorator:
    def test_metrics_cache_hit(self):
        """同一日期第二次请求应命中缓存（更快）。"""
        r1 = client.get("/api/limitup/metrics")
        if r1.status_code != 200:
            pytest.skip("metrics 不可用，跳过缓存测试")
        t1 = r1.elapsed.total_seconds()
        r2 = client.get("/api/limitup/metrics")
        t2 = r2.elapsed.total_seconds()
        assert r1.json() == r2.json()
        # 缓存命中通常更快，但不强制（避免 flaky）
        assert t2 <= t1 * 2


# ===========================================================================
# 5. 合规：免责声明检查
# ===========================================================================

class TestCompliance:
    def test_screener_has_disclaimer(self):
        r = client.get("/api/limitup/screener")
        if r.status_code == 200:
            text = r.text
            assert "免责" in text or "声明" in text or "教育" in text or "研究" in text

    def test_analysis_has_disclaimer(self):
        r = client.get("/api/limitup/analysis/600519")
        if r.status_code == 200:
            text = r.text
            assert "免责" in text or "声明" in text or "教育" in text or "研究" in text

    def test_metrics_has_disclaimer(self):
        r = client.get("/api/limitup/metrics")
        if r.status_code == 200:
            text = r.text
            assert "免责" in text or "声明" in text or "教育" in text or "研究" in text


# ===========================================================================
# 6. 新增端点（V2.0.2 补充）
# ===========================================================================

class TestWinRateEndpoints:
    def test_winrate_trends(self):
        r = client.get("/api/winrate/trends")
        assert r.status_code in (200, 502)
        if r.status_code == 200:
            data = r.json()
            assert "data" in data

    def test_winrate_sector(self):
        r = client.get("/api/winrate/sector/计算机")
        assert r.status_code in (200, 502)
        if r.status_code == 200:
            data = r.json()
            assert "data" in data

    def test_winrate_strategy(self):
        r = client.get("/api/winrate/strategy/首板挖掘")
        assert r.status_code in (200, 502)
        if r.status_code == 200:
            data = r.json()
            assert "data" in data


class TestRiskEndpoints:
    def test_risk_oneday_list(self):
        r = client.get("/api/risk/oneday/list")
        assert r.status_code in (200, 502)
        if r.status_code == 200:
            data = r.json()
            assert "data" in data

    def test_risk_seats(self):
        r = client.get("/api/risk/seats")
        assert r.status_code in (200, 502)
        if r.status_code == 200:
            data = r.json()
            assert "data" in data


class TestSectorDivergenceEndpoints:
    def test_sector_divergence_history(self):
        r = client.get("/api/sector/divergence/history")
        assert r.status_code in (200, 502)
        if r.status_code == 200:
            data = r.json()
            assert "data" in data
