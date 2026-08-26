# -*- coding: utf-8 -*-
"""S097 first_plate match() 返 StrategyMatchResult 契约测试（拆 C1/C2 + 三态 + fired）。

验证 S097 R3/R4：first_plate 从"全有或全无 list[ConditionMatch]"改为返
StrategyMatchResult（C1 基因合格 + C2 涨停频次，全量条件三态 hit/miss + fired 全条件命中）。
"""
from __future__ import annotations

import os
import sys
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from strategies.strategy_base import StrategyContext, StrategyMatchResult  # noqa: E402
from strategies.impl.gene_based import FirstPlateStrategy  # noqa: E402


def _make_gene(total_score=70, freq=30) -> mock.MagicMock:
    gene = mock.MagicMock()
    gene.total_score = total_score
    gene.factors = {"涨停频次": freq, "封板率": 80}
    gene.zt_count_250d = 5
    gene.code = "003032"
    return gene


def _ctx(gene) -> StrategyContext:
    return StrategyContext(
        code=gene.code, gene=gene, pool_item=None,
        indicators=None, derived=None, weather_state=None,
    )


class TestFirstPlateMatchS097(unittest.TestCase):
    """first_plate 拆 C1/C2 + 三态 + fired 全条件命中。"""

    def test_both_hit_fired(self):
        gene = _make_gene(total_score=70, freq=30)
        r = FirstPlateStrategy().match(_ctx(gene))
        self.assertIsInstance(r, StrategyMatchResult)
        self.assertTrue(r.fired)
        self.assertEqual(r.hit_count, 2)
        self.assertEqual(len(r.conditions), 2)
        self.assertEqual(r.conditions[0].condition_id, "first_plate.c1")
        self.assertEqual(r.conditions[0].state, "hit")
        self.assertEqual(r.conditions[1].state, "hit")
        self.assertEqual(r.fire_rule, "全条件命中")
        self.assertTrue(r.data_ok)

    def test_c1_miss_c2_hit_not_fired(self):
        gene = _make_gene(total_score=50, freq=30)  # C1 基因<60 miss
        r = FirstPlateStrategy().match(_ctx(gene))
        self.assertFalse(r.fired)
        self.assertEqual(r.hit_count, 1)
        self.assertEqual(r.conditions[0].state, "miss")
        self.assertEqual(r.conditions[1].state, "hit")

    def test_c1_hit_c2_miss_not_fired(self):
        gene = _make_gene(total_score=70, freq=10)  # C2 频次<=20 miss
        r = FirstPlateStrategy().match(_ctx(gene))
        self.assertFalse(r.fired)
        self.assertEqual(r.hit_count, 1)
        self.assertEqual(r.conditions[0].state, "hit")
        self.assertEqual(r.conditions[1].state, "miss")


if __name__ == "__main__":
    unittest.main()
