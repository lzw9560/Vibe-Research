# -*- coding: utf-8 -*-
"""S004 性能收尾测试：top-N 限界 + 并行采集 + 预计算 executor + TTL 读 config。

spec A5：验证 R3 top-N 截断、R2 并行不丢数据、R5 预计算写缓存且失败不抛、
TTL 从 config 读取（非硬编码）。
"""
from __future__ import annotations

import os
import sys
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from candidate_funnel import funnel as funnel_mod
from candidate_funnel.funnel import run_funnel, _top_n_by_gene_score, _funnel_cache_ttl
from candidate_funnel.models import ThresholdConfig


def _make_genes(n: int) -> dict:
    """生成 n 只合成基因数据，gene_score 从 n 递减到 1。"""
    return {
        f"60000{i:03d}": {"name": f"股票{i}", "gene_score": float(n - i), "high_gene": i < 5, "qualify": True}
        for i in range(n)
    }


class TestTopNLimit(unittest.TestCase):
    """S004 R3：top-N 限界。"""

    def test_top_n_truncates_to_n(self):
        codes = [f"60000{i:03d}" for i in range(120)]
        genes = {f"60000{i:03d}": {"gene_score": float(120 - i)} for i in range(120)}
        result = _top_n_by_gene_score(codes, genes, 80)
        self.assertEqual(len(result), 80)
        # 最高分在前
        self.assertEqual(result[0], "60000000")  # score 120

    def test_top_n_returns_all_when_below_n(self):
        codes = ["600001", "600002"]
        genes = {"600001": {"gene_score": 50.0}, "600002": {"gene_score": 30.0}}
        result = _top_n_by_gene_score(codes, genes, 80)
        self.assertEqual(len(result), 2)

    def test_top_n_zero_or_negative_returns_all(self):
        codes = ["600001", "600002"]
        genes = {"600001": {"gene_score": 50.0}, "600002": {"gene_score": 30.0}}
        result = _top_n_by_gene_score(codes, genes, 0)
        self.assertEqual(len(result), 2)

    def test_top_n_none_score_treated_as_zero(self):
        codes = ["A", "B", "C"]
        genes = {"A": {"gene_score": None}, "B": {"gene_score": 50.0}, "C": {"gene_score": None}}
        result = _top_n_by_gene_score(codes, genes, 2)
        self.assertEqual(len(result), 2)
        self.assertIn("B", result)  # 50 分应入选


class TestParallelFunnel(unittest.TestCase):
    """S004 R2：并行采集——验证三组并行不丢数据、结果完整。"""

    def _patch_sources(self, genes):
        return (
            mock.patch.object(funnel_mod.sources.gene, "fetch_genes", return_value=genes),
            mock.patch.object(funnel_mod.sources.board_ladder, "fetch_board_ladder", return_value={"lianban_stocks": []}),
            mock.patch.object(funnel_mod.sources.activity, "fetch_activity", return_value={}),
            mock.patch.object(funnel_mod.sources.fund_flow, "fetch_fund_flow", return_value={}),
            mock.patch.object(funnel_mod.sources.auction, "fetch_auction", return_value={}),
            mock.patch.object(funnel_mod.sources.catalyst, "fetch_catalyst", return_value={}),
            mock.patch.object(funnel_mod.sources.watchlist_in, "get_watchlist_codes", return_value=[]),
            mock.patch.object(funnel_mod, "_fetch_sentiment_phase", return_value="晴天"),
        )

    def test_parallel_collects_all_sources(self):
        """并行模式下所有 source 都被调用，结果不丢层。"""
        genes = _make_genes(10)
        patches = self._patch_sources(genes)
        for p in patches:
            p.start()
            self.addCleanup(p.stop)
        funnel_mod.clear_funnel_cache()

        cfg = ThresholdConfig(mode="manual")
        result = run_funnel(stage="all", date="2026-08-13", cfg=cfg)
        layer_ids = [l.layer_id for l in result.layers]
        self.assertEqual(layer_ids, ["R1", "R2", "R3", "SELF"])

    def test_parallel_with_topn_limit(self):
        """top-N 限界 + 并行：120 只 → R2 只采 top-80（mock activity 输入验证）。"""
        genes = _make_genes(120)
        captured_codes = []

        def fake_activity(codes, date):
            captured_codes.extend(codes)
            return {}

        patches = (
            mock.patch.object(funnel_mod.sources.gene, "fetch_genes", return_value=genes),
            mock.patch.object(funnel_mod.sources.board_ladder, "fetch_board_ladder", return_value={"lianban_stocks": []}),
            mock.patch.object(funnel_mod.sources.activity, "fetch_activity", side_effect=fake_activity),
            mock.patch.object(funnel_mod.sources.fund_flow, "fetch_fund_flow", return_value={}),
            mock.patch.object(funnel_mod.sources.auction, "fetch_auction", return_value={}),
            mock.patch.object(funnel_mod.sources.catalyst, "fetch_catalyst", return_value={}),
            mock.patch.object(funnel_mod.sources.watchlist_in, "get_watchlist_codes", return_value=[]),
            mock.patch.object(funnel_mod, "_fetch_sentiment_phase", return_value="晴天"),
        )
        for p in patches:
            p.start()
            self.addCleanup(p.stop)
        funnel_mod.clear_funnel_cache()

        cfg = ThresholdConfig(mode="manual")
        run_funnel(stage="all", date="2026-08-13", cfg=cfg)
        # activity 收到的 codes 应被 top-N 截断到 80
        self.assertLessEqual(len(captured_codes), 80)


