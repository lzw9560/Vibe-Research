# -*- coding: utf-8 -*-
"""S094 audit: save_result sti_timeline INSERT 测试（T18 zt_real/raw_break_rate 列写入）。

覆盖 gap：save_result 是 sti_timeline 唯一生产写路径，T18 加 zt_real 列后零测试覆盖；
T18 readback 测试只验 _market_emotion_from_ctx 读，没验 save_result 写（zt_real/raw_break_rate 列入 DB）。
"""
from __future__ import annotations

import os
import sqlite3
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from limitup_sti.models import STIResult, STIDimension, STIPhase
from limitup_sti.data import save_result
from config import STI_TIMELINE_DB_PATH


class TestSaveResult(unittest.TestCase):
    """save_result 写 sti_timeline（zt_real/raw_break_rate 列）。"""

    def setUp(self):
        import limitup_sti  # noqa: F401 — 触发 __init__ 迁移建表（含 zt_real/raw_break_rate ALTER，独立 try）
        db = sqlite3.connect(STI_TIMELINE_DB_PATH)
        db.execute("DELETE FROM sti_timeline")
        db.commit()
        db.close()

    def _make_result(self, zt_real=None, raw_break_rate=None):
        dims = STIDimension(
            limit_up_count=90, limit_down_count=2, seal_rate=0.85,
            advance_decline_ratio=2.0, promotion_rate=0.27,
            prev_zt_performance=100.0, max_boards=5, market_factor=1.0,
        )
        return STIResult(
            date="2026-08-23", score=70.0, phase=STIPhase.START,
            dimensions=dims, source_ok=True, confidence="high",
            raw_break_rate=raw_break_rate, zt_real=zt_real,
        )

    def test_save_with_zt_real_and_raw_break_rate(self):
        r = self._make_result(zt_real=42.0, raw_break_rate=0.12)
        save_result(r)
        db = sqlite3.connect(STI_TIMELINE_DB_PATH)
        row = db.execute(
            "SELECT zt_real, raw_break_rate, score, phase FROM sti_timeline WHERE date=?",
            ("2026-08-23",),
        ).fetchone()
        db.close()
        self.assertIsNotNone(row)
        self.assertEqual(row[0], 42.0)   # zt_real
        self.assertEqual(row[1], 0.12)    # raw_break_rate
        self.assertEqual(row[2], 70.0)   # score
        self.assertEqual(row[3], "启动")  # phase（STIPhase.START）

    def test_save_zt_real_none(self):
        """zt_real/raw_break_rate None → DB NULL（诚实缺失，不臆造 0）。"""
        r = self._make_result(zt_real=None, raw_break_rate=None)
        save_result(r)
        db = sqlite3.connect(STI_TIMELINE_DB_PATH)
        row = db.execute(
            "SELECT zt_real, raw_break_rate FROM sti_timeline WHERE date=?",
            ("2026-08-23",),
        ).fetchone()
        db.close()
        self.assertIsNotNone(row)
        self.assertIsNone(row[0])  # zt_real NULL
        self.assertIsNone(row[1])  # raw_break_rate NULL

    def test_save_or_replace_upserts(self):
        """同 date 二次写 → ON CONFLICT 覆写（非空新值覆盖旧值，不重复行）。"""
        save_result(self._make_result(zt_real=10.0))
        save_result(self._make_result(zt_real=20.0))  # 同 date 覆写
        db = sqlite3.connect(STI_TIMELINE_DB_PATH)
        rows = db.execute(
            "SELECT zt_real FROM sti_timeline WHERE date=?", ("2026-08-23",)
        ).fetchall()
        db.close()
        self.assertEqual(len(rows), 1)   # 一行（OR REPLACE）
        self.assertEqual(rows[0][0], 20.0)  # 覆写后的值

    def test_save_zt_real_none_does_not_overwrite(self):
        """重算历史日 zt_real=None 不覆盖当天真值（COALESCE 保留旧值）。

        场景：15:35 写 zt_real=42（当天最新日有值），次日 limitup_precompute
        back_days 回溯重算昨日（已非最新日→_sentiment 返 {}→zt_real=None），
        COALESCE 保留 42 不被 None 覆盖。
        """
        save_result(self._make_result(zt_real=42.0))
        save_result(self._make_result(zt_real=None))  # 重算 None 不覆盖
        db = sqlite3.connect(STI_TIMELINE_DB_PATH)
        row = db.execute(
            "SELECT zt_real FROM sti_timeline WHERE date=?", ("2026-08-23",)
        ).fetchone()
        db.close()
        self.assertEqual(row[0], 42.0)  # 旧值保留

    def test_save_raw_break_rate_none_does_not_overwrite(self):
        """raw_break_rate=None 重算不覆盖旧值（同 COALESCE 范式）。"""
        save_result(self._make_result(zt_real=10.0, raw_break_rate=0.15))
        save_result(self._make_result(zt_real=None, raw_break_rate=None))
        db = sqlite3.connect(STI_TIMELINE_DB_PATH)
        row = db.execute(
            "SELECT raw_break_rate, zt_real FROM sti_timeline WHERE date=?",
            ("2026-08-23",),
        ).fetchone()
        db.close()
        self.assertEqual(row[0], 0.15)  # raw_break_rate 旧值保留
        self.assertEqual(row[1], 10.0)  # zt_real 旧值保留（None 不覆盖）


if __name__ == "__main__":
    unittest.main()
