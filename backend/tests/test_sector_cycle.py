# -*- coding: utf-8 -*-
"""S066 §5 板块周期分析测试。"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

backend_dir = Path(__file__).resolve().parent.parent
if str(backend_dir) not in sys.path:
    sys.path.insert(0, str(backend_dir))

from strategies.sector_cycle import (
    classify_phase,
    sector_breadth,
    sector_strength_rank,
    detect_rotation,
)


class TestClassifyPhase:
    """板块周期阶段分类。"""

    def test_startup_phase(self):
        """启动：avg<=1 且 today>=1。"""
        phase, mod, note = classify_phase(1, 0.5, has_history=True)
        assert phase == "启动"
        assert mod == 1.1

    def test_fermentation_phase(self):
        """发酵：today > avg 且 avg >= 1。"""
        phase, mod, note = classify_phase(4, 1.5, has_history=True)
        assert phase == "发酵"
        assert mod == 1.0

    def test_climax_phase(self):
        """高潮：today >= 5 且 today >= avg。"""
        phase, mod, note = classify_phase(6, 4.0, has_history=True)
        assert phase == "高潮"
        assert mod == 0.9

    def test_receding_phase(self):
        """退潮：today < avg 且 avg >= 3。"""
        phase, mod, note = classify_phase(2, 4.0, has_history=True)
        assert phase == "退潮"
        assert mod == 0.7

    def test_cold_phase(self):
        """冷门：avg==0 且 today<=1。"""
        phase, mod, note = classify_phase(0, 0.0, has_history=True)
        assert phase == "冷门"
        assert mod == 0.8

    def test_no_history(self):
        """无历史数据 → 中性。"""
        phase, mod, note = classify_phase(1, 0, has_history=False)
        assert phase == "无历史"
        assert mod == 1.0

    def test_climax_takes_priority_over_fermentation(self):
        """高潮优先于发酵：today=8, avg=5 → 高潮（>=5 且 >=avg）。"""
        phase, _, _ = classify_phase(8, 5.0, has_history=True)
        assert phase == "高潮"

    def test_startup_takes_priority_over_cold(self):
        """启动优先于冷门：today=1, avg=0.5 → 启动（avg<=1 且 today>=1）。"""
        phase, _, _ = classify_phase(1, 0.5, has_history=True)
        assert phase == "启动"


class TestSectorBreadth:
    """板块广度。"""

    def test_full_breadth(self):
        """全部上涨 → 广度 1.0。"""
        assert sector_breadth(100, 0) == 1.0

    def test_half_breadth(self):
        """半涨半跌 → 广度 0.5。"""
        assert sector_breadth(50, 50) == 0.5

    def test_zero_breadth(self):
        """零上涨 → 广度 0.0。"""
        assert sector_breadth(0, 100) == 0.0

    def test_empty_sector(self):
        """无股票 → 广度 0.0。"""
        assert sector_breadth(0, 0) == 0.0


class TestSectorStrengthRank:
    """板块强度排名。"""

    def test_ranking_by_strength(self):
        """按强度降序排序 + 修饰系数。"""
        sectors = [
            {"industry": "A", "zt_count_today": 5, "zt_momentum": 2, "fund_flow": 1},
            {"industry": "B", "zt_count_today": 3, "zt_momentum": 1, "fund_flow": -1},
            {"industry": "C", "zt_count_today": 1, "zt_momentum": 0, "fund_flow": 0},
        ]
        ranked = sector_strength_rank("2026-08-14", sectors)
        assert len(ranked) <= 10
        assert ranked[0]["industry"] == "A"  # 最强排第一
        assert ranked[0]["modifier"] == 1.05  # TOP-3

    def test_top3_get_bonus(self):
        """TOP-3 修饰 ×1.05。"""
        sectors = [{"industry": f"S{i}", "zt_count_today": 10 - i, "zt_momentum": 0, "fund_flow": 0} for i in range(5)]
        ranked = sector_strength_rank("2026-08-14", sectors)
        assert ranked[0]["modifier"] == 1.05
        assert ranked[2]["modifier"] == 1.05
        assert ranked[3]["modifier"] == 1.0  # 第 4 名无 bonus


class TestDetectRotation:
    """跨板块轮动检测。"""

    def test_rotation_up(self):
        """上升 >= 5 位 → 启动候选。"""
        # 板块 A 从第 10 名升到第 3 名（change=7）
        sectors_prev = [{"industry": f"S{i}", "zt_count_today": 10 - i} for i in range(11)]
        # A 在 prev 排第 10，在 curr 排第 3
        sectors_curr = [{"industry": "A", "zt_count_today": 8}] + [{"industry": f"S{i}", "zt_count_today": 10 - i} for i in range(1, 11) if f"S{i}" != "A"]
        rotations = detect_rotation("2026-08-13", "2026-08-14", sectors_prev, sectors_curr)
        a_rotation = [r for r in rotations if r["industry"] == "A"]
        if a_rotation:
            assert a_rotation[0]["signal"] in ("启动候选", "退潮")

    def test_no_rotation_small_change(self):
        """变化 < 5 位 → 无轮动信号。"""
        sectors = [{"industry": f"S{i}", "zt_count_today": 10 - i} for i in range(6)]
        rotations = detect_rotation("2026-08-13", "2026-08-14", sectors, sectors)
        assert len(rotations) == 0  # 无变化
