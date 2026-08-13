# -*- coding: utf-8 -*-
"""S064 盯盘教练单测：时刻表边界 + attention_mode 读写 + 条件清单 + 教练状态。"""
from __future__ import annotations

import json
import os
import sys
import unittest
from datetime import datetime
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import intraday_coach as coach
from intraday_coach import (
    TIMETABLE,
    TimetableSlot,
    get_current_slot,
    get_attention_mode,
    set_attention_mode,
    build_condition_checklist,
    build_coach_state,
    MODE_RULES,
)


def _dt(h: int, m: int, weekday: int = 3) -> datetime:
    """构造 2026-08-13（周四, weekday=3）的 datetime。"""
    d = datetime(2026, 8, 13, h, m)
    # datetime(2026,8,13) 是周四——weekday=3
    assert d.weekday() == 3, f"2026-08-13 不是周四？{d.weekday()}"
    return d


class TestTimetable(unittest.TestCase):
    def test_ten_slots(self):
        self.assertEqual(len(TIMETABLE), 10)

    def test_slots_have_required_fields(self):
        for s in TIMETABLE:
            self.assertIsInstance(s, TimetableSlot)
            self.assertTrue(s.slot_id)
            self.assertTrue(s.label)
            self.assertIn("A", s.mode_note)
            self.assertIn("B", s.mode_note)
            self.assertIn("C", s.mode_note)

    def test_before_open(self):
        s, st = get_current_slot(_dt(9, 14))
        self.assertIsNone(s)
        self.assertEqual(st, "before_open")

    def test_fake_auction_start(self):
        s, st = get_current_slot(_dt(9, 15))
        self.assertEqual(s.slot_id, "fake_auction")
        self.assertEqual(st, "active")

    def test_real_auction(self):
        s, st = get_current_slot(_dt(9, 22))
        self.assertEqual(s.slot_id, "real_auction")
        self.assertEqual(st, "active")

    def test_auction_confirm(self):
        s, st = get_current_slot(_dt(9, 25))
        self.assertEqual(s.slot_id, "auction_confirm")
        self.assertEqual(st, "active")

    def test_seal_main(self):
        s, st = get_current_slot(_dt(9, 40))
        self.assertEqual(s.slot_id, "seal_main")
        self.assertEqual(st, "active")

    def test_divergence(self):
        s, st = get_current_slot(_dt(10, 15))
        self.assertEqual(s.slot_id, "divergence")
        self.assertEqual(st, "active")

    def test_gap_returns_next_slot(self):
        s, st = get_current_slot(_dt(10, 35))
        self.assertEqual(st, "gap")
        self.assertIsNotNone(s)
        self.assertEqual(s.slot_id, "reseal_window")

    def test_lunch_break_active(self):
        s, st = get_current_slot(_dt(11, 30))
        self.assertEqual(s.slot_id, "lunch_break")
        self.assertEqual(st, "active")

    def test_reseal_window(self):
        s, st = get_current_slot(_dt(14, 15))
        self.assertEqual(s.slot_id, "reseal_window")
        self.assertEqual(st, "active")

    def test_stop_loss(self):
        s, st = get_current_slot(_dt(14, 30))
        self.assertEqual(s.slot_id, "stop_loss")
        self.assertEqual(st, "active")

    def test_tail_session(self):
        s, st = get_current_slot(_dt(14, 55))
        self.assertEqual(s.slot_id, "tail_session")
        self.assertEqual(st, "active")

    def test_post_review(self):
        s, st = get_current_slot(_dt(15, 30))
        self.assertEqual(s.slot_id, "post_review")
        self.assertEqual(st, "active")

    def test_after_close(self):
        s, st = get_current_slot(_dt(22, 0))
        self.assertIsNone(s)
        self.assertEqual(st, "after_close")

    def test_weekend(self):
        sat = datetime(2026, 8, 15, 10, 0)  # 周六
        self.assertEqual(sat.weekday(), 5)
        s, st = get_current_slot(sat)
        self.assertIsNone(s)
        self.assertEqual(st, "weekend")


class TestAttentionMode(unittest.TestCase):
    def setUp(self):
        self._orig_path = coach._COACH_CONFIG_PATH
        import tempfile
        self.tmp = tempfile.NamedTemporaryFile(
            suffix=".json", delete=False, mode="w"
        )
        self.tmp.close()
        coach._COACH_CONFIG_PATH = __import__("pathlib").Path(self.tmp.name)

    def tearDown(self):
        coach._COACH_CONFIG_PATH = self._orig_path
        os.unlink(self.tmp.name)

    def test_default_is_A(self):
        self.assertEqual(get_attention_mode("2026-08-13"), "A")

    def test_write_and_read(self):
        set_attention_mode("2026-08-13", "B")
        self.assertEqual(get_attention_mode("2026-08-13"), "B")

    def test_cross_day_reset(self):
        set_attention_mode("2026-08-13", "C")
        self.assertEqual(get_attention_mode("2026-08-12"), "A")

    def test_invalid_mode_raises(self):
        with self.assertRaises(ValueError):
            set_attention_mode("2026-08-13", "D")


