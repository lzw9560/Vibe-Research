"""S171 R2 T8 test——月度 rebalance + PIT earnings gate + quintile。

TDD 验收（tasks.md T8.1-T8.4）：
- T8.2a PIT gate pubDate < D 严格（== D 是 lookahead ~25% 月）
- T8.2b get_pit_profit_row tie-breaking（同 pubDate 取最新 quarter 2026Q1 > 2025Q4）
- T8.3 不复权 close PE quintile（bottom Q1 + top Q5）+ 停牌 filter
- T8.4 epsTTM>0 排除率统计
"""
from __future__ import annotations

from pathlib import Path

import pytest

# sys.path: backend/ + tools/long_value_run.py
ROOT = Path(__file__).resolve().parents[2]
import sys

sys.path.insert(0, str(ROOT / "backend"))

from tools.long_value_run import (  # noqa: E402
    PitProfitRow,
    compute_exclusion_rate,
    compute_pe,
    get_pit_profit_row,
    select_quintiles,
    _quarter_sort_key,
)


# ---------- T8.2b: get_pit_profit_row PIT gate + tie-breaking ----------


def test_pit_gate_pubdate_strict_less_than_d():
    """T8.2a: pubDate < D 严格（pubDate == D 是 lookahead ~25% 月，不取）。"""
    profit = {
        "sh.600519": {
            "2026Q1": {"pubDate": "2026-04-30", "epsTTM": 52.0},  # == D，lookahead
            "2025Q4": {"pubDate": "2026-01-28", "epsTTM": 50.0},  # < D，PIT
        },
    }
    # D = 2026-04-30，pubDate == D 的 2026Q1 不取，取 2025Q4
    row = get_pit_profit_row("sh.600519", "2026-04-30", profit)
    assert row is not None
    assert row.quarter_key == "2025Q4"
    assert row.eps_ttm == 50.0


def test_pit_tie_breaking_latest_quarter():
    """T8.2b: 同 pubDate 取最新 quarter（2026Q1 > 2025Q4 非 dict 顺序）."""
    same_pub = "2026-01-28"
    profit = {
        "sh.600519": {
            "2025Q4": {"pubDate": same_pub, "epsTTM": 50.0},
            "2026Q1": {"pubDate": same_pub, "epsTTM": 52.0},
        },
    }
    row = get_pit_profit_row("sh.600519", "2026-04-30", profit)
    assert row is not None
    assert row.quarter_key == "2026Q1"  # 最新 quarter 非 dict 顺序 Q4
    assert row.eps_ttm == 52.0


def test_pit_no_profit_row_returns_none_not_fabricated():
    """T8.2b: 无 PIT profit row（无 quarter 或全 pubDate>=D）返 None 不臆造。"""
    profit = {
        "sh.600519": {"2026Q1": {"pubDate": "2026-05-01", "epsTTM": 52.0}},  # > D
    }
    row = get_pit_profit_row("sh.600519", "2026-04-30", profit)
    assert row is None  # 不臆造

    # code 不在 cache
    row2 = get_pit_profit_row("sh.000001", "2026-04-30", profit)
    assert row2 is None


def test_quarter_sort_key_parse():
    """T8.2b: _quarter_sort_key "2026Q1" → (2026, 1) 元组降序."""
    assert _quarter_sort_key("2026Q1") == (2026, 1)
    assert _quarter_sort_key("2025Q4") == (2025, 4)
    assert (2026, 1) > (2025, 4)  # 元组降序 tie-breaking
    assert _quarter_sort_key("bad") == (0, 0)


def test_pit_profit_row_frozen_dataclass():
    """T8 immutable: PitProfitRow frozen dataclass，setattr 报 FrozenInstanceError。"""
    row = PitProfitRow(
        code="sh.600519",
        rebalance_date="2026-04-30",
        quarter_key="2026Q1",
        pub_date="2026-04-28",
        eps_ttm=52.0,
    )
    with pytest.raises(Exception):  # FrozenInstanceError
        row.code = "sh.000001"  # type: ignore[misc]


# ---------- T8.2a: compute_pe PIT gate ----------


def test_compute_pe_uses_unadjusted_close_and_pit_eps():
    """T8.2a: PE = close / epsTTM（不复权 close + PIT epsTTM）."""
    profit = {
        "sh.600519": {"2026Q1": {"pubDate": "2026-04-28", "epsTTM": 52.0}},
    }
    pe = compute_pe("sh.600519", "2026-04-30", 1800.0, profit)
    assert pe is not None
    assert abs(pe - 1800.0 / 52.0) < 0.01


def test_compute_pe_eps_ttm_zero_or_negative_returns_none():
    """T8.2a/T8.4: epsTTM<=0 返 None（不臆造 PE）."""
    profit = {
        "sh.600519": {"2026Q1": {"pubDate": "2026-04-28", "epsTTM": 0.0}},
        "sh.000001": {"2026Q1": {"pubDate": "2026-04-28", "epsTTM": -1.5}},
    }
    assert compute_pe("sh.600519", "2026-04-30", 100.0, profit) is None
    assert compute_pe("sh.000001", "2026-04-30", 100.0, profit) is None


# ---------- T8.3: select_quintiles ----------


def _mock_kline(code: str, close: float, date: str = "2026-04-30", vol: float = 1000.0) -> list[dict]:
    return [{"date": date, "close": close, "volume": vol}]


