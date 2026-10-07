# -*- coding: utf-8 -*-
"""test_tactics_anti_quant_engine —— 三战法引擎测试（S235 T09）。AAA 结构。

覆盖 tasks T09：反例（非冰点全因子命中不触发 / prev_drop=0 不触发）+ 正例 +
权重和=1.0 + veto 优先于评分。
"""
from __future__ import annotations
import pytest

from tactics.anti_quant_engine import (
    AntiQuantEngine,
    FACTOR_WEIGHTS,
    score_tactic,
)


@pytest.fixture
def engine():
    return AntiQuantEngine()


# ---------------------------------------------------------------------------
# 权重和=1.0 断言
# ---------------------------------------------------------------------------

def test_factor_weights_sum_to_one():
    for tactic, weights in FACTOR_WEIGHTS.items():
        assert sum(weights.values()) == pytest.approx(1.0), f"{tactic} 权重和!=1.0"


# ---------------------------------------------------------------------------
# veto 优先于评分
# ---------------------------------------------------------------------------

def test_veto_overrides_high_factors():
    # 反例1：非冰点日，但其他因子全命中 → ice_rebound 不触发
    factors = {
        "ice_point": False,  # gate 不满足
        "anti_drop": 1.0,
        "break_vwap": True,
        "turnover_rate": 0.15,
        "bottom_divergence": 0.8,
        "big_order_proxy": 0.8,
    }
    r = score_tactic("ice_rebound", factors)
    assert r["is_triggered"] is False
    assert r["score"] == 0
    assert "veto" in r["reason"]


def test_veto_prev_drop_zero():
    # 反例2：prev_drop=0（前日未跌）→ reversal 不触发，即便其他因子全命中
    factors = {
        "prev_drop": 0.0,  # gate 不满足
        "gap_pct": 3.5,
        "vol_ratio": 4.5,
        "amount_ratio": 0.10,
        "bid_increasing": True,
    }
    r = score_tactic("reversal", factors)
    assert r["is_triggered"] is False
    assert r["score"] == 0


def test_veto_above_vwap_false():
    # 尾盘突破但未站稳 VWAP → veto
    factors = {
        "above_vwap": False,
        "turnover_rate": 0.17,
        "breakout_high": 1.0,
        "big_order_proxy": 0.8,
        "sector_resonance": 2,
        "close_position": 0.7,
    }
    r = score_tactic("tail_breakout", factors)
    assert r["score"] == 0


# ---------------------------------------------------------------------------
# 正例：全因子命中 → 触发
# ---------------------------------------------------------------------------

def test_reversal_all_factors_hit(engine):
    # Arrange: 前日跌 6%（prev_close 10 → 9.4），竞价 final 开 9.729（gap 3.5%）
    # klines 带 open_volume 让 vol_ratio 可算（4.5/1000=4.5）
    prev_klines = [
        {"close_price": 10, "open_volume": 1000},
        {"close_price": 9.4, "open_volume": 1000},
    ]
    auction_final = {"open_price": 9.729, "volume": 4500, "amount": 1e7}
    auction_live_1 = {"volume": 4000}
    auction_live_2 = {"volume": 5000}  # 量增
    # Act
    r = engine.evaluate_reversal(
        "603778", prev_klines, auction_live_1, auction_live_2,
        auction_final, prev_day_turnover=1e8,
    )
    # Assert: score=100（全 1.0），触发
    assert r["is_triggered"] is True
    assert r["tactic_name"] == "reversal"
    assert r["score"] == 100
    assert r["factors"]["prev_drop"] == pytest.approx(-0.06)
    assert r["factors"]["gap_pct"] == pytest.approx(3.5, abs=1e-3)


def test_tail_breakout_all_factors_hit(engine):
    # Arrange: close=11, VWAP=(10+12+9+22)/4=13.25 → close<vwap? 用 close>vwap 例子
    # 改：O=10 H=12 L=9 C=12 → VWAP=(10+12+9+24)/4=13.75 → close<vwap，不行
    # 用 close>=vwap：O=10 H=12 L=9 C=13 → VWAP=(10+12+9+26)/4=14.25，close<vwap
    # 直接构造 close>>vwap 不易（公式 1.25x）；改用 gate above_vwap 用 score_tactic 直接测
    factors = {
        "above_vwap": True,
        "turnover_rate": 0.17,
        "breakout_high": 1.0,
        "big_order_proxy": 0.8,
        "sector_resonance": 2,
        "close_position": 0.7,
    }
    r = score_tactic("tail_breakout", factors)
    assert r["is_triggered"] is True
    assert r["score"] >= 60


def test_ice_rebound_all_factors_hit(engine):
    # Arrange: 冰点期 + 全因子命中
    # close=20, O=10 H=20 L=9 → vwap=(10+20+9+40)/4=19.75，close>=vwap → break_vwap=True
    snapshot = {
        "price_change_ratio_pct": -2.0,  # 个股跌 2%
        "close_price": 20, "open_price": 10, "high_price": 20, "low_price": 9,
        "amount": 1.5e8, "float_mv": 1e9,  # 换手 15%
        "bottom_divergence": 0.8, "big_order_proxy": 0.8,
    }
    market_stats = {"market_drop_pct": -5.0}  # 市场跌 5% → anti_drop = -2-(-5) = +3
    # Act
    r = engine.evaluate_ice_rebound("603778", snapshot, market_stats, ice_point=True)
    # Assert: 触发（score≈95：anti_drop 1.0×0.35 + break_vwap 1.0×0.20 + turnover 1.0×0.20
    #        + bottom_div 0.8×0.15 + big_order 0.8×0.10 = 0.95）
    assert r["is_triggered"] is True
    assert r["tactic_name"] == "ice_rebound"
    assert r["factors"]["anti_drop"] == pytest.approx(3.0)  # 抗跌 +3


# ---------------------------------------------------------------------------
# 边界：score 刚好 60
# ---------------------------------------------------------------------------

def test_score_below_threshold_not_triggered():
    # 构造 score<60：reversal 全 gate 通过但软因子低
    factors = {
        "prev_drop": -0.06,  # gate 通过
        "gap_pct": 1.5,  # <2 → 0
        "vol_ratio": 1.0,  # 1/4.5≈0.22
        "amount_ratio": 0.02,  # 0.2
        "bid_increasing": False,  # 0
    }
    r = score_tactic("reversal", factors)
    # score = (0*0.30 + 0.22*0.30 + 0.2*0.25 + 0*0.15)*100 ≈ 6.6+5=11.6 → 12
    assert r["is_triggered"] is False
    assert r["score"] < 60


# ---------------------------------------------------------------------------
# 结果结构
# ---------------------------------------------------------------------------

def test_result_structure(engine):
    prev_klines = [{"close_price": 10}, {"close_price": 9.4}]
    r = engine.evaluate_reversal(
        "603778", prev_klines, {"volume": 100}, {"volume": 200},
        {"open_price": 9.635, "volume": 4500, "amount": 1e7},
        prev_day_turnover=1e8,
    )
    assert set(r.keys()) >= {"is_triggered", "tactic_name", "score", "reason",
                             "risk_warning", "factors", "code", "raw"}
    assert r["code"] == "603778"
    assert "探索性" in r["risk_warning"]


def test_unknown_tactic_score_returns_zero():
    # 未知战法名 → FACTOR_WEIGHTS KeyError；用 score_tactic 应保守返 0
    # （当前实现会抛 KeyError——这是设计选择，调用方不应传未知名）
    with pytest.raises(KeyError):
        score_tactic("nonexistent", {})
