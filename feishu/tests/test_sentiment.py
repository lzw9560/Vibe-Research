# -*- coding: utf-8 -*-
"""test_sentiment.py — calculate_sentiment_score 单测。

calculate_sentiment_score 是纯函数，支持 data 参数注入，无需 mock CLI。
测试覆盖：
- 输入边界值（空数据/全空字段）
- 正常值（各分项得分组合）
- 状态判定（冰点/震荡/沸点三档）
"""
from __future__ import annotations

from feishu.sentiment import (
    calculate_sentiment_score,
    _score_volume,
    _score_effect,
    _score_ladder,
    _score_flow,
    _determine_state,
)


# ─── 分项评分函数单测 ───

class TestScoreVolume:
    def test_extreme_high(self):
        assert _score_volume(20000) == 25  # >15000

    def test_high(self):
        assert _score_volume(12000) == 20  # >10000

    def test_medium(self):
        assert _score_volume(8000) == 15  # >7000

    def test_low(self):
        assert _score_volume(5000) == 5  # 地量

    def test_boundary_15000(self):
        # 15000 不 > 15000 → 落 10000 档
        assert _score_volume(15000) == 20

    def test_boundary_10000(self):
        assert _score_volume(10000) == 15

    def test_zero(self):
        assert _score_volume(0) == 5


class TestScoreEffect:
    def test_extreme_bull(self):
        # up_ratio > 0.75 且 limit_down < 10
        assert _score_effect(800, 200, 5) == 25

    def test_bull_high_limit_down(self):
        # up_ratio > 0.75 但 limit_down >= 10 → 不满足冰点豁免条件
        assert _score_effect(800, 200, 15) == 18  # 落 >0.55 档

    def test_moderate_up(self):
        assert _score_effect(600, 400, 0) == 18  # 0.6 > 0.55

    def test_neutral(self):
        assert _score_effect(500, 500, 0) == 12  # 0.5 > 0.45

    def test_bear(self):
        assert _score_effect(200, 800, 0) == 5  # 0.2 <= 0.45

    def test_no_data(self):
        # up+down == 0 → up_ratio = 0.5 → 12
        assert _score_effect(0, 0, 0) == 12


class TestScoreLadder:
    def test_seven_plus(self):
        assert _score_ladder(7) == 22

    def test_five(self):
        assert _score_ladder(5) == 18

    def test_three(self):
        assert _score_ladder(3) == 12

    def test_two(self):
        assert _score_ladder(2) == 8

    def test_one(self):
        assert _score_ladder(1) == 3

    def test_zero(self):
        assert _score_ladder(0) == 3


class TestScoreFlow:
    def test_high_inflow(self):
        assert _score_flow(6) == 13  # >5亿

    def test_moderate_inflow(self):
        assert _score_flow(3) == 8  # >0

    def test_outflow(self):
        assert _score_flow(-1) == 3  # <=0

    def test_zero(self):
        assert _score_flow(0) == 3

    def test_boundary_5(self):
        assert _score_flow(5) == 8  # 5 不 > 5


# ─── 状态判定 ───

class TestDetermineState:
    def test_freezing(self):
        state, alloc, strategy, wencai, risk = _determine_state(35)
        assert "冰点" in state
        assert alloc["长线"] == 70
        assert "DRIP" in strategy

    def test_freezing_boundary(self):
        # 35 是冰点上限（<=35）
        state, *_ = _determine_state(35)
        assert "冰点" in state

    def test_oscillation(self):
        state, alloc, strategy, wencai, risk = _determine_state(70)
        assert "震荡" in state
        assert alloc["中线"] == 50
        assert "波段" in strategy

    def test_boiling(self):
        state, alloc, strategy, wencai, risk = _determine_state(71)
        assert "沸点" in state
        assert alloc["短线"] == 70
        assert "打板" in strategy

    def test_zero_is_freezing(self):
        state, *_ = _determine_state(0)
        assert "冰点" in state

    def test_max_is_boiling(self):
        state, *_ = _determine_state(100)
        assert "沸点" in state


# ─── calculate_sentiment_score 集成（注入 data） ───

