# -*- coding: utf-8 -*-
"""sources 联网冒烟测试（S002 B1-B7，@pytest.mark.live）。

仅 -m live 时运行，验证各 source 适配器对真实 astock/limitup_screener/market/auction_screener
的字段映射。默认 -m "not live" 跳过。断言结构而非具体数值（联网结果随行情变）。
"""

from __future__ import annotations

import os
import sys
import unittest
from datetime import date

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from candidate_funnel import sources

_TODAY = date.today().isoformat()
_CODE = "600519"  # 贵州茅台（流动性稳定，便于联网复核）


@pytest.mark.live
class TestSourcesLive(unittest.TestCase):
    def test_gene_fetch_structure(self):
        out = sources.gene.fetch_genes(_TODAY)
        self.assertIsInstance(out, dict)
        for c, v in out.items():
            self.assertIn("name", v)
            self.assertIn("gene_score", v)

    def test_board_ladder_structure(self):
        out = sources.board_ladder.fetch_board_ladder(_TODAY)
        self.assertIn("seal_rate", out)
        self.assertIn("bomb_rate", out)
        self.assertIn("advance_rate", out)
        self.assertIn("lianban_stocks", out)

    def test_activity_structure(self):
        out = sources.activity.fetch_activity([_CODE], _TODAY)
        self.assertIn(_CODE, out)
        v = out[_CODE]
        self.assertTrue("turnover_pct" in v or "missing" in v)

    def test_fund_flow_structure(self):
        out = sources.fund_flow.fetch_fund_flow([_CODE], _TODAY)
        self.assertIn(_CODE, out)
        v = out[_CODE]
        self.assertIn("main_net_inflow", v)
        self.assertIn("missing", v)

    def test_auction_structure(self):
        out = sources.auction.fetch_auction(_TODAY)
        self.assertIsInstance(out, dict)

    def test_catalyst_structure(self):
        out = sources.catalyst.fetch_catalyst([_CODE], _TODAY)
        self.assertIn(_CODE, out)
        v = out[_CODE]
        self.assertIn("announcements", v)
        self.assertIn("concepts", v)

    def test_watchlist_returns_list(self):
        out = sources.watchlist_in.get_watchlist_codes()
        self.assertIsInstance(out, list)
