# -*- coding: utf-8 -*-
"""S094 T18：zt_real 端到端读回测试。

验证 R16（zt_real 持久化 + 显示层修）的读回半边 + R17（refresh 重算 market_emotion）：
- _market_emotion_from_ctx 从 sti_timeline T-1 行读 zt_real（raw 计数，不 /100）。
- 历史行 zt_real NULL → out["zt_real"] None（诚实缺失，不臆造 0）。
- 无 STI 行 → default shape zt_real=None。
- _fetch_market_emotion fallback（ctx=None）从 emo 透传 zt_real。

conftest 把 VR_DATA_DIR 指到临时目录 → STI_TIMELINE_DB_PATH 指向新空 DB；
limitup_sti/__init__.py 的自动迁移在首次 import 时建表（含 T18 的 zt_real ALTER）。
"""
from __future__ import annotations

import os
import sys
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import sqlite3
from config import STI_TIMELINE_DB_PATH


def _seed_sti_row(t1_date: str, zt_real=None) -> None:
    """在 STI_TIMELINE_DB 插一行 T-1 数据（可选 zt_real）。

    import limitup_sti 触发 __init__ 自动迁移建 sti_timeline 表（含 T18 zt_real 列）。
    """
    import limitup_sti  # noqa: F401 — 触发 __init__ 自动迁移建表
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
                change_from_yesterday, data_updated, raw_break_rate, zt_real
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (t1_date, 68.83, "分歧", 92.0, 0.0, 87.6, 2.0, 27.6, 100.0, 5.0,
             1.0, "high", 1, 2.5, t1_date, 0.12, zt_real),
        )
        db.commit()
    finally:
        db.close()


def _clear_sti() -> None:
    import limitup_sti  # noqa: F401 — 确保表已建
    db = sqlite3.connect(STI_TIMELINE_DB_PATH)
    try:
        db.execute("DELETE FROM sti_timeline")
        db.commit()
    finally:
        db.close()


class TestZtRealReadback(unittest.TestCase):
    """T18 step 6 + R17：_market_emotion_from_ctx 从 STI DB 读 zt_real。"""

    def setUp(self):
        _clear_sti()

    def test_reads_zt_real_from_sti_row_raw_not_divided(self):
        from sentiment_context import build_context
        from routers.workflow import _market_emotion_from_ctx

        _seed_sti_row("2026-08-12", zt_real=42.0)
        ctx = build_context("2026-08-13")
        self.assertEqual(ctx.source_date, "2026-08-12")
        self.assertEqual(ctx.data_status, "ok")

        out = _market_emotion_from_ctx("2026-08-13", ctx)
        # zt_real 从 STI 行读回；raw 计数不 /100（42.0 非 0.42——区别于 seal_rate/promotion_rate 的 /100）
        self.assertEqual(out["zt_real"], 42.0)

    def test_zt_real_null_when_row_has_none(self):
        from sentiment_context import build_context
        from routers.workflow import _market_emotion_from_ctx

        _seed_sti_row("2026-08-12", zt_real=None)  # 历史行 zt_real NULL
        ctx = build_context("2026-08-13")
        out = _market_emotion_from_ctx("2026-08-13", ctx)
        # 历史行 NULL → None（诚实缺失，不臆造 0；akshare legu 无法查历史）
        self.assertIsNone(out["zt_real"])

    def test_zt_real_none_in_default_shape_when_no_row(self):
        from sentiment_context import build_context
        from routers.workflow import _market_emotion_from_ctx

        ctx = build_context("2099-12-31")  # 表空 → data_status=missing
        self.assertEqual(ctx.data_status, "missing")
        out = _market_emotion_from_ctx("2099-12-31", ctx)
        # 无行 → 早返 default shape（T18 加的 zt_real=None）
        self.assertIsNone(out["zt_real"])
        self.assertIn("ladder_note", out)


class TestZtRealFallbackPassthrough(unittest.TestCase):
    """T18 step 7：_fetch_market_emotion fallback（ctx=None）从 emo 透传 zt_real。"""

    def test_fallback_passes_zt_real(self):
        from routers import workflow as wf

        emo = {
            "seal_rate": 0.6, "break_rate": 0.2, "promotion_rate": 0.3,
            "ladder": [], "zt_count": 30, "dt_count": 2, "zt_real": 55,
        }
        _sti = mock.MagicMock(source_ok=False, score=None, phase=None)
        with mock.patch("candidate_funnel.sources.board_ladder.get_market_emotion_raw", return_value=emo), \
             mock.patch("limitup_sti.service.get_sti_engine",
                        return_value=mock.MagicMock(compute=lambda e, s: _sti)), \
             mock.patch("market._sentiment", return_value={}):
            out = wf._fetch_market_emotion("2026-08-10")
        self.assertEqual(out["zt_real"], 55)

    def test_fallback_zt_real_none_when_emo_lacks_it(self):
        from routers import workflow as wf

        emo = {"seal_rate": 0.6, "ladder": [], "zt_count": 30, "dt_count": 2}
        _sti = mock.MagicMock(source_ok=False, score=None, phase=None)
        with mock.patch("candidate_funnel.sources.board_ladder.get_market_emotion_raw", return_value=emo), \
             mock.patch("limitup_sti.service.get_sti_engine",
                        return_value=mock.MagicMock(compute=lambda e, s: _sti)), \
             mock.patch("market._sentiment", return_value={}):
            out = wf._fetch_market_emotion("2026-08-10")
        self.assertIsNone(out["zt_real"])


if __name__ == "__main__":
    unittest.main()
