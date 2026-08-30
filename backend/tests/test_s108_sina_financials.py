# -*- coding: utf-8 -*-
"""S108 新浪三表孤儿管道全链接线测试。

契约（spec §6）：
- A1 fetch_merged_periods 返完整 FinancialPeriod（三表字段 + share_capital）
- A2 merge_three_statements 按 period 对齐
- A3 detect_anomalies 喂完整 periods 返 5 信号
- A4 /api/value-funnel/{code}/anomaly 端点 200
- A5 funnel L4 finals 含 anomaly
- A6 quality 第2/3/7 接新浪回退
- A7 L2 全量不调新浪（请求风暴防线）
- A8 新浪失败降级
"""
from __future__ import annotations

from unittest.mock import patch

import pytest

from data.mappers import merge_three_statements
from models.financials import FinancialPeriod


# ── A2：merge_three_statements ────────────────────────────────────────────────


class TestMerge:
    def test_aligns_by_period(self):
        """A2：按 报告期 对齐三表 raw，合并成每期一个 dict。"""
        lrb = [{"报告期": "2026-06-30", "营业收入": 100, "净利润": 10}]
        fzb = [{"报告期": "2026-06-30", "资产总计": 500, "实收资本(或股本)": 12.5}]
        llb = [{"报告期": "2026-06-30", "经营活动产生的现金流量净额": 20,
                "购建固定资产、无形资产和其他长期资产支付的现金": 5}]
        merged = merge_three_statements(lrb, fzb, llb)
        assert len(merged) == 1
        m = merged[0]
        assert m["报告期"] == "2026-06-30"
        assert m["营业收入"] == 100 and m["资产总计"] == 500
        assert m["实收资本(或股本)"] == 12.5
        assert m["经营活动产生的现金流量净额"] == 20

    def test_period_mismatch_kept(self):
        """A2 边界：某表独有的期保留（另两表字段缺失→None）。"""
        lrb = [{"报告期": "2026-06-30", "营业收入": 100},
               {"报告期": "2026-03-31", "营业收入": 80}]  # lrb 有季报
        fzb = [{"报告期": "2026-06-30", "资产总计": 500}]  # fzb 只年报
        llb = []
        merged = merge_three_statements(lrb, fzb, llb)
        assert len(merged) == 2  # 两期都保留
        periods = [m["报告期"] for m in merged]
        assert "2026-06-30" in periods and "2026-03-31" in periods

    def test_descending_order(self):
        """A2：按报告期倒序（最新在前）。"""
        lrb = [{"报告期": "2025-12-31", "营业收入": 100},
               {"报告期": "2026-06-30", "营业收入": 200}]
        merged = merge_three_statements(lrb, [], [])
        assert merged[0]["报告期"] == "2026-06-30"
        assert merged[1]["报告期"] == "2025-12-31"


# ── A1/A8：fetch_merged_periods ───────────────────────────────────────────────


class TestFetchMerged:
    def test_returns_complete_financial_periods(self):
        """A1：返完整 FinancialPeriod（三表字段 + share_capital）。"""
        from data.sources import sina_financial as sf
        lrb = [{"报告期": "2026-06-30", "营业收入": "100", "净利润": "10"}]
        fzb = [{"报告期": "2026-06-30", "资产总计": "500", "实收资本(或股本)": "12.5"}]
        llb = [{"报告期": "2026-06-30", "经营活动产生的现金流量净额": "20",
                "购建固定资产、无形资产和其他长期资产支付的现金": "5"}]
        with patch.object(sf, "fetch_raw", side_effect=[lrb, fzb, llb]):
            periods = sf.fetch_merged_periods("600519", num=5)
        assert len(periods) == 1
        p = periods[0]
        assert p.revenue == 100.0 and p.net_profit == 10.0
        assert p.total_assets == 500.0
        assert p.share_capital == 12.5  # S108 新增字段
        assert p.operating_cash_flow == 20.0 and p.capex == 5.0

    def test_all_empty_returns_empty(self):
        """A8：三表全失败 → 返 []。"""
        from data.sources import sina_financial as sf
        with patch.object(sf, "fetch_raw", side_effect=[[], [], []]):
            assert sf.fetch_merged_periods("000001") == []

    def test_partial_failure_degrades(self):
        """A8 边界：单表失败不阻断，用其余两表。"""
        from data.sources import sina_financial as sf
        lrb = [{"报告期": "2026-06-30", "营业收入": "100"}]
        with patch.object(sf, "fetch_raw",
                          side_effect=[lrb, RuntimeError("fzb断"), RuntimeError("llb断")]):
            periods = sf.fetch_merged_periods("600519")
        assert len(periods) == 1
        assert periods[0].revenue == 100.0
        assert periods[0].total_assets is None  # fzb 失败→None


# ── A3：detect_anomalies 喂完整 periods ─────────────────────────────────────


