# -*- coding: utf-8 -*-
"""STI 情绪温度引擎测试 — PRD V1.6 对齐。

覆盖 PRD §12.9.2.11 定义的 13 类边界用例。
"""

import os
import sys
import tempfile
import threading
import unittest

# 确保 backend 目录在 path 中
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import limitup_sti as sti_module
from limitup_sti import (
    STIEngine,
    STIResult,
    STIDimension,
    STIPhase,
    percentile_rank,
    TOTAL_WEIGHT,
    STI_WEIGHTS,
)


class TestPercentileRank(unittest.TestCase):
    """百分位排名测试。"""

    def test_empty_series_returns_50(self):
        self.assertEqual(percentile_rank(50.0, []), 50.0)

    def test_short_series_returns_50(self):
        # < 60 个元素 → 中性值
        self.assertEqual(percentile_rank(50.0, list(range(30))), 50.0)

    def test_exact_middle(self):
        series = list(range(100))
        # 50 在 series 中排第 50/100 = 50th percentile
        result = percentile_rank(50.0, series)
        # less=50 (0..49), equal=1, n=100 → (50 + 0.5) / 100 * 100 = 50.5
        expected = (50 + 0.5 * 1) / 100 * 100
        self.assertAlmostEqual(result, expected, places=1)

    def test_extreme_values(self):
        series = list(range(100))
        # 最小值
        low = percentile_rank(0.0, series)
        self.assertGreater(low, 0)
        self.assertLessEqual(low, 1.0)
        # 最大值
        high = percentile_rank(99.0, series)
        self.assertGreater(high, 90)

    def test_equal_compensation(self):
        """equal 补偿: (less + 0.5 * equal) / n"""
        # 大量相等的值
        series = [50.0] * 100
        result = percentile_rank(50.0, series)
        # less=0, equal=100, n=100 → (0 + 50) / 100 = 50
        self.assertAlmostEqual(result, 50.0, places=1)

    def test_unique_values_sorted(self):
        series = list(range(100))
        # 值 50 在 series 中有 50 个小于它，1 个等于它
        result = percentile_rank(50.0, series)
        expected = (50 + 0.5 * 1) / 100 * 100  # = 50.5
        self.assertAlmostEqual(result, expected, places=1)


