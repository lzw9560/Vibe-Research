# -*- coding: utf-8 -*-
"""S079 阶段 B 单测：_market_phase 扩展（R6）+ cap_by_market_phase（R7）。

覆盖：
- B5 _market_phase：四档判定 + 红期硬熔断覆盖 + 向后兼容（旧签名不破坏）
- B12 cap_by_market_phase：三状态 cap 映射 + 叠加代数 min() + 绿档不放宽 + 互斥
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

backend_dir = Path(__file__).resolve().parent.parent
if str(backend_dir) not in sys.path:
    sys.path.insert(0, str(backend_dir))

from strategies.first_board_filter import (
    _market_phase,
    PHASE_TO_CAP_TIER,
)
from strategies.position_advisor import (
    PositionSuggestion,
    cap_by_market_phase,
    MARKET_PHASE_CAP,
)


# ---------------------------------------------------------------------------
# 构造 PositionSuggestion 工具
# ---------------------------------------------------------------------------

def _make_pos(code: str = "600000", suggested_pct: float = 0.2) -> PositionSuggestion:
    """构造一个 PositionSuggestion（advise_batch 输出的模拟）。"""
    return PositionSuggestion(
        code=code,
        name=f"test_{code}",
        suggested_pct=suggested_pct,
        confidence="medium",
        entry_price_range=(9.9, 10.1),
        stop_loss=9.0,
        take_profit=11.0,
        matched_strategy="test_strategy",
        reasons=["test"],
    )


# ===========================================================================
# B5：_market_phase 扩展单测（R6）
# ===========================================================================

class TestMarketPhaseBackwardCompat:
    """R6.5 向后兼容：旧签名 `_market_phase(zt_count)` 不破坏。"""

    def test_old_signature_single_arg(self):
        """旧调用 `_market_phase(40)` 走原四档判定，不报错。"""
        assert _market_phase(40) == "普通"
        assert _market_phase(20) == "冰点"
        assert _market_phase(80) == "活跃"
        assert _market_phase(120) == "亢奋"

    def test_old_signature_none(self):
        """旧调用 `_market_phase(None)` 返回"普通"（中性档）。"""
        assert _market_phase(None) == "普通"

    def test_keyword_only_zt_count(self):
        """关键字调用仅传 zt_count，big_loss 等 None 跳过红期硬熔断。"""
        assert _market_phase(zt_count=40) == "普通"
        assert _market_phase(zt_count=80, big_loss=None, floor=None) == "活跃"


class TestMarketPhaseFourTier:
    """R6.1 四档判定保留（红期硬熔断未触发时走原逻辑）。"""

    @pytest.mark.parametrize("zt_count,expected", [
        (0, "冰点"),
        (29, "冰点"),
        (30, "普通"),
        (59, "普通"),
        (60, "活跃"),
        (99, "活跃"),
        (100, "亢奋"),
        (200, "亢奋"),
    ])
    def test_four_tier_thresholds(self, zt_count, expected):
        assert _market_phase(zt_count, big_loss=0, floor=0) == expected


class TestMarketPhaseRedPeriodOverride:
    """R6.2 红期硬熔断覆盖（big_loss≥8 或 floor≥20 时强制返回"红期"）。"""

    def test_big_loss_threshold_8(self):
        """big_loss=8 → 红期（边界值）。"""
        assert _market_phase(zt_count=80, big_loss=8, floor=0) == "红期"

    def test_big_loss_above_threshold(self):
        """big_loss=12 → 红期（覆盖四档）。"""
        assert _market_phase(zt_count=80, big_loss=12, floor=0) == "红期"

    def test_big_loss_below_threshold(self):
        """big_loss=3 → 走四档判定（不触发红期）。"""
        assert _market_phase(zt_count=80, big_loss=3, floor=0) == "活跃"

    def test_floor_threshold_20(self):
        """floor=20 → 红期（边界值）。"""
        assert _market_phase(zt_count=80, big_loss=0, floor=20) == "红期"

    def test_floor_above_threshold(self):
        """floor=30 → 红期（覆盖四档）。"""
        assert _market_phase(zt_count=80, big_loss=0, floor=30) == "红期"

    def test_floor_below_threshold(self):
        """floor=10 → 走四档判定（不触发红期）。"""
        assert _market_phase(zt_count=80, big_loss=0, floor=10) == "活跃"

    def test_both_triggers(self):
        """big_loss + floor 同时触发 → 红期。"""
        assert _market_phase(zt_count=80, big_loss=10, floor=25) == "红期"

    def test_red_period_overrides_hot(self):
        """红期硬熔断覆盖亢奋档（zt_count=120 但 big_loss=8）。"""
        assert _market_phase(zt_count=120, big_loss=8, floor=0) == "红期"

    def test_red_period_overrides_cold(self):
        """红期硬熔断覆盖冰点档（zt_count=10 但 floor=20）。"""
        assert _market_phase(zt_count=10, big_loss=0, floor=20) == "红期"


class TestPhaseToCapTier:
    """R6.3 三状态映射常量。"""

    def test_green_tier(self):
        """活跃/亢奋 → green。"""
        assert PHASE_TO_CAP_TIER["活跃"] == "green"
        assert PHASE_TO_CAP_TIER["亢奋"] == "green"

    def test_yellow_tier(self):
        """普通 → yellow。"""
        assert PHASE_TO_CAP_TIER["普通"] == "yellow"

    def test_red_tier(self):
        """冰点/红期 → red。"""
        assert PHASE_TO_CAP_TIER["冰点"] == "red"
        assert PHASE_TO_CAP_TIER["红期"] == "red"

    def test_all_five_phases_covered(self):
        """5 个 phase 映射齐全。"""
        assert set(PHASE_TO_CAP_TIER.keys()) == {"活跃", "亢奋", "普通", "冰点", "红期"}


# ===========================================================================
# B12：cap_by_market_phase 单测（R7）
# ===========================================================================

class TestCapByMarketPhaseMapping:
    """R7.1 三状态 cap 映射。"""

    def test_market_phase_cap_constants(self):
        """MARKET_PHASE_CAP 常量：green=1.0/yellow=0.5/red=0.2。"""
        assert MARKET_PHASE_CAP["green"] == 1.0
        assert MARKET_PHASE_CAP["yellow"] == 0.5
        assert MARKET_PHASE_CAP["red"] == 0.2

    def test_unknown_phase_degrades_yellow(self):
        """未知 phase 降级 yellow（保守）。"""
        pos = _make_pos(suggested_pct=0.2)
        result = cap_by_market_phase([pos], phase="未知状态")
        # yellow cap=0.5，max_single_position=0.3 → 0.3*0.5=0.15
        assert result[0].suggested_pct == 0.15
        assert result[0].market_phase == "未知状态"
        assert result[0].market_phase_cap == 0.5


class TestCapByMarketPhaseAlgebra:
    """R7.1 叠加代数：final_cap = min(weather_cap, market_phase_cap, max_total_position)。"""

    def test_green_no_widening(self):
        """R7.2 绿档不放宽：green cap=1.0，不顶掉既有单票上限。"""
        # suggested_pct=0.2（weather_cap 后），green cap=1.0
        # market_phase_cap_result = min(0.2, 0.3*1.0)=min(0.2,0.3)=0.2
        # final = min(0.2, 0.2, 0.8) = 0.2
        pos = _make_pos(suggested_pct=0.2)
        result = cap_by_market_phase([pos], phase="活跃")
        assert result[0].suggested_pct == 0.2
        assert result[0].market_phase == "活跃"
        assert result[0].market_phase_cap == 1.0

    def test_green_caps_at_max_single(self):
        """R7.2 绿档：suggested_pct 超过 max_single_position 时被 cap 收紧。"""
        # suggested_pct=0.4（weather 后异常高），green cap=1.0
        # market_phase_cap_result = min(0.4, 0.3*1.0)=min(0.4,0.3)=0.3
        # final = min(0.4, 0.3, 0.8) = 0.3
        pos = _make_pos(suggested_pct=0.4)
        result = cap_by_market_phase([pos], phase="亢奋")
        assert result[0].suggested_pct == 0.3  # 不超过 max_single_position

    def test_yellow_halves_position(self):
        """黄档 cap=0.5：仓位砍半。"""
        # suggested_pct=0.2，yellow cap=0.5
        # market_phase_cap_result = min(0.2, 0.3*0.5)=min(0.2,0.15)=0.15
        # final = min(0.2, 0.15, 0.8) = 0.15
        pos = _make_pos(suggested_pct=0.2)
        result = cap_by_market_phase([pos], phase="普通")
        assert result[0].suggested_pct == 0.15
        assert result[0].market_phase_cap == 0.5

    def test_red_shrinks_to_min(self):
        """红档 cap=0.2：仓位收紧到 max_single*0.2。"""
        # suggested_pct=0.2，red cap=0.2
        # market_phase_cap_result = min(0.2, 0.3*0.2)=min(0.2,0.06)=0.06
        # final = min(0.2, 0.06, 0.8) = 0.06
        pos = _make_pos(suggested_pct=0.2)
        result = cap_by_market_phase([pos], phase="冰点")
        assert result[0].suggested_pct == 0.06
        assert result[0].market_phase_cap == 0.2

    def test_red_period_same_as_cold(self):
        """红期与冰点同档（red cap=0.2）。"""
        pos1 = _make_pos(suggested_pct=0.2)
        pos2 = _make_pos(suggested_pct=0.2)
        r1 = cap_by_market_phase([pos1], phase="冰点")
        r2 = cap_by_market_phase([pos2], phase="红期")
        assert r1[0].suggested_pct == r2[0].suggested_pct == 0.06


class TestCapByMarketPhaseMutualExclusion:
    """R7.3 互斥：同一情绪现象同时触发 weather + market_phase 熔断取 min 不冲突。"""

    def test_weather_and_market_phase_both_triggered(self):
        """weather_cap 后 suggested_pct=0.1（极端反弹砍半），market_phase=红期 cap=0.2。
        market_phase_cap_result = min(0.1, 0.3*0.2)=min(0.1,0.06)=0.06
        final = min(0.1, 0.06, 0.8) = 0.06（取最严）
        """
        pos = _make_pos(suggested_pct=0.1)  # weather_cap 已砍半
        result = cap_by_market_phase([pos], phase="红期")
        assert result[0].suggested_pct == 0.06  # 取最严

    def test_weather_more_severe_than_market_phase(self):
        """weather 更严（0.05）+ market_phase 黄档（0.15）→ 取 weather 0.05。
        market_phase_cap_result = min(0.05, 0.3*0.5)=min(0.05,0.15)=0.05
        final = min(0.05, 0.05, 0.8) = 0.05
        """
        pos = _make_pos(suggested_pct=0.05)
        result = cap_by_market_phase([pos], phase="普通")
        assert result[0].suggested_pct == 0.05


class TestCapByMarketPhaseBatch:
    """批量处理 + 原地修改 + max_total_position 硬上限。"""

    def test_batch_processing(self):
        """批量处理多个 position。"""
        positions = [
            _make_pos(code="600000", suggested_pct=0.2),
            _make_pos(code="600001", suggested_pct=0.15),
            _make_pos(code="600002", suggested_pct=0.1),
        ]
        result = cap_by_market_phase(positions, phase="普通")
        assert len(result) == 3
        # yellow cap=0.5：每个 suggested_pct vs max_single*0.5=0.15 取 min
        assert result[0].suggested_pct == 0.15  # min(0.2, 0.15)=0.15
        assert result[1].suggested_pct == 0.15  # min(0.15, 0.15)=0.15
        assert result[2].suggested_pct == 0.1   # min(0.1, 0.15)=0.1
        # 所有 position 标记仓位闸信息
        for p in result:
            assert p.market_phase == "普通"
            assert p.market_phase_cap == 0.5

    def test_max_total_position_hard_cap(self):
        """max_total_position=0.8 硬上限：suggested_pct 超 0.8 时 cap 在 0.8。
        注：单测场景极端，实际 advise_batch 输出不会超 0.3。
        """
        pos = _make_pos(suggested_pct=1.0)  # 极端值测硬上限
        result = cap_by_market_phase([pos], phase="活跃", max_total_position=0.8)
        # green cap=1.0：market_phase_cap_result=min(1.0, 0.3*1.0)=0.3
        # final=min(1.0, 0.3, 0.8)=0.3
        assert result[0].suggested_pct == 0.3

    def test_in_place_modification(self):
        """原地修改 + 返回同一列表。"""
        pos = _make_pos(suggested_pct=0.2)
        result = cap_by_market_phase([pos], phase="普通")
        assert result[0] is pos  # 同一对象
        assert pos.suggested_pct == 0.15  # 原地修改生效


class TestCapByMarketPhaseEmpty:
    """空列表处理。"""

    def test_empty_list(self):
        """空列表不报错。"""
        result = cap_by_market_phase([], phase="普通")
        assert result == []