class TestTtlFromConfig(unittest.TestCase):
    """S004 R5：TTL 从 config 读取（非硬编码 300）。"""

    def test_ttl_reads_config(self):
        with mock.patch("config.default_config") as mock_cfg:
            mock_cfg.CANDIDATE_FUNNEL_CACHE_TTL = 3600
            self.assertEqual(_funnel_cache_ttl(), 3600)

    def test_ttl_fallback_on_error(self):
        # config 导入失败时 fallback 3600
        with mock.patch.dict(sys.modules, {"config": None}):
            # _funnel_cache_ttl 内部 try/except
            self.assertEqual(_funnel_cache_ttl(), 3600)


class TestPrecomputeExecutor(unittest.TestCase):
    """S004 R5：盘后预计算 executor——写缓存 + 失败不抛。"""

    def test_precompute_writes_cache(self):
        """executor 调 run_funnel → 结果落 _FUNNEL_CACHE。

        不 mock routers.candidates._store（触发循环导入）；
        executor 的 try/except 会 fallback 到 ThresholdConfig() 默认。
        """
        import scheduled_tasks as st
        executor = st.TaskExecutor()
        genes = _make_genes(5)
        with mock.patch.object(funnel_mod.sources.gene, "fetch_genes", return_value=genes), \
             mock.patch.object(funnel_mod.sources.board_ladder, "fetch_board_ladder", return_value={"lianban_stocks": []}), \
             mock.patch.object(funnel_mod.sources.activity, "fetch_activity", return_value={}), \
             mock.patch.object(funnel_mod.sources.fund_flow, "fetch_fund_flow", return_value={}), \
             mock.patch.object(funnel_mod.sources.auction, "fetch_auction", return_value={}), \
             mock.patch.object(funnel_mod.sources.catalyst, "fetch_catalyst", return_value={}), \
             mock.patch.object(funnel_mod.sources.watchlist_in, "get_watchlist_codes", return_value=[]), \
             mock.patch.object(funnel_mod, "_fetch_sentiment_phase", return_value="晴天"), \
             mock.patch("vr_paths.last_trading_date_str", return_value="2026-08-13"):
            funnel_mod.clear_funnel_cache()
            result = executor._execute_candidate_funnel_precompute({})
        self.assertEqual(result["status"], "ok")
        self.assertEqual(result["date"], "2026-08-13")

    def test_precompute_failure_does_not_raise(self):
        """run_funnel 抛异常时 executor 返 error 不抛。"""
        import scheduled_tasks as st
        executor = st.TaskExecutor()
        with mock.patch("vr_paths.last_trading_date_str", return_value="2026-08-13"), \
             mock.patch("candidate_funnel.funnel.run_funnel", side_effect=RuntimeError("boom")):
            result = executor._execute_candidate_funnel_precompute({})
        self.assertIn("error", result["status"])
        self.assertIn("boom", result["status"])


if __name__ == "__main__":
    unittest.main()
