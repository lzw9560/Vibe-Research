# -*- coding: utf-8 -*-
"""S084 选股池战法解耦单测：DiagnosisCard 3 子对象 + 10 扩展字段 + 新 source 契约。

覆盖 AC1-AC5（AC5a-d 移 backlog 不在范围）：
- AC1：DiagnosisCard 含 gene_score/pool_item/derived（默认 None 不破坏序列化）
- AC2：gene.py 扩展存完整 GeneScore 对象（gene_obj 键）
- AC3：zt_pool_source 从 first_board_filter.fetch_zt_pool 取（走 em_get 限流）
- AC4：derived_source 取 T-1 昨日 snapshots，盘前未采集 None 降级
- AC5：IndicatorSet 10 扩展字段（tencent_quote 6 + 板块资金 3 + 前日成交额 1）按历史日路径分字段
"""

from __future__ import annotations

import os
import sys
import unittest
from datetime import datetime
from types import SimpleNamespace
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from candidate_funnel import funnel
from candidate_funnel.diagnosis import build_diagnosis_card, build_indicator_set
from candidate_funnel.models import (
    ActivityAssessment,
    ActivityTier,
    BaseThreshold,
    DiagnosisCard,
    IndicatorSet,
    StabilizationSignals,
    ThresholdConfig,
)
from candidate_funnel.sources import activity, derived_source, fund_flow, gene, zt_pool_source
from limitup_screener.models import GeneScore


# 与 astock._parse_gtimg 实际输出同形（含 S084 新字段 raw key）
_GTIMG_SHAPE = {
    "600519": {
        "name": "贵州茅台", "price": 1800.0, "last_close": 1714.28, "open": 1720.0,
        "change_amt": 85.72, "change_pct": 5.0, "high": 1820.0, "low": 1710.0,
        "amount_wan": 500000.0, "turnover_pct": 25.0, "pe_ttm": 30.0,
        "amplitude_pct": 6.4, "mcap_yi": 22600.0, "float_mcap_yi": 22600.0,
        "pb": 10.0, "limit_up": 1885.71, "limit_down": 1542.85,
        "vol_ratio": 3.0, "pe_static": 30.0,
    },
}


class TestModelsS084(unittest.TestCase):
    """AC1/AC5：DiagnosisCard 3 子对象 + IndicatorSet 10 字段默认 None 不破坏序列化。"""

    def _card(self) -> DiagnosisCard:
        ind = IndicatorSet(code="600519", name="贵州茅台")
        return DiagnosisCard(
            code="600519", name="贵州茅台", indicators=ind,
            activity=ActivityAssessment(tier=ActivityTier.COLD, rules_applied=[]),
            stabilization=StabilizationSignals(), as_of=datetime.now(),
        )

    def test_diagnosis_card_3_subobjects_default_none(self):
        card = self._card()
        self.assertIsNone(card.gene_score)
        self.assertIsNone(card.pool_item)
        self.assertIsNone(card.derived)

    def test_diagnosis_card_model_dump_contains_3_subobject_keys(self):
        d = self._card().model_dump(mode="json")
        for k in ("gene_score", "pool_item", "derived"):
            self.assertIn(k, d)

    def test_indicatorset_10_new_fields_default_none(self):
        ind = IndicatorSet(code="X", name="X")
        for f in ("last_close", "open", "change_amt", "pe_ttm", "mcap_yi", "pb",
                  "sector_net_inflow", "sector_inflow", "sector_outflow", "prev_amount_yi"):
            self.assertIsNone(getattr(ind, f), f"{f} 应默认 None")