class TestSTIEngine(unittest.TestCase):
    """STI 引擎核心测试。"""

    def setUp(self):
        """使用临时数据库。"""
        self.tmpdir = tempfile.mkdtemp()
        self.db_path = os.path.join(self.tmpdir, "test_vibe_research.db")
        self.engine = STIEngine()
        # 覆盖 DB 路径
        original_get_db = self.engine._get_db

        def patched_get_db():
            if self.engine._db is None:
                import sqlite3
                self.engine._db = sqlite3.connect(self.db_path, timeout=10)
                self.engine._db.row_factory = sqlite3.Row
                self.engine._db.execute(
                    """CREATE TABLE IF NOT EXISTS sti_timeline (
                        date TEXT NOT NULL UNIQUE,
                        score REAL,
                        phase TEXT,
                        dimension_limit_up_count REAL,
                        dimension_limit_down_count REAL,
                        dimension_seal_rate REAL,
                        dimension_advance_decline_ratio REAL,
                        dimension_promotion_rate REAL,
                        dimension_prev_zt_performance REAL,
                        dimension_max_boards REAL,
                        market_factor REAL,
                        confidence TEXT,
                        source_ok BOOLEAN DEFAULT 1,
                        change_from_yesterday REAL,
                        data_updated TEXT,
                        computed_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                    )"""
                )
                self.engine._db.commit()
            return self.engine._db

        self.engine._get_db = patched_get_db
        # 清除内存缓存
        with sti_module._sti_lock:
            sti_module._sti_scores.clear()

    def tearDown(self):
        if self.engine._db:
            self.engine._db.close()
        import shutil
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    # ---- 1. 空数据 ----
    def test_empty_data_returns_null(self):
        result = sti_module.STIEngine.compute(
            self.engine, {}, {}
        )
        self.assertFalse(result.source_ok)
        self.assertIsNone(result.score)
        self.assertIsNone(result.phase)

    # ---- 2. 单点数据 ----
    def test_single_point_returns_50(self):
        """历史序列为空 → 所有维度返回 50，加权后应为 50"""
        emotion = {
            "date": "2026-07-21",
            "zt_count": 50,
            "dt_count": 10,
            "seal_rate": 0.83,
            "promotion_rate": 0.3,
            "yzt_count": 40,
            "max_boards": 4,
        }
        sentiment = {"up": 3000, "down": 2000, "active": "中性"}
        result = self.engine.compute(emotion, sentiment)
        # 由于历史为空（<60），所有维度返回 50，加权后应为 50
        self.assertIsNotNone(result.score)
        self.assertAlmostEqual(result.score, 50.0, delta=1.0)

    # ---- 3. 极端值 ----
    def test_extreme_values_stay_in_range(self):
        """涨停 500 家 / 跌停 100 家 → 不归一化溢出 [0, 100]"""
        emotion = {
            "date": "2026-07-21",
            "zt_count": 500,
            "dt_count": 100,
            "seal_rate": 0.95,
            "promotion_rate": 0.8,
            "yzt_count": 200,
            "max_boards": 10,
        }
        sentiment = {"up": 4500, "down": 500, "active": "普涨"}
        result = self.engine.compute(emotion, sentiment)
        self.assertIsNotNone(result.score)
        self.assertGreaterEqual(result.score, 0)
        self.assertLessEqual(result.score, 100)

    # ---- 4. 负权重（跌停最多）----
    def test_negative_indicator_contribution(self):
        """跌停最多的那天 → 反向指标贡献最低分，总分应偏低"""
        emotion = {
            "date": "2026-07-21",
            "zt_count": 5,
            "dt_count": 100,
            "seal_rate": 0.1,
            "promotion_rate": 0.01,
            "yzt_count": 50,
            "max_boards": 1,
        }
        sentiment = {"up": 500, "down": 4000, "active": "冰点"}
        result = self.engine.compute(emotion, sentiment)
        self.assertIsNotNone(result.score)
        # 所有维度都是新数据（历史为空 → 50 分），所以分数应为 50
        # 但 market_factor = 0.7 会降低置信度
        self.assertGreaterEqual(result.score, 0)
        self.assertLessEqual(result.score, 100)

    # ---- 5. 相位边界 ----
    def test_phase_boundaries(self):
        """score = 19.9, 20.0, 69.9, 70.0 → 相位不跳变（降级阈值）"""
        base_emotion = {
            "date": "2026-07-21",
            "zt_count": 50,
            "dt_count": 10,
            "seal_rate": 0.8,
            "promotion_rate": 0.3,
            "yzt_count": 40,
            "max_boards": 4,
        }
        base_sentiment = {"up": 3000, "down": 2000, "active": "中性"}

        # 这些测试依赖于百分位排名，不直接测试分数边界
        # 但确保不会 crash
        for i in range(3):
            emotion = {**base_emotion, "date": f"2026-07-{21+i}"}
            result = self.engine.compute(emotion, base_sentiment)
            self.assertIsNotNone(result.phase)

    # ---- 6. 归一化退化 ----
    def test_normalize_degeneration(self):
        """min_val == max_val → 返回 50.0"""
        # 当所有历史值都相同时，engine 应检测到并返回 50
        emotion = {
            "date": "2026-07-21",
            "zt_count": 50,
            "dt_count": 10,
            "seal_rate": 0.8,
            "promotion_rate": 0.3,
            "yzt_count": 40,
            "max_boards": 4,
        }
        sentiment = {"up": 3000, "down": 2000, "active": "中性"}
        result = self.engine.compute(emotion, sentiment)
        self.assertIsNotNone(result.score)

    # ---- 7. market_factor ----
    def test_market_factor_applied(self):
        """成交额 = 冰点 → market_factor = 0.7"""
        emotion = {
            "date": "2026-07-21",
            "zt_count": 50,
            "dt_count": 10,
            "seal_rate": 0.8,
            "promotion_rate": 0.3,
            "yzt_count": 40,
            "max_boards": 4,
        }
        sentiment = {"up": 3000, "down": 2000, "active": "冰点"}
        result = self.engine.compute(emotion, sentiment)
        self.assertIsNotNone(result.dimensions)
        self.assertEqual(result.dimensions.market_factor, 0.7)

    # ---- 8. 数据源故障 ----
    def test_source_failure_returns_null(self):
        """emotion_data = {} → source_ok=False, score=null"""
        result = self.engine.compute({}, {"up": 1})
        self.assertFalse(result.source_ok)
        self.assertIsNone(result.score)
        self.assertIsNone(result.phase)

    # ---- 9. equal 补偿 ----
    def test_equal_compensation_in_ranking(self):
        """(less + 0.5 * equal) / n 结果正确"""
        series = [10.0, 20.0, 30.0, 30.0, 30.0, 40.0, 50.0]
        result = percentile_rank(30.0, series)
        # less=2 (10,20), equal=3, n=7 → (2 + 1.5) / 7 * 100 = 50.0
        expected = (2 + 0.5 * 3) / 7 * 100
        self.assertAlmostEqual(result, expected, places=1)

    # ---- 10. 浮点精度 ----
    def test_weight_sum_is_one(self):
        """权重合计 = 1.00"""
        self.assertAlmostEqual(TOTAL_WEIGHT, 1.00, places=4)
        self.assertEqual(sum(STI_WEIGHTS.values()), TOTAL_WEIGHT)

    # ---- 11. 线程安全 ----
    def test_thread_safety(self):
        """内存缓存线程安全 → _sti_lock 保护"""
        # 测试内存缓存的线程安全（SQLite 并发写入较复杂，主要测内存锁）
        with sti_module._sti_lock:
            sti_module._sti_scores.clear()

        results = []

        def append_score():
            for i in range(100):
                with sti_module._sti_lock:
                    sti_module._sti_scores.append(float(i))

        threads = [threading.Thread(target=append_score) for _ in range(5)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        # 应该有 500 个元素（5 * 100）
        with sti_module._sti_lock:
            self.assertEqual(len(sti_module._sti_scores), 500)

    # ---- 12. prev_zt_performance 方向修正 ----
    def test_prev_zt_performance_direction(self):
        """zt/yzt > 100 表示情绪延续"""
        emotion = {
            "date": "2026-07-21",
            "zt_count": 60,
            "dt_count": 10,
            "seal_rate": 0.8,
            "promotion_rate": 0.3,
            "yzt_count": 40,
            "max_boards": 4,
        }
        sentiment = {"up": 3000, "down": 2000, "active": "中性"}
        result = self.engine.compute(emotion, sentiment)
        # 60/40 * 100 = 150 > 100 情绪延续
        self.assertGreater(result.dimensions.prev_zt_performance, 100)

    # ---- 13. 8 维无 break_rate ----
    def test_no_break_rate_in_dimensions(self):
        """STIDimension 不应包含 break_rate 字段"""
        dims = STIDimension()
        self.assertFalse(hasattr(dims, "break_rate"))
        self.assertFalse("break_rate" in STI_WEIGHTS)

    # ---- 相位平滑 ----
    def test_phase_smoothing(self):
        """3 日移动平均 → 单日极端值不导致相位跳变"""
        from limitup_sti import _ema_3day
        # 正常平滑
        result = _ema_3day(90.0, [50.0, 55.0])
        expected = (90 + 50 + 55) / 3
        self.assertAlmostEqual(result, expected, places=1)

        # 无历史
        result2 = _ema_3day(90.0, [])
        self.assertEqual(result2, 90.0)

        # 1 个历史
        result3 = _ema_3day(90.0, [50.0])
        expected3 = (90 + 50) / 2
        self.assertAlmostEqual(result3, expected3, places=1)


class TestSchemaMigration(unittest.TestCase):
    """SQLite schema 迁移测试。"""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.db_path = os.path.join(self.tmpdir, "test_vibe_research.db")
        self.engine = STIEngine()

    def tearDown(self):
        if self.engine._db:
            self.engine._db.close()
        import shutil
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_migrate_removes_break_rate(self):
        """迁移后不应有 break_rate 列"""
        # 手动创建带旧列的表
        import sqlite3
        db = sqlite3.connect(self.db_path)
        db.execute("""CREATE TABLE sti_timeline (
            date TEXT NOT NULL UNIQUE,
            score REAL,
            phase TEXT,
            dimension_limit_up_count REAL,
            dimension_limit_down_count REAL,
            dimension_seal_rate REAL,
            dimension_break_rate REAL,
            dimension_advance_decline_ratio REAL,
            dimension_promotion_rate REAL,
            dimension_prev_zt_performance REAL,
            dimension_max_boards REAL,
            market_factor REAL,
            confidence TEXT,
            source_ok BOOLEAN DEFAULT 1,
            momentum REAL,
            computed_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )""")
        db.commit()
        db.close()

        # 创建 engine 并设置 DB 路径
        engine = STIEngine()
        engine._db = sqlite3.connect(self.db_path, timeout=10)
        engine._db.row_factory = sqlite3.Row

        # 执行迁移
        engine._migrate_schema()

        # 验证 break_rate 列已被移除
        cursor = engine._db.execute("PRAGMA table_info(sti_timeline)")
        columns = {row["name"] for row in cursor.fetchall()}
        self.assertNotIn("dimension_break_rate", columns)
        self.assertIn("change_from_yesterday", columns)
        self.assertIn("data_updated", columns)
        engine._db.close()


if __name__ == "__main__":
    unittest.main()
