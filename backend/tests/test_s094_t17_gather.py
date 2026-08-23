# -*- coding: utf-8 -*-
"""S094 T17：gather_non_limitup_candidates 采集测试。

gather 抽自 routers/strategy.py 端点（R26），供 workflow._collect 产 market_scan_scored
（briefing 双 pipeline 分区透传，R28）。验证无热门板块场景的早返 + shape。
完整路径（top + cache + score）依赖 baostock_kline_cache 全 A 扩容（T21-run），
逻辑同端点（S3 已覆盖）+ T21-run 后 live 验。
"""
from __future__ import annotations

import os
import sys
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


class TestGatherNonLimitupCandidates(unittest.TestCase):
    """T17/R26：gather_non_limitup_candidates 采集早返 + shape。"""

    def test_empty_when_no_top_sectors(self):
        """sector_rotation 无涨停板块（strength_rank 空）→ 返空 dict。"""
        from strategies.market_scan import gather_non_limitup_candidates
        with mock.patch("strategies.sector_cycle.sector_rotation",
                        return_value={"strength_rank": []}):
            result = gather_non_limitup_candidates("2026-08-13")
        self.assertEqual(result, {
            "candidates": [], "count": 0, "sectors_scanned": 0, "candidates_input": 0,
        })

    def test_empty_when_top_has_no_zt_count(self):
        """strength_rank 有板块但 zt_count_today=0 → top 过滤后空 → 返空 dict。"""
        from strategies.market_scan import gather_non_limitup_candidates
        with mock.patch("strategies.sector_cycle.sector_rotation",
                        return_value={"strength_rank": [{"industry": "电子", "zt_count_today": 0}]}):
            result = gather_non_limitup_candidates("2026-08-13")
        self.assertEqual(result["candidates"], [])
        self.assertEqual(result["count"], 0)
        self.assertEqual(result["sectors_scanned"], 0)

    def test_returns_shape_keys(self):
        """返 dict 含 candidates/count/sectors_scanned/candidates_input 4 键（端点同 shape）。"""
        from strategies.market_scan import gather_non_limitup_candidates
        with mock.patch("strategies.sector_cycle.sector_rotation",
                        return_value={"strength_rank": []}):
            result = gather_non_limitup_candidates("2026-08-13")
        self.assertEqual(set(result.keys()),
                         {"candidates", "count", "sectors_scanned", "candidates_input"})


if __name__ == "__main__":
    unittest.main()