class TestGeneObj(unittest.TestCase):
    """AC2：fetch_genes 扩展存完整 GeneScore 对象（gene_obj 键，不删数字键）。"""

    def _gene(self) -> GeneScore:
        return GeneScore(
            code="600519", name="贵州茅台", total_score=80.0,
            factors={"封板率": 70}, wilson_adjusted=78.0, qualify=True,
            high_gene=True, last_zt_dates=[], zt_count_250d=3,
        )

    def test_fetch_genes_stores_gene_obj(self):
        import limitup_screener as ls
        result = SimpleNamespace(gene_scores=[self._gene()])

        async def fake(date=None):
            return result

        with mock.patch.object(ls, "get_screener_result", fake):
            out = gene.fetch_genes("2026-08-10")
        self.assertIn("600519", out)
        # gene_obj 存原始 GeneScore 对象
        self.assertIsInstance(out["600519"]["gene_obj"], GeneScore)
        # 数字键不删（向后兼容）
        self.assertEqual(out["600519"]["gene_score"], 80.0)
        self.assertTrue(out["600519"]["high_gene"])

    def test_fetch_genes_empty_no_gene_obj_key(self):
        import limitup_screener as ls
        result = SimpleNamespace(gene_scores=[])

        async def fake(date=None):
            return result

        with mock.patch.object(ls, "get_screener_result", fake):
            out = gene.fetch_genes("2026-08-10")
        self.assertEqual(out, {})


class TestZtPoolSource(unittest.TestCase):
    """AC3：zt_pool_source 复用 first_board_filter.fetch_zt_pool（走 em_get 限流）。"""

    def test_fetch_zt_pool_map_builds_code_mapping(self):
        pool = [
            {"c": "600519", "n": "茅台", "lbc": 2, "zbc": 0, "fbt": "0930",
             "zdp": 10.0, "zje": 1850.0, "hybk": "白酒"},
            {"c": "000001", "n": "平安", "lbc": 1, "zbc": 1, "fbt": "1005",
             "zdp": 9.9, "zje": 12.0, "hybk": "银行"},
        ]
        with mock.patch("strategies.first_board_filter.fetch_zt_pool", return_value=pool):
            m = zt_pool_source.fetch_zt_pool_map("2026-08-10")
        self.assertEqual(set(m.keys()), {"600519", "000001"})
        self.assertEqual(m["600519"]["lbc"], 2)
        self.assertEqual(m["000001"]["hybk"], "银行")

    def test_fetch_zt_pool_map_empty_on_failure(self):
        with mock.patch("strategies.first_board_filter.fetch_zt_pool", side_effect=RuntimeError):
            self.assertEqual(zt_pool_source.fetch_zt_pool_map("2026-08-10"), {})


class TestDerivedSource(unittest.TestCase):
    """AC4：derived_source 取 T-1 昨日 snapshots；未采集→None 降级不臆造。"""

    _OK = {"last_lock_time": "2026-08-09T14:00:00", "broken_duration_min": 0.0,
           "max_drop_pct": 1.5, "limit_price": 11.0,
           "granularity_note": "60s粒度近似", "data_status": "ok"}

    def test_returns_dict_when_snapshots_exist(self):
        snaps = [{"ts": "x", "open_count": 0, "limit_pct": 10.0, "price": 11.0, "low_price": 10.8}]
        with mock.patch("risk.seal_intraday_collector.get_snapshots_by_code", return_value=snaps), \
             mock.patch("strategies.intraday_features.compute_derived_features", return_value=self._OK):
            d = derived_source.fetch_derived("600519", "2026-08-09")
        self.assertEqual(d["broken_duration_min"], 0.0)
        self.assertEqual(d["data_status"], "ok")

    def test_none_when_no_snapshots(self):
        with mock.patch("risk.seal_intraday_collector.get_snapshots_by_code", return_value=[]):
            self.assertIsNone(derived_source.fetch_derived("600519", "2026-08-09"))

    def test_none_when_data_status_missing(self):
        snaps = [{"ts": "x", "open_count": 0, "limit_pct": 1, "price": 1, "low_price": 1}]
        with mock.patch("risk.seal_intraday_collector.get_snapshots_by_code", return_value=snaps), \
             mock.patch("strategies.intraday_features.compute_derived_features",
                        return_value={"data_status": "missing", "broken_duration_min": None}):
            self.assertIsNone(derived_source.fetch_derived("600519", "2026-08-09"))

    def test_reads_precomputed_from_table(self):
        """S084 C3：命中 seal_derived_features 预采集 → 直接返，不实时算 snapshots。"""
        cached = {"last_lock_time": "2026-08-09T14:00:00", "broken_duration_min": 5.0,
                  "max_drop_pct": 2.0, "limit_price": None,
                  "granularity_note": "60s粒度近似", "data_status": "ok"}
        with mock.patch("risk.seal_intraday_collector.get_derived_result",
                        return_value=cached) as m, \
             mock.patch("risk.seal_intraday_collector.get_snapshots_by_code") as snap:
            d = derived_source.fetch_derived("600519", "2026-08-09")
        m.assert_called_once_with("600519", "2026-08-09")
        snap.assert_not_called()  # 命中预采集表，不 per-code 实时算
        self.assertEqual(d["broken_duration_min"], 5.0)
        self.assertEqual(d["data_status"], "ok")

    def test_precomputed_missing_status_returns_none(self):
        """预采集表 data_status='missing' → None（不透传空派生，与 S070 范式一致）。"""
        cached = {"broken_duration_min": None, "data_status": "missing"}
        with mock.patch("risk.seal_intraday_collector.get_derived_result",
                        return_value=cached), \
             mock.patch("risk.seal_intraday_collector.get_snapshots_by_code") as snap:
            self.assertIsNone(derived_source.fetch_derived("600519", "2026-08-09"))
        snap.assert_not_called()  # missing 也不走 fallback（表已明确 missing）