def test_select_quintiles_bottom_q1_top_q5():
    """T8.3: bottom quintile Q1（低 PE value）+ top quintile Q5（高 PE growth）."""
    # 20 股，PE 1..20（code_i PE=i+1）
    profit = {f"sh.60000{i}": {"2026Q1": {"pubDate": "2026-04-28", "epsTTM": 1.0}} for i in range(10)}
    profit.update({f"sh.60001{i}": {"2026Q1": {"pubDate": "2026-04-28", "epsTTM": 1.0}} for i in range(10)})
    kline = {f"sh.60000{i}": _mock_kline(f"sh.60000{i}", float(i + 1)) for i in range(10)}
    kline.update({f"sh.60001{i}": _mock_kline(f"sh.60001{i}", float(i + 11)) for i in range(10)})
    universe = set(kline.keys())
    Q1, Q5, pe_map = select_quintiles("2026-04-30", universe, kline, profit)
    assert len(Q1) == 4  # 20 // 5 = 4 bottom
    assert len(Q5) == 4  # 20 // 5 = 4 top
    assert Q1.isdisjoint(Q5)  # Q1/Q5 不重叠
    # Q1 是低 PE（value）= 600000-600003
    assert "sh.600000" in Q1
    # Q5 是高 PE（growth）= 600016-600019
    assert "sh.600019" in Q5
    assert len(pe_map) == 20


def test_select_quintiles_suspended_stock_filtered():
    """T8.3 bug 9: 停牌 volume==0 跳过（不取 stale close）."""
    profit = {f"sh.60000{i}": {"2026Q1": {"pubDate": "2026-04-28", "epsTTM": 1.0}} for i in range(10)}
    profit.update({f"sh.60001{i}": {"2026Q1": {"pubDate": "2026-04-28", "epsTTM": 1.0}} for i in range(10)})
    kline = {f"sh.60000{i}": _mock_kline(f"sh.60000{i}", float(i + 1)) for i in range(10)}
    # sh.600010-600019 停牌（volume=0）
    kline.update({f"sh.60001{i}": [{"date": "2026-04-30", "close": 999.0, "volume": 0}] for i in range(10)})
    universe = set(kline.keys())
    Q1, Q5, pe_map = select_quintiles("2026-04-30", universe, kline, profit)
    # 10 股停牌被剔除，剩 10 股有 PE
    assert len(pe_map) == 10
    for code in pe_map:
        assert not code.startswith("sh.60001")  # 停牌股全被剔


def test_select_quintiles_small_universe_returns_empty():
    """T8.3: universe < 10 股返空（样本不足不强行 quintile）."""
    profit = {f"sh.60000{i}": {"2026Q1": {"pubDate": "2026-04-28", "epsTTM": 1.0}} for i in range(5)}
    kline = {f"sh.60000{i}": _mock_kline(f"sh.60000{i}", 10.0) for i in range(5)}
    universe = set(kline.keys())
    Q1, Q5, pe_map = select_quintiles("2026-04-30", universe, kline, profit)
    assert Q1 == set()
    assert Q5 == set()
    assert len(pe_map) == 5  # pe_map 仍返（供 debug）但 quintile 不分


# ---------- T8.4: compute_exclusion_rate ----------


def test_exclusion_rate_eps_ttm_zero_or_negative_excluded():
    """T8.4: epsTTM<=0 排除（无 PIT row 或 epsTTM<=0）."""
    profit = {
        "sh.600519": {"2026Q1": {"pubDate": "2026-04-28", "epsTTM": 50.0}},  # 保留
        "sh.600518": {"2026Q1": {"pubDate": "2026-04-28", "epsTTM": 0.0}},  # 排除
        "sh.600517": {"2026Q1": {"pubDate": "2026-04-28", "epsTTM": -1.0}},  # 排除
        "sh.600516": {"2026Q1": {"pubDate": "2026-05-01", "epsTTM": 10.0}},  # 排除（pubDate>D 无 PIT）
    }
    universe = {"sh.600519", "sh.600518", "sh.600517", "sh.600516"}
    rate = compute_exclusion_rate("2026-04-30", universe, profit)
    assert rate == 0.75  # 3/4 排除


def test_exclusion_rate_empty_universe_returns_zero():
    """T8.4: universe 空返 0.0（不臆造）."""
    assert compute_exclusion_rate("2026-04-30", set(), {}) == 0.0


def test_exclusion_rate_all_valid_returns_zero():
    """T8.4: 全 epsTTM>0 + PIT 返 0.0."""
    profit = {
        f"sh.60000{i}": {"2026Q1": {"pubDate": "2026-04-28", "epsTTM": float(i + 1)}}
        for i in range(10)
    }
    universe = set(profit.keys())
    assert compute_exclusion_rate("2026-04-30", universe, profit) == 0.0


# ---------- T8.1: month_end_rebalance_days（cache 路径，不跑 baostock） ----------


def test_month_end_rebalance_days_reads_cache(monkeypatch, tmp_path):
    """T8.1: 优先读 historical_universe_monthly.json cache 的 key（月末交易日）."""
    import tools.long_value_run as lvr

    cache = tmp_path / "s171_long_value" / "historical_universe_monthly.json"
    cache.parent.mkdir(parents=True)
    cache.write_text('{"2026-04-30": {"active": []}, "2026-05-29": {"active": []}}')
    monkeypatch.setattr(lvr, "SCRATCH", cache.parent)
    days = lvr.month_end_rebalance_days()
    assert days == ["2026-04-30", "2026-05-29"]
