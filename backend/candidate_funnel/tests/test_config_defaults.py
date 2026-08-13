# -*- coding: utf-8 -*-
"""AssistantDefaultConfig 候选池默认字段测试（S002 A10，TDD RED）。"""

from __future__ import annotations

import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from config import AssistantDefaultConfig


class TestCandidateFunnelDefaults(unittest.TestCase):
    def test_mode_default_suggest(self):
        cfg = AssistantDefaultConfig()
        self.assertEqual(cfg.CANDIDATE_FUNNEL_MODE, "suggest")

    def test_base_thresholds_match_spec(self):
        cfg = AssistantDefaultConfig()
        b = cfg.CANDIDATE_FUNNEL_BASE
        self.assertEqual(b["turnover_cold"], 8.0)
        self.assertEqual(b["turnover_hot"], 20.0)
        self.assertEqual(b["vol_ratio_active"], 2.0)
        self.assertEqual(b["amount_yi_min"], 10.0)
        self.assertEqual(b["amplitude_high"], 8.0)

    def test_sources_all_on_by_default(self):
        cfg = AssistantDefaultConfig()
        srcs = cfg.CANDIDATE_FUNNEL_SOURCES
        for k in ("gene", "board_ladder", "activity", "fund_flow",
                  "auction", "catalyst", "watchlist_in"):
            self.assertTrue(srcs.get(k), f"{k} 应默认开启")

    def test_cache_ttl(self):
        cfg = AssistantDefaultConfig()
        # S004 R5：TTL 默认 3600s（盘后预计算长 TTL，收盘数据已定无 stale 风险）
        self.assertEqual(cfg.CANDIDATE_FUNNEL_CACHE_TTL, 3600)

    def test_max_r2(self):
        cfg = AssistantDefaultConfig()
        self.assertEqual(cfg.CANDIDATE_FUNNEL_MAX_R2, 80)


if __name__ == "__main__":
    unittest.main()