class TestActivityNewFields(unittest.TestCase):
    """AC5：activity 两路径新字段（batch 当日 tencent_quote + kline 历史日复算）。"""

    def test_batch_path_reads_tencent_quote_extended_fields(self):
        with mock.patch.object(activity.astock, "tencent_quote", return_value=_GTIMG_SHAPE):
            out = activity.fetch_activity(["600519"], "2099-07-28")  # 未来日→batch 路径
        e = out["600519"]
        self.assertAlmostEqual(e["last_close"], 1714.28)
        self.assertAlmostEqual(e["open"], 1720.0)
        self.assertAlmostEqual(e["change_amt"], 85.72)  # Quote.change_amount → entry change_amt
        self.assertAlmostEqual(e["pe_ttm"], 30.0)
        self.assertAlmostEqual(e["mcap_yi"], 22600.0)
        self.assertAlmostEqual(e["pb"], 10.0)
        self.assertIsNone(e["prev_amount_yi"])  # 当日路径无前日 K线
        self.assertIn("prev_amount_yi", e.get("missing", {}))

    def test_kline_path_recomputes_fields_and_marks_valuation_missing(self):
        bars = [
            {"datetime": "2026-08-09", "open": 10.0, "high": 11.0, "low": 9.5,
             "close": 10.5, "vol": 1000, "amount": 1e8},
            {"datetime": "2026-08-10", "open": 10.5, "high": 11.5, "low": 10.5,
             "close": 11.0, "vol": 2000, "amount": 2e8},
        ]
        shape = {"600519": dict(_GTIMG_SHAPE["600519"])}  # 当日 quote 仅供 name/float_market_cap
        with mock.patch.object(activity.astock, "tencent_quote", return_value=shape), \
             mock.patch.object(activity.astock, "kline", return_value=bars):
            out = activity._fetch_activity_from_kline(["600519"], "2026-08-10")
        e = out["600519"]
        self.assertEqual(e["last_close"], 10.5)   # prev bar close = T-1 昨收
        self.assertEqual(e["open"], 10.5)         # target bar open
        self.assertEqual(e["change_amt"], 0.5)    # 11.0 - 10.5
        self.assertEqual(e["prev_amount_yi"], 1.0)  # 1e8/1e8
        # pe_ttm/mcap_yi/pb 历史日无源 → None + missing（不臆造）
        self.assertIsNone(e["pe_ttm"])
        self.assertIsNone(e["mcap_yi"])
        self.assertIsNone(e["pb"])
        self.assertIn("当前估值非T-1", e["missing"]["pe_ttm"])


