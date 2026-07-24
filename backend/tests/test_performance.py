"""Phase 5 性能测试。

验证：
1. 全市场涨停基因分析 < 3 分钟
2. 个股策略分析 < 30 秒
3. 竞价选股分析 < 2 分钟
4. 席位画像构建 < 5 分钟
"""
from __future__ import annotations

import time

import pytest
from fastapi.testclient import TestClient

import app as app_module

client = TestClient(app_module.app)

SCREENER_TIMEOUT = 180  # 3 分钟
ANALYSIS_TIMEOUT = 30   # 30 秒
AUCTION_TIMEOUT = 120   # 2 分钟
SEATS_TIMEOUT = 300     # 5 分钟


class TestPerformance:
    def test_screener_performance(self):
        """全市场涨停基因分析应在 3 分钟内完成。"""
        start = time.time()
        r = client.get("/api/limitup/screener")
        elapsed = time.time() - start
        if r.status_code == 502:
            pytest.skip("数据源不可用，跳过性能测试")
        assert r.status_code == 200, f"screener 失败: {r.text}"
        assert elapsed < SCREENER_TIMEOUT, f"screener 耗时 {elapsed:.1f}s，超过 {SCREENER_TIMEOUT}s"

    def test_analysis_performance(self):
        """个股策略分析应在 30 秒内完成。"""
        start = time.time()
        r = client.get("/api/limitup/analysis/600519")
        elapsed = time.time() - start
        if r.status_code == 502:
            pytest.skip("数据源不可用，跳过性能测试")
        assert r.status_code == 200, f"analysis 失败: {r.text}"
        assert elapsed < ANALYSIS_TIMEOUT, f"analysis 耗时 {elapsed:.1f}s，超过 {ANALYSIS_TIMEOUT}s"

    def test_auction_performance(self):
        """竞价选股分析应在 2 分钟内完成。"""
        start = time.time()
        r = client.get("/api/limitup/auction/top")
        elapsed = time.time() - start
        if r.status_code == 502:
            pytest.skip("数据源不可用，跳过性能测试")
        assert r.status_code == 200, f"auction 失败: {r.text}"
        assert elapsed < AUCTION_TIMEOUT, f"auction 耗时 {elapsed:.1f}s，超过 {AUCTION_TIMEOUT}s"

    def test_seats_build_performance(self):
        """席位画像构建应在 5 分钟内完成。"""
        start = time.time()
        r = client.post("/api/limitup/seats/build?lookback_days=30")
        elapsed = time.time() - start
        if r.status_code == 502:
            pytest.skip("数据源不可用，跳过性能测试")
        assert r.status_code == 200, f"seats build 失败: {r.text}"
        assert elapsed < SEATS_TIMEOUT, f"seats build 耗时 {elapsed:.1f}s，超过 {SEATS_TIMEOUT}s"

    def test_metrics_performance(self):
        """涨停策略聚合指标应在 30 秒内完成。"""
        start = time.time()
        r = client.get("/api/limitup/metrics")
        elapsed = time.time() - start
        if r.status_code == 502:
            pytest.skip("数据源不可用，跳过性能测试")
        assert r.status_code == 200, f"metrics 失败: {r.text}"
        assert elapsed < 30, f"metrics 耗时 {elapsed:.1f}s，超过 30s"


class TestWorkflowPerformance:
    def test_workflow_status_latency(self):
        """工作流状态查询应在 5 秒内完成。"""
        start = time.time()
        r = client.get("/api/workflow/status")
        elapsed = time.time() - start
        assert r.status_code == 200, f"workflow status 失败: {r.text}"
        assert elapsed < 5, f"workflow status 耗时 {elapsed:.1f}s，超过 5s"

    def test_workflow_signals_latency(self):
        """实时交易信号查询应在 5 秒内完成。"""
        start = time.time()
        r = client.get("/api/workflow/signals")
        elapsed = time.time() - start
        assert r.status_code == 200, f"workflow signals 失败: {r.text}"
        assert elapsed < 5, f"workflow signals 耗时 {elapsed:.1f}s，超过 5s"

    def test_workflow_alerts_latency(self):
        """炸板预警查询应在 5 秒内完成。"""
        start = time.time()
        r = client.get("/api/workflow/alerts")
        elapsed = time.time() - start
        assert r.status_code == 200, f"workflow alerts 失败: {r.text}"
        assert elapsed < 5, f"workflow alerts 耗时 {elapsed:.1f}s，超过 5s"

    def test_workflow_win_rate_latency(self):
        """胜率统计查询应在 5 秒内完成。"""
        start = time.time()
        r = client.get("/api/workflow/win-rate")
        elapsed = time.time() - start
        assert r.status_code == 200, f"workflow win-rate 失败: {r.text}"
        assert elapsed < 5, f"workflow win-rate 耗时 {elapsed:.1f}s，超过 5s"
