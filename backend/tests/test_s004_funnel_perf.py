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
        self.assertEqual(layer_ids, ["R1", "R2", "SELF"])  # S148(b)：R3 层已删（annotate 并入 R2 tradability）

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


class TestR3DegradationContract(unittest.TestCase):
    """S004 R3 降级契约——S148(b) 删 R3 层后的不变量守护。

    原 R3 层（auction/catalyst annotate）已在 S148(b) 并入 R2 tradability（funnel.py
    _filter_tradability + R2 passed backfill matched_triggers）。本组从"R3 = R2 pass-through"
    改为守护：① R3 层不回归（防误加回）② auction/catalyst 双空或有数据时 final_candidates
    不丢候选（原契约核心意图：数据缺失不致候选清零）。
    """

    def _patch_sources(self, genes, activity, auction, catalyst):
        return (
            mock.patch.object(funnel_mod.sources.gene, "fetch_genes", return_value=genes),
            mock.patch.object(funnel_mod.sources.board_ladder, "fetch_board_ladder", return_value={"lianban_stocks": []}),
            mock.patch.object(funnel_mod.sources.activity, "fetch_activity", return_value=activity),
            mock.patch.object(funnel_mod.sources.fund_flow, "fetch_fund_flow", return_value={}),
            mock.patch.object(funnel_mod.sources.auction, "fetch_auction", return_value=auction),
            mock.patch.object(funnel_mod.sources.catalyst, "fetch_catalyst", return_value=catalyst),
            mock.patch.object(funnel_mod.sources.watchlist_in, "get_watchlist_codes", return_value=[]),
            mock.patch.object(funnel_mod, "_fetch_sentiment_phase", return_value="晴天"),
        )

    @staticmethod
    def _three_genes() -> dict:
        """3 只合成基因，code 避开 ST/退市段（600001 系安全）。"""
        return {
            "600001": {"name": "股票A", "gene_score": 90.0, "high_gene": True, "qualify": True},
            "600002": {"name": "股票B", "gene_score": 80.0, "high_gene": True, "qualify": True},
            "600003": {"name": "股票C", "gene_score": 70.0, "high_gene": False, "qualify": True},
        }

    @staticmethod
    def _three_activity(genes: dict) -> dict:
        """3 只 activity 全合格——turnover_pct=10.0 > turnover_cold=8.0（manual 默认），
        northbound 留空（_filter_r2: nb is None 保留不过滤）。"""
        return {c: {"name": g["name"], "turnover_pct": 10.0} for c, g in genes.items()}

    def _run(self, genes, activity, auction, catalyst):
        patches = self._patch_sources(genes, activity, auction, catalyst)
        for p in patches:
            p.start()
            self.addCleanup(p.stop)
        funnel_mod.clear_funnel_cache()
        cfg = ThresholdConfig(mode="manual")
        return run_funnel(stage="all", date="2026-08-13", cfg=cfg)

    def test_r3_degradation_when_auction_catalyst_both_empty(self):
        """S148(b) 删 R3 后：auction/catalyst 双空时 final_candidates 不丢候选（原 R3 pass-through 契约核心）。

        原 R3 层已删——本测守护：① "R3" 不在 layer_ids（防误加回 R3 层）
        ② R2 保留全量 ③ final_candidates 含全部 3 只（数据缺失不清零候选）。
        """
        genes = self._three_genes()
        activity = self._three_activity(genes)
        result = self._run(genes, activity, auction={}, catalyst={})

        layers_by_id = {l.layer_id: l for l in result.layers}
        # 契约 0：R3 层不回归（S148(b) 已删，防误加回）
        self.assertNotIn("R3", layers_by_id)
        r2 = layers_by_id["R2"]
        # 前提：R2 确实保留 3 只（否则测试本身失效，掩盖问题未暴露）
        self.assertEqual(r2.output_count, 3, "R2 应保留 3 只（activity 全合格），否则测试场景失效")
        self.assertEqual(sorted(r2.output_codes), ["600001", "600002", "600003"])
        # 契约：final_candidates 含全部 3 只（auction/catalyst 双空不清零候选）
        final_codes = {c.code for c in result.final_candidates}
        self.assertEqual(final_codes, {"600001", "600002", "600003"})

    def test_r3_normal_filter_when_auction_present(self):
        """S148(b) 删 R3 后：auction 有数据时 final_candidates 仍含全量（auction 不再收敛候选）。

        原 R3 层已删——auction 存在不再经漏斗层过滤（下放战法层）。本测守护：
        ① "R3" 不在 layer_ids ② auction 存在时 final_candidates 仍含全部 3 只
        （不收缩到仅有 auction_open_pct 的 600001——若未来漏斗层误加回 auction 过滤，本测会先红）。
        """
        genes = self._three_genes()
        activity = self._three_activity(genes)
        auction = {"600001": {"auction_open_pct": 5.0}}  # 仅 600001 有竞价异动
        result = self._run(genes, activity, auction=auction, catalyst={})

        layers_by_id = {l.layer_id: l for l in result.layers}
        self.assertNotIn("R3", layers_by_id)
        # 契约：final_candidates 含全部 3 只（auction 不再收敛候选）
        self.assertEqual({c.code for c in result.final_candidates}, {"600001", "600002", "600003"})


if __name__ == "__main__":
    unittest.main()
