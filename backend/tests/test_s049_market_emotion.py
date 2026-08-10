# -*- coding: utf-8 -*-
"""S049 B/C/D：_fetch_market_emotion 重写 + diagnose as_of + 快照诊断卡 + 漏斗全参数。

子项 B：_fetch_market_emotion 返 STI+三率+ladder+涨跌停（mock market._emotion + STI engine）；
子项 C：diagnose as_of=数据源最早日期；
子项 D：状态机 WATCHING→CANDIDATE + funnel passed 全参数 + run_funnel 缓存。
"""
from __future__ import annotations

import os
import sys
import unittest
from datetime import datetime
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


# ── B: _fetch_market_emotion 三分支 ───────────────────────────────────────


class TestFetchMarketEmotion(unittest.TestCase):
    """S049 R-B4：_fetch_market_emotion 返 STI+三率+ladder+涨跌停，失败降级。"""

    def test_emotion_present_returns_full_shape(self):
        from routers import workflow as wf

        emo = {
            "seal_rate": 0.6, "break_rate": 0.2, "promotion_rate": 0.3,
            "ladder": [{"boards": 2, "count": 5}], "zt_count": 30, "dt_count": 2,
        }

        class _Sti:
            source_ok = True
            score = 55.0

            class _Phase:
                value = "启动"

            phase = _Phase()

        with mock.patch("candidate_funnel.sources.board_ladder.get_market_emotion_raw", return_value=emo), \
             mock.patch("limitup_sti.service.get_sti_engine", return_value=mock.MagicMock(compute=lambda e, s: _Sti())), \
             mock.patch("market._sentiment", return_value={}):
            out = wf._fetch_market_emotion("2026-08-10")
        self.assertEqual(out["seal_rate"], 0.6)
        self.assertEqual(out["break_rate"], 0.2)
        self.assertEqual(out["promotion_rate"], 0.3)
        self.assertEqual(out["ladder"], [{"boards": 2, "count": 5}])
        self.assertEqual(out["zt_count"], 30)
        self.assertEqual(out["dt_count"], 2)
        self.assertEqual(out["sti_score"], 55.0)
        self.assertEqual(out["sti_phase"], "启动")

    def test_emotion_empty_returns_none_fields(self):
        from routers import workflow as wf

        with mock.patch("candidate_funnel.sources.board_ladder.get_market_emotion_raw", return_value={}):
            out = wf._fetch_market_emotion("2026-08-10")
        self.assertIsNone(out["seal_rate"])
        self.assertIsNone(out["sti_score"])
        self.assertEqual(out["ladder"], [])

    def test_sti_failure_degrades_to_none(self):
        from routers import workflow as wf

        emo = {"seal_rate": 0.5, "ladder": [], "zt_count": 10, "dt_count": 1}

        with mock.patch("candidate_funnel.sources.board_ladder.get_market_emotion_raw", return_value=emo), \
             mock.patch("limitup_sti.service.get_sti_engine", side_effect=RuntimeError("db locked")):
            out = wf._fetch_market_emotion("2026-08-10")
        # STI 失败不影响三率/ladder
        self.assertEqual(out["seal_rate"], 0.5)
        self.assertIsNone(out["sti_score"])
        self.assertIsNone(out["sti_phase"])


if __name__ == "__main__":
    unittest.main()