class TestFundFlowSectors(unittest.TestCase):
    """AC5：fund_flow sectors 行业匹配（市场级板块资金）。"""

    def _patches(self):
        return (mock.patch.object(fund_flow.astock, "stock_fund_flow_120d", return_value=[]) ,
                mock.patch.object(fund_flow.astock, "dragon_tiger_board", return_value={}))

    def test_sectors_matched_by_industry(self):
        sectors = [{"name": "白酒", "net": 5000.0, "inflow": 8000.0, "outflow": 3000.0, "firms": 10}]
        # 行业从 zt pool hybk 提取（em_get-backed），非 raw akshare individual_info
        with mock.patch.object(fund_flow.astock, "stock_fund_flow_120d", return_value=[]), \
             mock.patch.object(fund_flow.astock, "dragon_tiger_board", return_value={}):
            out = fund_flow.fetch_fund_flow(["600519"], "2026-08-10", sectors=sectors,
                                            industry_map={"600519": "白酒"})
        e = out["600519"]
        self.assertEqual(e["sector_net_inflow"], 5000.0)
        self.assertEqual(e["sector_inflow"], 8000.0)
        self.assertEqual(e["sector_outflow"], 3000.0)

    def test_sectors_no_match_marks_missing(self):
        sectors = [{"name": "银行", "net": 1000.0, "inflow": 2000.0, "outflow": 1000.0, "firms": 5}]
        with mock.patch.object(fund_flow.astock, "stock_fund_flow_120d", return_value=[]), \
             mock.patch.object(fund_flow.astock, "dragon_tiger_board", return_value={}):
            out = fund_flow.fetch_fund_flow(["600519"], "2026-08-10", sectors=sectors,
                                            industry_map={"600519": "白酒"})
        e = out["600519"]
        self.assertIsNone(e["sector_net_inflow"])
        self.assertIn("sector_net_inflow", e["missing"])

    def test_sectors_none_marks_missing(self):
        with mock.patch.object(fund_flow.astock, "stock_fund_flow_120d", return_value=[]), \
             mock.patch.object(fund_flow.astock, "dragon_tiger_board", return_value={}):
            out = fund_flow.fetch_fund_flow(["600519"], "2026-08-10")  # sectors=None
        e = out["600519"]
        self.assertIsNone(e["sector_net_inflow"])
        self.assertIn("板块资金未采集", e["missing"].get("sector_net_inflow", ""))


class TestBuildDiagnosisCardSubobjects(unittest.TestCase):
    """AC1：build_diagnosis_card 塞 3 子对象 + 缺失降级。"""

    def _ind(self) -> IndicatorSet:
        return IndicatorSet(code="600519", name="贵州茅台", turnover_pct=25.0)

    def test_3_subobjects_populated(self):
        g = GeneScore(code="600519", name="贵州茅台", total_score=80.0,
                      factors={"封板率": 70}, wilson_adjusted=78.0, qualify=True,
                      high_gene=True, last_zt_dates=[], zt_count_250d=3)
        pool = {"lbc": 2, "zdp": 10.0, "fbt": "0930", "zbc": 0, "zje": 1850.0, "hybk": "白酒"}
        derived = {"broken_duration_min": 0.0, "max_drop_pct": 1.5,
                   "last_lock_time": "14:00", "data_status": "ok"}
        card = build_diagnosis_card("600519", "贵州茅台", self._ind(), BaseThreshold(),
                                    as_of=datetime.now(), gene_obj=g, pool_item=pool, derived=derived)
        self.assertIsNotNone(card.gene_score)
        self.assertEqual(card.gene_score["total_score"], 80.0)  # model_dump dict
        self.assertIn("factors", card.gene_score)
        self.assertEqual(card.pool_item, pool)
        self.assertEqual(card.derived, derived)

    def test_3_subobjects_none_when_not_passed(self):
        card = build_diagnosis_card("600519", "贵州茅台", self._ind(), BaseThreshold(),
                                    as_of=datetime.now())
        self.assertIsNone(card.gene_score)
        self.assertIsNone(card.pool_item)
        self.assertIsNone(card.derived)

    def test_gene_obj_non_pydantic_defensive_skip(self):
        """非 pydantic 对象（如 mock）无 model_dump → gene_score=None 不崩（hasattr 防御）。"""
        class FakeGene:
            pass
        card = build_diagnosis_card("600519", "贵州茅台", self._ind(), BaseThreshold(),
                                    as_of=datetime.now(), gene_obj=FakeGene())
        self.assertIsNone(card.gene_score)


