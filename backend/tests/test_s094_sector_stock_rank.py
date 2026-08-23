# -*- coding: utf-8 -*-
"""S094 S2 T7：板块领涨子 compute_sector_stock_rank 单测（spec R11）。

R11：板块内按 relative_strength 降序排名（个股内，非 sector_strength_rank 板块间）。
供 dragon_head.match 板块内≤3 命中（R9，经 market_scan_ctx.sector_rank，S3 接线）。

实现口径（market_scan.compute_sector_stock_rank）：板块内 sector_ret 对所有成分股是
恒定偏移，故相对强度排名 ≡ 绝对 5 日涨幅排名（精确同序，非近似）——用
compute_relative_strength(sb, None, days) 取个股 5 日涨幅排序，免去重复聚合板块等权日K。

纯单元测试：合成 bars_map，无 DB/网络，可与全量套件并发跑（无共享资源）。
"""
from __future__ import annotations

import sys
from datetime import date, timedelta
from pathlib import Path

import pytest

backend_dir = Path(__file__).resolve().parent.parent
if str(backend_dir) not in sys.path:
    sys.path.insert(0, str(backend_dir))

from strategies.market_scan import compute_sector_stock_rank, compute_sector_stock_rank_map


def _bar(close: float, iso_date: str, high: float | None = None, low: float | None = None) -> dict:
    return {
        "date": iso_date,
        "close": close,
        "high": high if high is not None else close,
        "low": low if low is not None else close,
        "volume": 100,
        "amount": 1e9,
    }


def _stock_bars(prices: list[float], start_date: str = "2026-08-08") -> list[dict]:
    """prices 升序（旧→新），生成连续交易日日K（6 根够 5 日涨幅）。"""
    d = date.fromisoformat(start_date)
    return [_bar(p, (d + timedelta(days=i)).isoformat()) for i, p in enumerate(prices)]


class TestComputeSectorStockRank:
    def test_strongest_stock_ranks_first_weakest_last(self):
        # Arrange：A 涨最多 → 最强；C 持平 → 最弱
        bars_map = {
            "A": _stock_bars([10, 11, 12, 13, 14, 15]),        # +50% 5d
            "B": _stock_bars([10, 10.5, 11, 11.5, 12, 12.5]),   # +25% 5d
            "C": _stock_bars([10, 10, 10, 10, 10, 10]),         # 0% 5d
        }
        sector = ["A", "B", "C"]

        # Act / Assert
        assert compute_sector_stock_rank("A", sector, bars_map) == 1
        assert compute_sector_stock_rank("B", sector, bars_map) == 2
        assert compute_sector_stock_rank("C", sector, bars_map) == 3

    def test_code_not_in_sector_returns_none(self):
        bars_map = {"A": _stock_bars([10, 11, 12, 13, 14, 15])}
        assert compute_sector_stock_rank("X", ["A"], bars_map) is None

    def test_empty_sector_returns_none(self):
        bars_map = {"A": _stock_bars([10, 11, 12, 13, 14, 15])}
        assert compute_sector_stock_rank("A", [], bars_map) is None

    def test_insufficient_bars_returns_none(self):
        # code 自身仅 3 根 bar（5 日涨幅需 6 根）→ relative_strength None → 无法排名
        bars_map = {"A": _stock_bars([10, 11, 12])}
        assert compute_sector_stock_rank("A", ["A"], bars_map) is None

    def test_stock_with_data_ranks_above_dataless_peers(self):
        # 板块内仅 A 有足够数据，B/C 数据不足：A 仍 rank 1（不因同伴缺数据而失排名）
        bars_map = {
            "A": _stock_bars([10, 11, 12, 13, 14, 15]),
            "B": _stock_bars([10, 11]),  # 不足
            "C": _stock_bars([10, 11]),  # 不足
        }
        assert compute_sector_stock_rank("A", ["A", "B", "C"], bars_map) == 1
        # B/C 自身数据不足 → None
        assert compute_sector_stock_rank("B", ["A", "B", "C"], bars_map) is None
        assert compute_sector_stock_rank("C", ["A", "B", "C"], bars_map) is None

    def test_missing_bars_entry_treated_as_dataless(self):
        # sector_stocks 含 code 但 bars_map 无该 code 条目 → 视为数据不足 → None
        bars_map = {"A": _stock_bars([10, 11, 12, 13, 14, 15])}
        assert compute_sector_stock_rank("B", ["A", "B"], bars_map) is None


class TestComputeSectorStockRankMap:
    """批量版（spec R11）：板块内全部成分股排名表。"""

    def test_ranks_all_with_data(self):
        bars_map = {
            "A": _stock_bars([10, 11, 12, 13, 14, 15]),
            "B": _stock_bars([10, 10.5, 11, 11.5, 12, 12.5]),
            "C": _stock_bars([10, 10, 10, 10, 10, 10]),
        }
        assert compute_sector_stock_rank_map(["A", "B", "C"], bars_map) == {"A": 1, "B": 2, "C": 3}

    def test_excludes_dataless_stocks(self):
        # 数据不足者不入表（诚实降级，不臆造名次）
        bars_map = {
            "A": _stock_bars([10, 11, 12, 13, 14, 15]),
            "B": _stock_bars([10, 11]),  # 不足
        }
        assert compute_sector_stock_rank_map(["A", "B"], bars_map) == {"A": 1}

    def test_empty_sector_returns_empty(self):
        assert compute_sector_stock_rank_map([], {}) == {}

    def test_consistent_with_single_api(self):
        bars_map = {
            "A": _stock_bars([10, 11, 12, 13, 14, 15]),
            "B": _stock_bars([10, 10.5, 11, 11.5, 12, 12.5]),
            "C": _stock_bars([10, 10, 10, 10, 10, 10]),
        }
        sector = ["A", "B", "C"]
        rm = compute_sector_stock_rank_map(sector, bars_map)
        for code in sector:
            assert rm[code] == compute_sector_stock_rank(code, sector, bars_map)
