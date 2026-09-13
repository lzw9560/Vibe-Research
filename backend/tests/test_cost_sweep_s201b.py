# -*- coding: utf-8 -*-
"""S201b cost-sweep 纯函数 compute_net_at_levels 测试。

测：各口径 net returns 单调（cost 越高 net 越低）+ 逐笔口径独立 + 返 5 口径。
"""
from __future__ import annotations

from tools.cost_sweep_s201b import compute_net_at_levels


def test_returns_monotonic_decreasing_with_cost():
    """cost 越高 net 越低（单调）。"""
    gross = [0.02, 0.03, -0.01, 0.05]  # 分数
    per_trade = [1.46, 1.46, 1.46, 1.46]  # 百分数（统一便于比较）
    sweeps = compute_net_at_levels(gross, per_trade, levels_pct=[0.10, 0.20, 0.30, 0.70])
    # flat 口径 mean net 单调递减
    means = [sum(s["returns"]) / len(s["returns"]) for s in sweeps[:4]]
    assert means[0] > means[1] > means[2] > means[3], f"flat 口径 net 应随 cost 递减: {means}"


def test_per_trade_level_distinct_from_flat():
    """逐笔口径独立（label 含 _cost_pct，returns 用 per_trade_costs）。"""
    gross = [0.02, 0.03]
    per_trade = [1.0, 2.0]  # 不同 per-trade cost
    sweeps = compute_net_at_levels(gross, per_trade)
    per_trade_sweep = sweeps[-1]
    assert "_cost_pct" in per_trade_sweep["label"]
    # 逐笔 net = gross - per_trade/100
    assert per_trade_sweep["returns"] == [0.02 - 1.0/100, 0.03 - 2.0/100]


def test_returns_count_matches_input():
    """每口径 returns 数 = gross 数。"""
    gross = [0.01] * 5
    per_trade = [1.0] * 5
    sweeps = compute_net_at_levels(gross, per_trade, levels_pct=[0.10, 0.70])
    # 2 flat + 1 逐笔 = 3
    assert len(sweeps) == 3
    for s in sweeps:
        assert len(s["returns"]) == 5


def test_empty_inputs_safe():
    """空输入不崩。"""
    sweeps = compute_net_at_levels([], [], levels_pct=[0.10])
    assert len(sweeps) == 2  # 1 flat + 1 逐笔
    # mean_cost=0, 逐笔 returns=[]
    assert sweeps[-1]["returns"] == []
    assert sweeps[-1]["cost_pct_mean"] == 0.0


def test_round_trip_cost_fraction():
    """round_trip_cost 是分数（0.007=0.7%），非百分数。"""
    from pytest import approx
    gross = [0.02]
    per_trade = [1.46]
    sweeps = compute_net_at_levels(gross, per_trade, levels_pct=[0.70])
    assert sweeps[0]["round_trip_cost"] == approx(0.007)  # 0.70% → 分数
    assert sweeps[1]["round_trip_cost"] == approx(0.0146)  # mean 1.46% → 分数