class TestBuildIndicatorSetRelay(unittest.TestCase):
    """AC5：build_indicator_set 透传 10 新字段。"""

    def test_relay_new_fields_from_activity_and_fund(self):
        activity_d = {"600519": {"last_close": 1700.0, "open": 1710.0, "change_amt": 10.0,
                                "pe_ttm": 30.0, "mcap_yi": 22000.0, "pb": 10.0, "prev_amount_yi": 5.0}}
        fund_d = {"600519": {"sector_net_inflow": 5000.0, "sector_inflow": 8000.0,
                            "sector_outflow": 3000.0}}
        ind = build_indicator_set("600519", "贵州茅台", {}, activity_d, fund_d, {}, {}, {})
        self.assertEqual(ind.last_close, 1700.0)
        self.assertEqual(ind.open, 1710.0)
        self.assertEqual(ind.change_amt, 10.0)
        self.assertEqual(ind.pe_ttm, 30.0)
        self.assertEqual(ind.mcap_yi, 22000.0)
        self.assertEqual(ind.pb, 10.0)
        self.assertEqual(ind.prev_amount_yi, 5.0)
        self.assertEqual(ind.sector_net_inflow, 5000.0)
        self.assertEqual(ind.sector_inflow, 8000.0)
        self.assertEqual(ind.sector_outflow, 3000.0)


class TestFunnelEndToEndSubobjects(unittest.TestCase):
    """AC1 端到端：funnel.final_candidates 的 DiagnosisCard 含 3 子对象。"""

    def test_final_candidates_contain_3_subobjects(self):
        funnel.clear_funnel_cache()
        g = GeneScore(code="000001", name="X", total_score=80.0, factors={"涨停频次": 25},
                      wilson_adjusted=78.0, qualify=True, high_gene=False,
                      last_zt_dates=[], zt_count_250d=1)
        with mock.patch.object(gene, "fetch_genes", return_value={
                "000001": {"name": "X", "gene_score": 80.0, "high_gene": False,
                           "qualify": True, "gene_obj": g}}), \
             mock.patch.object(funnel.sources.board_ladder, "fetch_board_ladder", return_value={}), \
             mock.patch.object(activity, "fetch_activity", return_value={
                "000001": {"name": "X", "turnover_pct": 15.0, "vol_ratio": 1.8,
                           "amount_yi": 12.0, "amplitude_pct": 5.0}}), \
             mock.patch.object(fund_flow, "fetch_fund_flow", return_value={
                "000001": {"main_net_inflow": 5000.0, "main_net_5d": 20000.0, "northbound": 800.0}}), \
             mock.patch.object(funnel.sources.auction, "fetch_auction", return_value={
                "000001": {"auction_open_pct": 2.0}}), \
             mock.patch.object(funnel.sources.catalyst, "fetch_catalyst", return_value={
                "000001": {"announcements": [{"title": "回购", "date": "2026-08-10"}],
                           "concepts": [], "sector_flow": None}}), \
             mock.patch.object(funnel.sources.watchlist_in, "get_watchlist_codes", return_value=[]), \
             mock.patch.object(funnel, "_fetch_sentiment_phase", lambda date, ctx=None: None), \
             mock.patch.object(zt_pool_source, "fetch_zt_pool_map", return_value={
                "000001": {"lbc": 1, "zdp": 10.0, "fbt": "0930", "zbc": 0, "zje": 12.0, "hybk": "X"}}), \
             mock.patch.object(derived_source, "fetch_derived", return_value={
                "broken_duration_min": 0.0, "data_status": "ok"}), \
             mock.patch("market.get_overview", return_value={"sectors": []}):
            result = funnel.run_funnel("pre_market", "2026-08-10", ThresholdConfig())
        try:
            self.assertTrue(result.final_candidates, "final_candidates 不应为空")
            card = result.final_candidates[0]
            self.assertIsNotNone(card.gene_score)
            self.assertEqual(card.gene_score["total_score"], 80.0)
            self.assertIsNotNone(card.pool_item)
            self.assertEqual(card.pool_item["lbc"], 1)
            self.assertIsNotNone(card.derived)
            self.assertEqual(card.derived["broken_duration_min"], 0.0)
        finally:
            funnel.clear_funnel_cache()


if __name__ == "__main__":
    unittest.main()