class TestCalculateSentimentScore:
    def test_empty_data(self):
        """空数据 → 全分项走默认值/地量档。"""
        result = calculate_sentiment_score(data={})
        # vol: 无 indices → 15（默认）
        # effect: 无 stocks → up_ratio=0.5 → 12
        # ladder: 无 → max_boards=0 → 3
        # flow: 无 → total_net=0 → 3
        # total = 15+12+3+3 = 33 → 冰点
        assert result["score"] == 33
        assert "冰点" in result["state"]
        assert result["up_count"] == 0
        assert result["down_count"] == 0

    def test_boiling_market(self):
        """沸点市场：巨量 + 普涨 + 高连板 + 大净买入。"""
        data = {
            "indices": [{"turnover": 2e12}],  # 20000亿 → vol=25
            "all_stocks": [
                {"price_change_ratio_pct": 5.0} for _ in range(800)
            ] + [{"price_change_ratio_pct": -2.0} for _ in range(200)],
            # up=800, down=200, up_ratio=0.8>0.75, limit_down=0<10 → effect=25
            "ladder": [{"boards": {"seven_over": [{"board_num": 7}]}}],
            # max_boards=7 → ladder=22
            "dragon": [{"net_value": 6e8} for _ in range(10)],
            # total_net=6e9 → 60亿 → flow=13
        }
        result = calculate_sentiment_score(data=data)
        # 25+25+22+13 = 85 → 沸点
        assert result["score"] == 85
        assert "沸点" in result["state"]
        assert result["vol_score"] == 25
        assert result["effect_score"] == 25
        assert result["ladder_score"] == 22
        assert result["flow_score"] == 13
        assert result["max_boards"] == 7
        assert result["up_count"] == 800
        assert result["down_count"] == 200
        assert result["allocation"]["短线"] == 70

    def test_freezing_market(self):
        """冰点市场：地量 + 普跌 + 无连板 + 净流出。"""
        data = {
            "indices": [{"turnover": 3e11}],  # 3000亿 → vol=5
            "all_stocks": [
                {"price_change_ratio_pct": -3.0} for _ in range(800)
            ] + [{"price_change_ratio_pct": 1.0} for _ in range(200)],
            # up=200, down=800, up_ratio=0.2 → effect=5
            "ladder": [{"boards": {}}],  # 无连板 → max_boards=0 → ladder=3
            "dragon": [{"net_value": -1e8} for _ in range(10)],
            # total_net=-1e9 → -10亿 → flow=3
        }
        result = calculate_sentiment_score(data=data)
        # 5+5+3+3 = 16 → 冰点
        assert result["score"] == 16
        assert "冰点" in result["state"]
        assert result["allocation"]["长线"] == 70

    def test_limit_up_down_counted(self):
        """涨跌停统计：chg>=9.5 计 limit_up，<=-9.5 计 limit_down。"""
        data = {
            "all_stocks": [
                {"price_change_ratio_pct": 10.0},   # limit_up
                {"price_change_ratio_pct": 9.5},    # limit_up (边界)
                {"price_change_ratio_pct": -10.0},  # limit_down
                {"price_change_ratio_pct": -9.5},   # limit_down (边界)
                {"price_change_ratio_pct": 9.4},    # up 但非涨停
            ],
        }
        result = calculate_sentiment_score(data=data)
        assert result["limit_up"] == 2
        assert result["limit_down"] == 2
        assert result["up_count"] == 3  # 10, 9.5, 9.4 都 >0
        assert result["down_count"] == 2

    def test_none_chg_skipped(self):
        """chg 为 None 的条目跳过（不计入涨跌家数）。"""
        data = {
            "all_stocks": [
                {"price_change_ratio_pct": None},
                {"price_change_ratio_pct": 5.0},
            ],
        }
        result = calculate_sentiment_score(data=data)
        assert result["up_count"] == 1
        assert result["down_count"] == 0

    def test_return_keys_complete(self):
        """返回 dict 包含所有契约字段。"""
        result = calculate_sentiment_score(data={})
        required = {
            "score", "state", "vol_score", "effect_score", "ladder_score",
            "flow_score", "max_boards", "up_count", "down_count",
            "limit_up", "limit_down", "total_turnover_yi",
            "allocation", "strategy", "wencai", "risk",
        }
        assert required.issubset(result.keys()), f"缺少字段: {required - result.keys()}"

    def test_allocation_keys(self):
        """allocation dict 包含长线/中线/短线三键。"""
        result = calculate_sentiment_score(data={})
        assert set(result["allocation"].keys()) == {"长线", "中线", "短线"}
