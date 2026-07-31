# -*- coding: utf-8 -*-
"""漏斗引擎测试（S002 B9/B10，TDD RED）。

mock 各 source，端到端跑 R1→R2→R3 + 自选并行 + 空层。
"""

from __future__ import annotations

import os
import sys
import unittest
from datetime import datetime
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from candidate_funnel import funnel as funnel_mod
from candidate_funnel.funnel import run_funnel
from candidate_funnel.models import ThresholdConfig


# ---- 合成 source 数据 ----
_GENES = {
    "600519": {"name": "贵州茅台", "gene_score": 80.0, "high_gene": True, "qualify": True},
    "000001": {"name": "平安银行", "gene_score": 65.0, "high_gene": False, "qualify": True},
    "603555": {"name": "ST贵人", "gene_score": 70.0, "high_gene": False, "qualify": True},  # 应被 ST 过滤
}
_BOARD_LADDER = {"seal_rate": 0.6, "bomb_rate": 0.2, "advance_rate": 0.3, "lianban_stocks": []}
_ACTIVITY = {
    # 600519 活跃；000001 冷股应被 R2 过滤
    "600519": {"name": "贵州茅台", "price": 1800.0, "change_pct": 5.0, "turnover_pct": 25.0,
               "vol_ratio": 3.0, "amount_yi": 50.0, "amplitude_pct": 6.0,
               "limit_up": 1890.0, "limit_down": 1710.0},
    "000001": {"name": "平安银行", "price": 12.0, "change_pct": 0.5, "turnover_pct": 3.0,
               "vol_ratio": 0.8, "amount_yi": 5.0, "amplitude_pct": 2.0,
               "limit_up": 13.2, "limit_down": 10.8},
}
_FUND_FLOW = {
    "600519": {"main_net_inflow": 50000.0, "main_net_5d": 200000.0,
               "dragon_tiger_inst_net": 30000.0, "northbound": 8000.0},
    "000001": {"main_net_inflow": -5000.0, "main_net_5d": -20000.0,
               "dragon_tiger_inst_net": None, "northbound": None},
}
_AUCTION = {"600519": {"name": "贵州茅台", "auction_open_pct": 0.04}}
_CATALYST = {
    "600519": {"announcements": [{"title": "预增", "date": "2026-07-28", "type": "业绩"}],
               "concepts": ["白酒"], "sector_flow": 2.0},
}
_WATCHLIST = ["002594"]


class TestRunFunnelEndToEnd(unittest.TestCase):
    """B9: R1→R2→R3 + 自选并行，每层输出为下轮输入。"""

    def _patch_sources(self):
        return (
            mock.patch.object(funnel_mod.sources.gene, "fetch_genes", return_value=_GENES),
            mock.patch.object(funnel_mod.sources.board_ladder, "fetch_board_ladder", return_value=_BOARD_LADDER),
            mock.patch.object(funnel_mod.sources.activity, "fetch_activity", return_value=_ACTIVITY),
            mock.patch.object(funnel_mod.sources.fund_flow, "fetch_fund_flow", return_value=_FUND_FLOW),
            mock.patch.object(funnel_mod.sources.auction, "fetch_auction", return_value=_AUCTION),
            mock.patch.object(funnel_mod.sources.catalyst, "fetch_catalyst", return_value=_CATALYST),
            mock.patch.object(funnel_mod.sources.watchlist_in, "get_watchlist_codes", return_value=_WATCHLIST),
            mock.patch.object(funnel_mod, "_fetch_sentiment_phase", return_value="晴天"),
        )

    def test_full_funnel_produces_layers_and_candidates(self):
        patches = self._patch_sources()
        for p in patches:
            p.start()
            self.addCleanup(p.stop)
        cfg = ThresholdConfig(mode="manual")
        result = run_funnel(stage="all", date="2026-07-28", cfg=cfg)
        layer_ids = [l.layer_id for l in result.layers]
        self.assertIn("R1", layer_ids)
        self.assertIn("R2", layer_ids)
        self.assertIn("R3", layer_ids)
        r1 = next(l for l in result.layers if l.layer_id == "R1")
        self.assertNotIn("603555", r1.output_codes)
        self.assertEqual(r1.input_count, 3)
        self.assertEqual(r1.output_count, 2)
        r2 = next(l for l in result.layers if l.layer_id == "R2")
        self.assertNotIn("000001", r2.output_codes)
        self.assertIn("600519", r2.output_codes)
        final_codes = [c.code for c in result.final_candidates]
        self.assertIn("600519", final_codes)
        self.assertEqual(result.sentiment_phase, "晴天")

    def test_each_layer_output_feeds_next_input(self):
        patches = self._patch_sources()
        for p in patches:
            p.start()
            self.addCleanup(p.stop)
        cfg = ThresholdConfig(mode="manual")
        result = run_funnel(stage="all", date="2026-07-28", cfg=cfg)
        r1, r2, r3 = (next(l for l in result.layers if l.layer_id == x) for x in ("R1", "R2", "R3"))
        self.assertTrue(set(r2.output_codes) <= set(r1.output_codes))
        self.assertTrue(set(r3.output_codes) <= set(r2.output_codes))

    def test_watchlist_parallel_channel_merged(self):
        patches = self._patch_sources()
        for p in patches:
            p.start()
            self.addCleanup(p.stop)
        cfg = ThresholdConfig(mode="manual")
        result = run_funnel(stage="all", date="2026-07-28", cfg=cfg)
        self.assertIn("SELF", [l.layer_id for l in result.layers])


class TestRunFunnelEmptyLayer(unittest.TestCase):
    """B9/AC9: 任一层空 → 下游无输入并提示，不报错。"""

    def test_r1_empty_propagates_no_crash(self):
        with mock.patch.object(funnel_mod.sources.gene, "fetch_genes", return_value={}), \
             mock.patch.object(funnel_mod.sources.board_ladder, "fetch_board_ladder", return_value=_BOARD_LADDER), \
             mock.patch.object(funnel_mod.sources.activity, "fetch_activity", return_value={}), \
             mock.patch.object(funnel_mod.sources.fund_flow, "fetch_fund_flow", return_value={}), \
             mock.patch.object(funnel_mod.sources.auction, "fetch_auction", return_value={}), \
             mock.patch.object(funnel_mod.sources.catalyst, "fetch_catalyst", return_value={}), \
             mock.patch.object(funnel_mod.sources.watchlist_in, "get_watchlist_codes", return_value=[]), \
             mock.patch.object(funnel_mod, "_fetch_sentiment_phase", return_value=None):
            cfg = ThresholdConfig(mode="manual")
            result = run_funnel(stage="all", date="2026-07-28", cfg=cfg)
            r1 = next(l for l in result.layers if l.layer_id == "R1")
            self.assertEqual(r1.output_count, 0)
            self.assertEqual(result.final_candidates, [])
            # 不抛异常即通过


if __name__ == "__main__":
    unittest.main()
