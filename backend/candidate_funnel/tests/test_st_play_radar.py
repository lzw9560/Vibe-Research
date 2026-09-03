# -*- coding: utf-8 -*-
"""st_play_radar 生产端测试（S148 R3，TDD）。"""

from __future__ import annotations

import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from candidate_funnel.sources.st_play_radar import (
    classify_st_play,
    build_st_play_radar,
    save_st_play_radar,
    load_st_play_radar,
    run_st_play_radar,
)


class TestClassifyStPlay(unittest.TestCase):
    def test_zhaimao_warning_removed(self):
        self.assertEqual(classify_st_play([{"title": "撤销其他风险警示"}]), "摘帽")

    def test_zhaimao_delisting_warning_removed(self):
        self.assertEqual(classify_st_play([{"title": "撤销退市风险警示"}]), "摘帽")

    def test_zhaimao_keyword(self):
        self.assertEqual(classify_st_play([{"title": "公司股票撤销风险警示（摘帽）"}]), "摘帽")

    def test_chongzu(self):
        self.assertEqual(classify_st_play([{"title": "重大资产重组预案"}]), "重组")

    def test_chongzu借壳(self):
        self.assertEqual(classify_st_play([{"title": "关于公司借壳上市的公告"}]), "重组")

    def test_niukui_turnaround(self):
        self.assertEqual(classify_st_play([{"title": "公司业绩扭亏为盈"}]), "扭亏")

    def test_zhaimao_priority_over_chongzu(self):
        # 同时摘帽+重组公告 → 摘帽优先（最强信号）
        anns = [{"title": "撤销风险警示"}, {"title": "重大资产重组"}]
        self.assertEqual(classify_st_play(anns), "摘帽")

    def test_chongzu_priority_over_niukui(self):
        anns = [{"title": "重大资产重组"}, {"title": "扭亏"}]
        self.assertEqual(classify_st_play(anns), "重组")

    def test_no_play(self):
        self.assertIsNone(classify_st_play([{"title": "关于召开股东大会的通知"}]))

    def test_empty_or_none(self):
        self.assertIsNone(classify_st_play([]))
        self.assertIsNone(classify_st_play(None))


class TestBuildStPlayRadar(unittest.TestCase):
    def test_only_hits_enter_whitelist(self):
        def fetch(code):
            return {
                "603555": [{"title": "撤销其他风险警示"}],   # 摘帽
                "600123": [{"title": "关于召开股东大会"}],     # 无
                "000456": [{"title": "重大资产重组"}],       # 重组
            }.get(code, [])
        radar = build_st_play_radar(["603555", "600123", "000456"], fetch)
        self.assertEqual(radar, {"603555": "摘帽", "000456": "重组"})

    def test_fetch_failure_skipped_not_crash(self):
        def fetch(code):
            raise RuntimeError("network down")
        self.assertEqual(build_st_play_radar(["603555"], fetch), {})

    def test_empty_codes(self):
        self.assertEqual(build_st_play_radar([], lambda c: []), {})


class TestSaveLoadRoundtrip(unittest.TestCase):
    def test_save_then_load(self):
        with tempfile.TemporaryDirectory() as td:
            with mock.patch("vr_paths.resolve_data_dir", return_value=Path(td)):
                save_st_play_radar({"603555": "摘帽", "000456": "重组"})
                self.assertEqual(load_st_play_radar(), {"603555": "摘帽", "000456": "重组"})

    def test_load_missing_file_empty(self):
        with tempfile.TemporaryDirectory() as td:
            with mock.patch("vr_paths.resolve_data_dir", return_value=Path(td)):
                self.assertEqual(load_st_play_radar(), {})


class TestRunStPlayRadar(unittest.TestCase):
    def test_orchestrator_injectable_builds_and_saves(self):
        def fetch(code):
            return {"603555": [{"title": "撤销其他风险警示"}]}.get(code, [])
        with tempfile.TemporaryDirectory() as td:
            with mock.patch("vr_paths.resolve_data_dir", return_value=Path(td)):
                radar = run_st_play_radar(
                    st_codes=["603555", "000001"], fetch_announcements=fetch,
                )
                self.assertEqual(radar, {"603555": "摘帽"})
                self.assertEqual(load_st_play_radar(), {"603555": "摘帽"})  # 落盘可复读


if __name__ == "__main__":
    unittest.main()
