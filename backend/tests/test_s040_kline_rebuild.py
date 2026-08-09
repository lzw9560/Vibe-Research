# -*- coding: utf-8 -*-
"""S040 v2 · K 线重建引擎单测（全离线，无 live 网络）。

覆盖：
- is_limit_up 涨停判定（主板/创业板/ST/容差）
- count_consecutive_boards 连板计数
- build_ztpool_items_from_klines 从 K 线构造 ZTPoolItem
- rebuild_date 端到端（mock K 线 + mock DB codes，验证 data_source/missing_factors/3因子权重）
"""

import asyncio
from types import SimpleNamespace

import pytest


class TestIsLimitUp:
    def test_main_board_10pct(self):
        from limitup_screener.kline_rebuild import is_limit_up
        # 600519 主板 10%：prev_close=10 → limit=11
        assert is_limit_up(11.0, 10.0, "600519")
        assert not is_limit_up(10.5, 10.0, "600519")

    def test_gem_20pct(self):
        from limitup_screener.kline_rebuild import is_limit_up
        # 300750 创业板 20%：prev_close=10 → limit=12
        assert is_limit_up(12.0, 10.0, "300750")
        assert not is_limit_up(11.0, 10.0, "300750")

    def test_star_20pct(self):
        from limitup_screener.kline_rebuild import is_limit_up
        # 688001 科创板 20%
        assert is_limit_up(12.0, 10.0, "688001")

    def test_tolerance(self):
        from limitup_screener.kline_rebuild import is_limit_up
        # 600519 prev=10, limit=11.00, close=10.99 容差内
        assert is_limit_up(10.99, 10.0, "600519", tolerance=0.015)
        # close=10.98 超容差
        assert not is_limit_up(10.98, 10.0, "600519", tolerance=0.015)

    def test_zero_prev_close(self):
        from limitup_screener.kline_rebuild import is_limit_up
        assert not is_limit_up(11.0, 0.0, "600519")
        assert not is_limit_up(11.0, -1.0, "600519")


class TestCountConsecutiveBoards:
    def _bars(self, closes, code="600519"):
        return [SimpleNamespace(date=f"2026-08-0{i}", close=c, code=code) for i, c in enumerate(closes)]

    def test_three_consecutive(self):
        from limitup_screener.kline_rebuild import count_consecutive_boards
        # prev=10, 11.0(涨停) / 12.1(涨停, prev=11→limit=12.1) / 13.31(涨停, prev=12.1→limit=13.31)
        bars = self._bars([10.0, 11.0, 12.1, 13.31])
        assert count_consecutive_boards(bars, 3) == 3

    def test_one_then_break(self):
        from limitup_screener.kline_rebuild import count_consecutive_boards
        # prev=10, 11(涨停) / 10.5(未涨停) → 1 连板
        bars = self._bars([10.0, 11.0, 10.5])
        assert count_consecutive_boards(bars, 1) == 1

    def test_zero_when_not_limit(self):
        from limitup_screener.kline_rebuild import count_consecutive_boards
        bars = self._bars([10.0, 10.5])
        assert count_consecutive_boards(bars, 1) == 0


class TestBuildZTPoolItems:
    def _bars(self, code="600519"):
        return [
            SimpleNamespace(date="2026-08-04", close=10.0, open=10.0, code=code, name="测试"),
            SimpleNamespace(date="2026-08-05", close=11.0, open=10.5, code=code, name="测试"),  # 涨停(prev=10→limit=11)
            SimpleNamespace(date="2026-08-06", close=12.1, open=11.5, code=code, name="测试"),  # 连板2(prev=11→limit=12.1)
            SimpleNamespace(date="2026-08-07", close=10.8, open=12.0, code=code, name="测试"),  # 破板
        ]

    def test_build_items_and_today(self):
        from limitup_screener.kline_rebuild import build_ztpool_items_from_klines
        history, today = build_ztpool_items_from_klines("600519", "测试", self._bars(), "2026-08-05")
        assert len(history) >= 1
        assert today is not None
        assert today.code == "600519"
        assert today.pool_date == "2026-08-05"
        assert today.boards == 1  # 08-05 是首板

    def test_build_items_two_consecutive(self):
        from limitup_screener.kline_rebuild import build_ztpool_items_from_klines
        history, today = build_ztpool_items_from_klines("600519", "测试", self._bars(), "2026-08-06")
        assert today is not None
        assert today.boards == 2  # 08-06 是 2 连板
        assert today.seal_time is None  # K 线不可推
        assert today.broken_count is None

    def test_no_limit_today_returns_none(self):
        from limitup_screener.kline_rebuild import build_ztpool_items_from_klines
        history, today = build_ztpool_items_from_klines("600519", "测试", self._bars(), "2026-08-07")
        assert today is None  # 08-07 未涨停


class TestRebuildDate:
    def test_rebuild_returns_genescores_with_correct_metadata(self, monkeypatch):
        """端到端：mock K 线 + DB codes，验证 data_source/missing_factors/3因子。"""
        from limitup_screener import kline_rebuild as kr

        fake_bars = [
            SimpleNamespace(date="2026-08-04", close=10.0, open=10.0, code="600519", name="贵州茅台"),
            SimpleNamespace(date="2026-08-05", close=11.0, open=10.5, code="600519", name="贵州茅台"),
            SimpleNamespace(date="2026-08-06", close=12.1, open=11.5, code="600519", name="贵州茅台"),
        ]

        monkeypatch.setattr(kr, "_get_kline_bars", lambda code, end, lb: fake_bars)
        monkeypatch.setattr(kr, "_get_db_codes", lambda: ["600519"])

        results = asyncio.run(kr.rebuild_date("2026-08-06", codes=["600519"]))
        assert len(results) >= 1
        g = results[0]
        assert g.code == "600519"
        assert g.data_source == "kline_rebuild"
        assert g.missing_factors == ["封板率", "炸板后溢价"]
        assert g.factors.get("封板率") is None
        assert g.factors.get("炸板后溢价") is None
        assert g.factors.get("次日溢价率") is not None
        assert g.factors.get("红盘率") is not None
        assert g.factors.get("涨停频次") is not None

    def test_rebuild_no_codes_returns_empty(self, monkeypatch):
        from limitup_screener import kline_rebuild as kr
        monkeypatch.setattr(kr, "_get_kline_bars", lambda *a, **k: [])
        results = asyncio.run(kr.rebuild_date("2026-08-06", codes=[]))
        assert results == []