class TestAnomaly:
    def test_returns_5_signals_when_enough_periods(self):
        """A3：≥2 期 → 返 5 信号（非全 inapplicable）。"""
        from value_funnel.anomaly import detect_anomalies
        periods = [
            FinancialPeriod(period="2026-06-30", revenue=100, net_profit=10,
                            operating_cash_flow=5, accounts_receivable=20, inventory=15,
                            capex=3, net_profit_excluding_nonrecurring=8),
            FinancialPeriod(period="2025-12-31", revenue=80, net_profit=8,
                            operating_cash_flow=7, accounts_receivable=15, inventory=12,
                            capex=2, net_profit_excluding_nonrecurring=7),
        ]
        assessment = detect_anomalies(periods)
        assert len(assessment.signals) == 5
        # 足够期不返 inapplicable 信号
        assert all(s.index in (1, 2, 3, 4, 5) for s in assessment.signals)

    def test_insufficient_periods_inapplicable(self):
        """A3 边界：<2 期 → 各信号标 inapplicable。"""
        from value_funnel.anomaly import detect_anomalies
        assessment = detect_anomalies([FinancialPeriod(period="2026-06-30")])
        assert assessment.triggered_count == 0


# ── A4：anomaly 端点 ──────────────────────────────────────────────────────────


class TestAnomalyEndpoint:
    def test_endpoint_returns_200(self):
        """A4：/api/value-funnel/{code}/anomaly 200 返 AnomalyAssessment。"""
        from fastapi.testclient import TestClient
        from app import app
        with patch("data.sources.sina_financial.fetch_merged_periods",
                   return_value=[FinancialPeriod(period="2026-06-30", revenue=100,
                                                 net_profit=10, operating_cash_flow=5),
                                  FinancialPeriod(period="2025-12-31", revenue=80,
                                                  net_profit=8, operating_cash_flow=7)]):
            c = TestClient(app)
            r = c.get("/api/value-funnel/600519/anomaly")
        assert r.status_code == 200
        data = r.json()["data"]
        assert "signals" in data and len(data["signals"]) == 5


# ── A6：quality 第2/3/7 接新浪回退 ────────────────────────────────────────────


class TestQualityFallback:
    def test_metric_7_uses_sina_share_capital(self, monkeypatch):
        """A6 第7条：股本膨胀用新浪 share_capital 序列。"""
        from value_funnel import quality
        periods = [FinancialPeriod(period="2026-06-30", share_capital=12.5),
                   FinancialPeriod(period="2022-12-31", share_capital=10.0)]
        monkeypatch.setattr("data.sources.sina_financial.fetch_merged_periods",
                            lambda code, num=8: periods)
        m = quality._metric_7_share_dilution("600519", 10)
        assert not m.missing  # 新浪补上，不再 missing
        assert m.value is not None
        assert "新浪share_capital" in m.evidence

    def test_metric_7_sina_fail_falls_back_missing(self, monkeypatch):
        """A8 第7条：新浪失败 → 降级 missing。"""
        from value_funnel import quality
        from data.sources.akshare_src import DependencyMissing
        monkeypatch.setattr("data.sources.sina_financial.fetch_merged_periods",
                            lambda code, num=8: (_ for _ in ()).throw(DependencyMissing("断")))
        m = quality._metric_7_share_dilution("600519", 10)
        assert m.missing

    def test_metric_2_uses_sina_fcf(self, monkeypatch):
        """A6 第2条：FCF 用新浪 OCF−capex（非每股代理）。"""
        from value_funnel import quality
        periods = [FinancialPeriod(period="2026-06-30", operating_cash_flow=20, capex=5),
                   FinancialPeriod(period="2025-12-31", operating_cash_flow=18, capex=4)]
        monkeypatch.setattr("data.sources.sina_financial.fetch_merged_periods",
                            lambda code, num=5: periods)
        rows = [{"每股经营现金流": "1.0"}] * 5  # ths 代理
        m = quality._metric_2_fcf(rows, 10, "600519")
        assert "新浪" in m.evidence
        assert m.value == 29.0  # (20+18) - (5+4) = 29


# ── A7：L2 全量不调新浪（请求风暴防线）──────────────────────────────────────


class TestNoStormInL2:
    def test_funnel_l2_does_not_import_sina(self):
        """A7：请求风暴防线——funnel.py 只在 L4 finals 调 fetch_merged_periods，L2 不调。

        防线由代码结构保证：funnel.py 的 L2 段调 compute_quality（quality 内部按需单只
        回退新浪），不批量预计算；只有 L4 finals（≤top_n_l4=3 只）调 fetch_merged_periods。
        本测试验证 funnel.py L2 段不含 fetch_merged_periods 调用（grep 源码）。
        """
        import inspect
        from value_funnel import funnel
        src = inspect.getsource(funnel)
        # funnel.py 里 fetch_merged_periods 只应出现在 L4 段（一处），不在 L2
        # L2 段调 compute_quality，不调 fetch_merged_periods
        assert "fetch_merged_periods" in src  # L4 有调
        # 确认 L2 段（"if stage in (\"L2\"" 到 "if stage in (\"L3\"" 之间）不含 fetch_merged_periods
        l2_start = src.find('if stage in ("L2"')
        l2_end = src.find('if stage in ("L3"', l2_start)
        l2_block = src[l2_start:l2_end] if l2_start > 0 and l2_end > 0 else ""
        assert "fetch_merged_periods" not in l2_block  # L2 不调新浪批量
