# -*- coding: utf-8 -*-
"""S194 R4 · fusion_layer 单测——综合 FS1 检索 + FS2 权重 + 对齐信号 → 研判产出喂 AI。

fusion_layer(signals_aligned, fs1_results, fs2_weights) → {regime, direction, confidence,
top_similar_cases, signal_weights}。不直接触发买卖（喂 AI 综合研判 + 用户决策，§1 弱合规）。
"""
from __future__ import annotations

import math

from engine.fusion_layer import fusion_layer


def _sig(name, value, confidence=0.5):
    return {"signal_name": name, "value": value, "confidence": confidence,
            "timestamp": "2026-09-13", "source": name}


class TestFusionLayer:
    def test_regime_from_gap_signal_value(self):
        """regime 取 gap 信号 value（缺口 regime 字符串）。"""
        signals = [_sig("gap", "趋势启动", 0.7), _sig("breakout", 0.95, 0.9)]
        out = fusion_layer(signals, fs1_results=[], fs2_weights={"gap": 0.5, "breakout": 0.3})
        assert out["regime"] == "趋势启动"

    def test_regime_unknown_when_no_gap(self):
        """无 gap 信号 → regime='未知'。"""
        signals = [_sig("breakout", 0.95, 0.9)]
        out = fusion_layer(signals, fs1_results=[], fs2_weights={"breakout": 0.3})
        assert out["regime"] == "未知"

    def test_direction_from_regime(self):
        """direction 由 regime 派生：趋势启动/中继→向上，反转/噪声/无→中性。"""
        for regime, direction in [("趋势启动", "向上"), ("趋势中继", "向上"),
                                  ("反转", "中性"), ("噪声", "中性"), ("无", "中性")]:
            out = fusion_layer([_sig("gap", regime, 0.5)], [], {"gap": 0.5})
            assert out["direction"] == direction, f"{regime}→{direction}"

    def test_confidence_weighted_by_fs2(self):
        """confidence = Σ(sig_conf × fs2_weight) / Σ(fs2_weight)（FS2 加权信号置信度）。"""
        signals = [_sig("gap", "趋势启动", 0.7), _sig("breakout", 0.95, 0.9)]
        out = fusion_layer(signals, [], fs2_weights={"gap": 0.5, "breakout": 0.3})
        # (0.7×0.5 + 0.9×0.3)/(0.5+0.3) = (0.35+0.27)/0.8 = 0.62/0.8 = 0.775
        assert math.isclose(out["confidence"], 0.775, rel_tol=1e-9)

    def test_confidence_zero_when_no_signals(self):
        """无信号 → confidence=0.0。"""
        out = fusion_layer([], [], {"gap": 0.5})
        assert out["confidence"] == 0.0

    def test_signal_not_in_fs2_weights_excluded_from_confidence(self):
        """信号不在 fs2_weights → 权重 0，排除出 confidence 加权（不臆造权重）。"""
        signals = [_sig("gap", "趋势启动", 0.7), _sig("ofi", 0.4, 0.5)]  # ofi 不在 weights
        out = fusion_layer(signals, [], fs2_weights={"gap": 0.5})  # 只 gap 有权重
        # (0.7×0.5 + 0.5×0)/0.5 = 0.35/0.5 = 0.7
        assert math.isclose(out["confidence"], 0.7, rel_tol=1e-9)

    def test_top_similar_cases_pass_through(self):
        """fs1_results 透传到 top_similar_cases（喂 AI 看）。"""
        fs1 = [{"case": {"stock": "000001"}, "similarity": 0.9, "outcome": "hit"}]
        out = fusion_layer([_sig("gap", "趋势启动", 0.7)], fs1, {"gap": 0.5})
        assert out["top_similar_cases"] == fs1

    def test_signal_weights_pass_through(self):
        """fs2_weights 透传到 signal_weights。"""
        weights = {"gap": 0.5, "breakout": 0.3}
        out = fusion_layer([_sig("gap", "趋势启动", 0.7)], [], weights)
        assert out["signal_weights"] == weights

    def test_output_keys(self):
        """输出含 spec §3 R4 要求的 5 字段。"""
        out = fusion_layer([_sig("gap", "趋势启动", 0.7)], [], {"gap": 0.5})
        assert set(out.keys()) == {"regime", "direction", "confidence", "top_similar_cases", "signal_weights"}