class TestModeRules(unittest.TestCase):
    def test_all_modes_have_rules(self):
        for m in ("A", "B", "C"):
            self.assertIn(m, MODE_RULES)
            self.assertIn("label", MODE_RULES[m])
            self.assertIn("desc", MODE_RULES[m])

    def test_C_has_four_rules(self):
        desc = MODE_RULES["C"]["desc"]
        self.assertIn("禁开新仓", desc)
        self.assertIn("止损前置", desc)
        self.assertIn("max_hold_days", desc)
        self.assertIn("收盘", desc)


class TestConditionChecklist(unittest.TestCase):
    def _mock_states(self):
        return [
            {"code": "600001", "name": "甲股", "status": "holding",
             "strategy": "first_plate", "trade_date": "2026-08-13",
             "entry_date": "2026-08-10", "attention_mode": "A"},
            {"code": "600002", "name": "乙股", "status": "watching",
             "strategy": None, "trade_date": "2026-08-13"},
            {"code": "600003", "name": "丙股", "status": "filtered",
             "trade_date": "2026-08-13"},
        ]

    def test_filters_non_active_statuses(self):
        with mock.patch("workflow_state_repo.list_states",
                        return_value=self._mock_states()), \
             mock.patch.object(coach, "_build_funnel_index", return_value={}), \
             mock.patch.object(coach, "_build_bomb_index", return_value={}):
            cl = build_condition_checklist("2026-08-13")
        codes = [c["code"] for c in cl]
        self.assertIn("600001", codes)
        self.assertIn("600002", codes)
        self.assertNotIn("600003", codes)  # filtered 排除

    def test_max_hold_warning_triggered(self):
        states = [self._mock_states()[0]]  # holding first_plate entry 8-10
        with mock.patch("workflow_state_repo.list_states", return_value=states), \
             mock.patch.object(coach, "_build_funnel_index", return_value={}), \
             mock.patch.object(coach, "_build_bomb_index", return_value={}):
            cl = build_condition_checklist("2026-08-13")
        # first_plate max_hold_days=3, entry 8-10 → 3 日 → 触发
        self.assertIsNotNone(cl[0]["max_hold_warning"])
        self.assertIn("max_hold_days=3", cl[0]["max_hold_warning"])

    def test_empty_states_returns_empty(self):
        with mock.patch("workflow_state_repo.list_states", return_value=[]):
            cl = build_condition_checklist("2026-08-13")
        self.assertEqual(cl, [])

    def test_missing_data_status(self):
        """无 seal 快照时 data_status=missing（不臆造）。"""
        with mock.patch("workflow_state_repo.list_states",
                        return_value=[self._mock_states()[1]]), \
             mock.patch.object(coach, "_build_funnel_index", return_value={}), \
             mock.patch.object(coach, "_build_bomb_index", return_value={}):
            cl = build_condition_checklist("2026-08-13")
        self.assertEqual(cl[0]["data_status"], "missing")
        self.assertEqual(cl[0]["bomb_alerts"], [])

    def test_repo_exception_returns_empty(self):
        with mock.patch("workflow_state_repo.list_states",
                        side_effect=RuntimeError("boom")):
            cl = build_condition_checklist("2026-08-13")
        self.assertEqual(cl, [])


class TestBuildCoachState(unittest.TestCase):
    def test_full_state(self):
        with mock.patch("workflow_state_repo.list_states", return_value=[]), \
             mock.patch.object(coach, "is_trading_day", return_value=True), \
             mock.patch.object(coach, "get_attention_mode", return_value="A"):
            state = build_coach_state("2026-08-13", now=_dt(9, 25))
        self.assertEqual(state["date"], "2026-08-13")
        self.assertEqual(state["current_slot"]["slot_id"], "auction_confirm")
        self.assertEqual(state["slot_status"], "active")
        self.assertEqual(state["attention_mode"], "A")
        self.assertEqual(state["checklist"], [])
        self.assertTrue(state["is_trading_day"])

    def test_weekend_state(self):
        sat = datetime(2026, 8, 15, 10, 0)
        with mock.patch("workflow_state_repo.list_states", return_value=[]), \
             mock.patch.object(coach, "get_attention_mode", return_value="A"):
            state = build_coach_state("2026-08-15", now=sat)
        self.assertEqual(state["slot_status"], "weekend")
        self.assertIsNone(state["current_slot"])


if __name__ == "__main__":
    unittest.main()
