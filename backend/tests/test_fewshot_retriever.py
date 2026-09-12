# -*- coding: utf-8 -*-
"""S194 R2 · fewshot_retriever 单测——FS1 检索历史相似 case（不过 §44）。

纯函数：cosine_sim + encode_case + retrieve + FewshotRetriever 类。
历史 case 用 reconstruct_s194_signals.py 重建的信号值（breakout_score + gap_regime_encoded）
作特征；query 是当天对齐后信号；cosine 相似度 top-K → [{case, similarity, outcome}] 喂 AI。

⚠️ FS1 不过 §44（spec §2.1 + §3 R2）：AI 推理非确定 + 全库检索 lookahead 泄漏（无 in/out-sample 划分）
→ §44v2 verifier 套不上，价值靠「AI 研判 + 用户反馈」定性评估，不参与 F1 消融 §44 验证。
"""
from __future__ import annotations

import math

import numpy as np

from engine.fewshot_retriever import (
    FewshotRetriever,
    cosine_sim,
    encode_case,
    retrieve,
)


class TestCosineSim:
    def test_identical_vectors(self):
        """相同向量 → 1.0。"""
        assert math.isclose(cosine_sim(np.array([1, 2, 3]), np.array([1, 2, 3])), 1.0)

    def test_orthogonal(self):
        """正交 → 0.0。"""
        assert math.isclose(cosine_sim(np.array([1, 0]), np.array([0, 1])), 0.0, abs_tol=1e-9)

    def test_opposite(self):
        """反向 → -1.0。"""
        assert math.isclose(cosine_sim(np.array([1, 1]), np.array([-1, -1])), -1.0, abs_tol=1e-9)

    def test_zero_vector_safe(self):
        """零向量 → 0.0（防除零，不崩）。"""
        assert cosine_sim(np.array([0, 0]), np.array([1, 2])) == 0.0


class TestEncodeCase:
    def test_extracts_feature_values(self):
        """按 feature_names 顺序提取信号值。"""
        case = {"breakout_score": 0.95, "gap_regime_encoded": 0.7, "other": 99}
        v = encode_case(case, ["breakout_score", "gap_regime_encoded"])
        assert np.allclose(v, [0.95, 0.7])

    def test_missing_feature_defaults_zero(self):
        """缺特征 → 0.0（信号未触发）。"""
        v = encode_case({"breakout_score": 0.9}, ["breakout_score", "gap_regime_encoded"])
        assert v[1] == 0.0

    def test_none_value_defaults_zero(self):
        """None 值（取数失败）→ 0.0（不臆造）。"""
        v = encode_case({"breakout_score": None, "gap_regime_encoded": 0.5},
                        ["breakout_score", "gap_regime_encoded"])
        assert v[0] == 0.0


class TestRetrieve:
    def test_returns_top_k_ranked_by_similarity(self):
        """返 top_k 条，按相似度降序。"""
        cases = [
            {"breakout_score": 0.9, "gap_regime_encoded": 0.7, "net_pnl": 50},
            {"breakout_score": 0.2, "gap_regime_encoded": 0.1, "net_pnl": -30},
            {"breakout_score": 0.95, "gap_regime_encoded": 0.7, "net_pnl": 80},  # 最像 query
            {"breakout_score": 0.3, "gap_regime_encoded": 0.0, "net_pnl": -10},
        ]
        query = {"breakout_score": 0.95, "gap_regime_encoded": 0.7}
        out = retrieve(query, cases, ["breakout_score", "gap_regime_encoded"], top_k=2)
        assert len(out) == 2
        assert out[0]["similarity"] >= out[1]["similarity"]  # 降序
        assert out[0]["case"]["breakout_score"] == 0.95  # 最像的排第一

    def test_exact_match_highest_similarity(self):
        """完全匹配的 case 相似度 1.0 排第一。"""
        cases = [{"breakout_score": 0.5, "gap_regime_encoded": 0.5, "net_pnl": 10},
                 {"breakout_score": 0.9, "gap_regime_encoded": 0.7, "net_pnl": 20}]
        query = {"breakout_score": 0.9, "gap_regime_encoded": 0.7}
        out = retrieve(query, cases, ["breakout_score", "gap_regime_encoded"], top_k=2)
        assert math.isclose(out[0]["similarity"], 1.0)
        assert out[0]["case"]["net_pnl"] == 20

    def test_empty_cases_returns_empty(self):
        """空 case 库 → 空。"""
        assert retrieve({"breakout_score": 0.9}, [], ["breakout_score"], top_k=5) == []

    def test_outcome_classified_hit_miss_neutral(self):
        """outcome 按 net_pnl 符号分类（hit/miss/neutral）喂 AI 研判。"""
        cases = [
            {"breakout_score": 0.9, "net_pnl": 50},    # hit
            {"breakout_score": 0.9, "net_pnl": -30},   # miss
            {"breakout_score": 0.9, "net_pnl": 0},     # neutral
            {"breakout_score": 0.9, "net_pnl": None},  # neutral（None→0）
        ]
        out = retrieve({"breakout_score": 0.9}, cases, ["breakout_score"], top_k=4)
        outcomes = [r["outcome"] for r in out]
        assert "hit" in outcomes
        assert "miss" in outcomes
        assert outcomes.count("neutral") == 2


class TestFewshotRetriever:
    def test_class_retrieve_uses_case_library(self):
        """类持 case 库 + feature_names，retrieve 查询。"""
        cases = [{"breakout_score": 0.9, "gap_regime_encoded": 0.7, "net_pnl": 50}]
        fr = FewshotRetriever(cases)
        out = fr.retrieve({"breakout_score": 0.9, "gap_regime_encoded": 0.7}, top_k=1)
        assert len(out) == 1
        assert math.isclose(out[0]["similarity"], 1.0)

    def test_default_feature_names(self):
        """默认 feature_names = [breakout_score, gap_regime_encoded]。"""
        fr = FewshotRetriever([{"breakout_score": 0.5, "gap_regime_encoded": 0.5}])
        assert fr._feature_names == ["breakout_score", "gap_regime_encoded"]
