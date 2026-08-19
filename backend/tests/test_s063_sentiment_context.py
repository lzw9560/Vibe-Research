# -*- coding: utf-8 -*-
"""S063 T30：sentiment_context + intraday_scoring + position_advisor 单元测试。

AC1：build_context(T) 返回 source_date=T-1 的完整 context
AC4：PositionAdvisor 暴风雨→0（禁止开仓），极端反弹→50%
AC5：盘中评分模型 4 维度固定阈值 + 趋势 + 色带
"""
from __future__ import annotations

import os
import sys
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import sqlite3
from config import STI_TIMELINE_DB_PATH


def _seed_sti_timeline_t1(t1_date: str = "2026-08-12", score: float = 68.83) -> None:
    """在 STI_TIMELINE_DB 插一行 T-1 数据（build_context 读它）。

    conftest 把 VR_DATA_DIR 指到临时目录 → STI_TIMELINE_DB_PATH 指向新空 DB；
    limitup_sti/__init__.py 的自动迁移在首次 import 时建表——这里先 import 触发。
    """
    import limitup_sti  # noqa: F401 — 触发 __init__ 自动迁移建 sti_timeline 表
    db = sqlite3.connect(STI_TIMELINE_DB_PATH)
    try:
        db.execute("DELETE FROM sti_timeline WHERE date = ?", (t1_date,))
        db.execute(
            """INSERT OR REPLACE INTO sti_timeline (
                date, score, phase,
                dimension_limit_up_count, dimension_limit_down_count,
                dimension_seal_rate, dimension_advance_decline_ratio,
                dimension_promotion_rate, dimension_prev_zt_performance,
                dimension_max_boards, market_factor, confidence, source_ok,
                change_from_yesterday, data_updated
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (t1_date, score, "分歧", 92.0, 0.0, 87.6, 2.0, 27.6, 100.0, 5.0, 1.0, "high", 1, 2.5, t1_date),
        )
        db.commit()
    finally:
        db.close()


class TestSentimentContextBuild(unittest.TestCase):
    """AC1：build_context 构造正确。"""

    def setUp(self):
        _seed_sti_timeline_t1()

    def test_build_context_returns_t1_data(self):
        from sentiment_context import build_context

        ctx = build_context("2026-08-13")
        self.assertEqual(ctx.decision_date, "2026-08-13")
        self.assertEqual(ctx.source_date, "2026-08-12")
        self.assertIsNotNone(ctx.sti_score)
        self.assertEqual(ctx.sti_phase, "分歧")
        self.assertIn(ctx.weather_state, ["晴天", "阴天", "暴风雨", "极端反弹", "未知"])
        self.assertIsInstance(ctx.allowed_styles, list)
        self.assertIsInstance(ctx.forbidden_styles, list)
        self.assertEqual(ctx.data_status, "ok")

    def test_build_context_missing_t1_returns_empty(self):
        from sentiment_context import build_context

        # 远未来日期，T-1 无数据（setUp 插的 2026-08-12 < 2099-12-31，但
        # build_context 查 date < decision_date → 2026-08-12 仍命中；用更大
        # 的日期且清掉所有 sti_timeline 数据测真正缺失路径）
        import sqlite3
        from config import STI_TIMELINE_DB_PATH
        db = sqlite3.connect(STI_TIMELINE_DB_PATH)
        try:
            db.execute("DELETE FROM sti_timeline")
            db.commit()
        finally:
            db.close()
        ctx = build_context("2099-12-31")
        self.assertIsNone(ctx.source_date)
        self.assertIsNone(ctx.sti_score)
        self.assertEqual(ctx.data_status, "missing")

    def test_to_dict_serializable(self):
        from sentiment_context import build_context

        ctx = build_context("2026-08-13")
        d = ctx.to_dict()
        self.assertIn("source_date", d)
        self.assertIn("weather_state", d)
        self.assertIn("allowed_styles", d)
        self.assertEqual(d["decision_date"], "2026-08-13")


class TestIntradayScoring(unittest.TestCase):
    """AC5：4 维度固定阈值评分 + 趋势 + 色带。"""

    def test_score_strong_market(self):
        from routers.intraday_sentiment import _compute_score
        score = _compute_score(zt_count=90, seal_rate=0.85, break_rate=0.1, ad_ratio=2.5)
        # 强市：涨停 100 + 封板 100 + 炸板 100 + 涨跌 100
        self.assertGreater(score, 90)

    def test_score_weak_market(self):
        from routers.intraday_sentiment import _compute_score
        score = _compute_score(zt_count=20, seal_rate=0.4, break_rate=0.35, ad_ratio=0.5)
        # 弱市：涨停 20 + 封板 20 + 炸板 20 + 涨跌 20
        self.assertLess(score, 35)

    def test_trend_up(self):
        from routers.intraday_sentiment import _compute_trend
        self.assertEqual(_compute_trend(70, 65), "up")

    def test_trend_flat_within_3(self):
        from routers.intraday_sentiment import _compute_trend
        self.assertEqual(_compute_trend(68, 67), "flat")

    def test_trend_down(self):
        from routers.intraday_sentiment import _compute_trend
        self.assertEqual(_compute_trend(60, 70), "down")

    def test_zone_green_within_5(self):
        from routers.intraday_sentiment import _compute_zone
        self.assertEqual(_compute_zone(70, 68), "green")

    def test_zone_yellow_5_to_15(self):
        from routers.intraday_sentiment import _compute_zone
        self.assertEqual(_compute_zone(75, 65), "yellow")

    def test_zone_red_over_15(self):
        from routers.intraday_sentiment import _compute_zone
        self.assertEqual(_compute_zone(80, 60), "red")

    def test_zone_no_baseline_defaults_yellow(self):
        from routers.intraday_sentiment import _compute_zone
        self.assertEqual(_compute_zone(70, None), "yellow")


class TestPositionAdvisorWeatherState(unittest.TestCase):
    """S086 R4：PositionAdvisor 暴风雨→仓位×0.3 建议（非强制），极端反弹→50%。"""

    def _make_signal(self, confidence: float = 0.8) -> "StrategySignal":
        from limitup_strategy import StrategySignal
        return StrategySignal(
            code="600001",
            name="测试股",
            strategy_name="首板挖掘",
            strategy_code="first_plate",
            confidence=confidence,
            entry_price=10.0,
            stop_loss=9.0,
            take_profit=11.0,
            signal_strength=80,
        )

    def test_storm_soft_caps_30pct(self):
        """S086 R4：暴风雨不再禁止开仓——仓位×0.3 建议（非强制），返回建议而非 None。"""
        from strategies.position_advisor import PositionAdvisor
        advisor = PositionAdvisor()
        sig = self._make_signal()
        result = advisor.advise(sig, weather_state="暴风雨")
        self.assertIsNotNone(result)  # S086 R4：不再 return None 禁止开仓
        # 暴风暴 weather_cap=0.3 → 仓位×0.3 建议（非强制，advice note 在 reasons 里）
        self.assertLessEqual(result.suggested_pct, advisor.max_single_position * 0.3)

    def test_extreme_rebound_caps_50pct(self):
        from strategies.position_advisor import PositionAdvisor
        advisor = PositionAdvisor(max_single_position=0.3)
        sig = self._make_signal(confidence=0.8)  # high → base_unit*2=0.2
        result = advisor.advise(sig, weather_state="极端反弹")
        self.assertIsNotNone(result)
        # 0.2 vs 0.3*0.5=0.15 → min(0.2, 0.15) = 0.15
        self.assertLessEqual(result.suggested_pct, 0.15)

    def test_sunny_normal(self):
        from strategies.position_advisor import PositionAdvisor
        advisor = PositionAdvisor(max_single_position=0.3)
        sig = self._make_signal(confidence=0.8)
        result = advisor.advise(sig, weather_state="晴天")
        self.assertIsNotNone(result)
        # 晴天不限制：high → base_unit*2=0.2
        self.assertEqual(result.suggested_pct, 0.2)

    def test_no_weather_state_behaves_normal(self):
        """未传 weather_state 时行为不变（向后兼容）。"""
        from strategies.position_advisor import PositionAdvisor
        advisor = PositionAdvisor(max_single_position=0.3)
        sig = self._make_signal(confidence=0.8)
        result = advisor.advise(sig)
        self.assertIsNotNone(result)
        self.assertEqual(result.suggested_pct, 0.2)


if __name__ == "__main__":
    unittest.main()
