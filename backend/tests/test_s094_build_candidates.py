# -*- coding: utf-8 -*-
"""S094 S2 T8：build_non_limitup_candidates 单测（spec R14 统一候选 shape）。

候选 {code,name,bars,sector,sector_rank,close}：
- name 从 code_industry 反查（_load_code_names，monkeypatch 注入假名表）
- sector_rank=板块内个股排名（compute_sector_stock_rank_map，T7）
- close=bars[-1].close
- bars<20 跳过

纯单元测试：合成 industry_map/cache，无 DB/网络（_load_code_names 被 monkeypatch）。
"""
from __future__ import annotations

import sys
from datetime import date, timedelta
from pathlib import Path

import pytest

backend_dir = Path(__file__).resolve().parent.parent
if str(backend_dir) not in sys.path:
    sys.path.insert(0, str(backend_dir))

from strategies import market_scan
from strategies.market_scan import build_non_limitup_candidates


def _bars(n: int, start: float = 10.0, step: float = 0.5) -> list[dict]:
    """n 根日K，close 从 start 起每根 +step（n>=20 够 MA/5日涨幅窗口）。"""
    d = date(2026, 8, 1)
    return [
        {
            "date": (d + timedelta(days=i)).isoformat(),
            "close": start + i * step,
            "high": start + i * step,
            "low": start + i * step,
            "volume": 100,
            "amount": 1e9,
        }
        for i in range(n)
    ]


class TestBuildNonLimitupCandidates:
    def test_carries_unified_shape(self, monkeypatch):
        # Arrange：电子板块 3 只，涨幅递减 → 板块内 rank 1/2/3
        industry_map = {"000001": "电子", "000002": "电子", "000003": "电子"}
        cache = {
            "000001": _bars(20, 10.0, 1.0),  # 涨最多 → 板块内 rank 1
            "000002": _bars(20, 10.0, 0.5),  # rank 2
            "000003": _bars(20, 10.0, 0.0),  # 持平 → rank 3
        }
        top = [{"industry": "电子", "zt_count_today": 1, "rank": 1}]
        monkeypatch.setattr(
            market_scan, "_load_code_names",
            lambda codes: {"000001": "甲", "000002": "乙", "000003": "丙"},
        )

        # Act
        cands = build_non_limitup_candidates(top, industry_map, cache, per_sector=20)

        # Assert
        assert len(cands) == 3
        by_code = {c["code"]: c for c in cands}
        assert by_code["000001"]["name"] == "甲"
        assert by_code["000001"]["sector"] == "电子"
        assert by_code["000001"]["sector_rank"] == 1  # 板块内最强
        assert by_code["000002"]["sector_rank"] == 2
        assert by_code["000003"]["sector_rank"] == 3
        # close = bars[-1].close（start + 19*step）
        assert by_code["000001"]["close"] == 10.0 + 19 * 1.0  # 29.0
        assert by_code["000003"]["close"] == 10.0  # step 0 → 恒 10

    def test_skips_stocks_with_bars_under_20(self, monkeypatch):
        industry_map = {"000001": "电子", "000002": "电子"}
        cache = {"000001": _bars(20), "000002": _bars(5)}  # 000002 bars<20 跳过
        top = [{"industry": "电子", "zt_count_today": 1, "rank": 1}]
        monkeypatch.setattr(market_scan, "_load_code_names", lambda codes: {})

        cands = build_non_limitup_candidates(top, industry_map, cache, per_sector=20)

        assert [c["code"] for c in cands] == ["000001"]

    def test_per_sector_caps_candidates(self, monkeypatch):
        # 5 只成分股，per_sector=2 → 只取前 2
        industry_map = {f"00000{i}": "电子" for i in range(1, 6)}
        cache = {f"00000{i}": _bars(20, 10.0, 0.1 * i) for i in range(1, 6)}
        top = [{"industry": "电子", "zt_count_today": 1, "rank": 1}]
        monkeypatch.setattr(market_scan, "_load_code_names", lambda codes: {})

        cands = build_non_limitup_candidates(top, industry_map, cache, per_sector=2)

        assert len(cands) == 2

    def test_name_empty_when_lookup_misses(self, monkeypatch):
        industry_map = {"000001": "电子"}
        cache = {"000001": _bars(20)}
        top = [{"industry": "电子", "zt_count_today": 1, "rank": 1}]
        monkeypatch.setattr(market_scan, "_load_code_names", lambda codes: {})  # 无名

        cands = build_non_limitup_candidates(top, industry_map, cache, per_sector=20)

        assert cands[0]["name"] == ""

    def test_empty_top_returns_empty(self):
        assert build_non_limitup_candidates([], {}, {}) == []

    def test_rank_uses_full_sector_not_sampled_subset(self, monkeypatch):
        # per_sector=1 只采 1 只候选，但 rank 应基于板块全成分（含未采样的最强股）
        industry_map = {"000001": "电子", "000002": "电子"}
        cache = {
            "000001": _bars(20, 10.0, 0.5),  # 采样进候选
            "000002": _bars(20, 10.0, 1.0),  # 未采样但涨更多 → 板块内 rank 1
        }
        top = [{"industry": "电子", "zt_count_today": 1, "rank": 1}]
        monkeypatch.setattr(market_scan, "_load_code_names", lambda codes: {})

        cands = build_non_limitup_candidates(top, industry_map, cache, per_sector=1)

        assert len(cands) == 1
        # 000001 排板块内第 2（000002 虽未采进候选但参与排名）
        assert cands[0]["code"] == "000001"
        assert cands[0]["sector_rank"] == 2
