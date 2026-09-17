"""S171 R2 T8 test——月度 rebalance + PIT earnings gate + quintile。

TDD 验收（tasks.md T8.1-T8.4）：
- T8.2a PIT gate pubDate < D 严格（== D 是 lookahead ~25% 月）
- T8.2b get_pit_profit_row tie-breaking（同 pubDate 取最新 quarter 2026Q1 > 2025Q4）
- T8.3 不复权 close PE quintile（bottom Q1 + top Q5）+ 停牌 filter
- T8.4 epsTTM>0 排除率统计
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

# sys.path: backend/ + tools/long_value_run.py
ROOT = Path(__file__).resolve().parents[2]
import sys

sys.path.insert(0, str(ROOT / "backend"))

from tools.long_value_run import (  # noqa: E402
    PitProfitRow,
    ROUND_TRIP_COST,
    compute_exclusion_rate,
    compute_pe,
    get_pit_profit_row,
    select_quintiles,
    _quarter_sort_key,
    _build_q1_q5_spread_series,
    wire_q1_q5_spread,
    _monthly_return,
    wire_q1_excess_universe,
    _delisting_return,
    _build_delisting_map,
    inject_delisting,
    run_sensitivity_two_tier,
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


# ---------- T9: wire_q1_q5_spread（co-PRIMARY ① Q1-Q5 spread） ----------


def _make_t9_kline(scratch: Path) -> None:
    """构建 T9 kline_raw cache：3 股 2 日 close（供 mock select_quintiles 返 Q1/Q5）。"""
    (scratch / "baostock_kline_raw.json").write_text(json.dumps({
        "sh.600519": [
            {"date": "2026-04-30", "close": 100.0, "volume": 1},
            {"date": "2026-05-29", "close": 110.0, "volume": 1},
        ],
        "sz.000001": [
            {"date": "2026-04-30", "close": 20.0, "volume": 1},
            {"date": "2026-05-29", "close": 18.0, "volume": 1},
        ],
        "sz.000002": [
            {"date": "2026-04-30", "close": 10.0, "volume": 1},
            {"date": "2026-05-29", "close": 8.0, "volume": 1},
        ],
    }))


def test_build_q1_q5_returns_dates_and_cost(monkeypatch, tmp_path):
    """T9.1+T9.2: returns=[Q1_ret-Q5_ret per month]+dates=[month_ISO]+cost 双腿预扣。

    mock select_quintiles 返 Q1={000001,000002} Q5={600519}。
    Q1_ret = ((18-20)/20 + (8-10)/10)/2 = (-0.1+-0.2)/2 = -0.15
    Q5_ret = (110-100)/100 = 0.10
    spread = -0.15-0.10 = -0.25
    cost 预扣双腿：首月 prev 空 turnover_q1=1.0 turnover_q5=1.0 → -0.25-0.0025×2 = -0.255
    """
    import tools.long_value_run as lvr

    scratch = tmp_path / "s171_long_value"
    scratch.mkdir(parents=True)
    (scratch / "historical_universe_monthly.json").write_text(
        '{"2026-04-30": {"active": []}, "2026-05-29": {"active": []}}'
    )
    _make_t9_kline(scratch)
    monkeypatch.setattr(lvr, "SCRATCH", scratch)
    # mock select_quintiles 绕过 universe<10 限制
    monkeypatch.setattr(
        lvr, "select_quintiles",
        lambda d, u, k, p: ({"sz.000001", "sz.000002"}, {"sh.600519"}, {}),
    )
    cache = lvr.load_r1_cache()
    returns, dates = lvr._build_q1_q5_spread_series(cache)
    assert len(returns) == 1
    assert dates == ["2026-05"]
    assert abs(returns[0] - (-0.255)) < 1e-6  # spread -0.25 - cost 0.005（双腿 1.0+1.0）


def test_build_q1_q5_underpowered_no_cache(monkeypatch, tmp_path):
    """T9: 月度<2 返 ([], []) 不臆造（给 1 月 cache <2，走 if 不触发 baostock fallback）。"""
    import tools.long_value_run as lvr

    scratch = tmp_path / "s171_long_value"
    scratch.mkdir(parents=True)
    (scratch / "historical_universe_monthly.json").write_text(
        '{"2026-04-30": {"active": []}}'
    )  # 1 月 <2
    monkeypatch.setattr(lvr, "SCRATCH", scratch)
    cache = lvr.load_r1_cache()
    returns, dates = lvr._build_q1_q5_spread_series(cache)
    assert returns == []
    assert dates == []


def test_wire_q1_q5_underpowered_short_series(monkeypatch, tmp_path):
    """T9: wire_q1_q5_spread 有效 spread<2 返 underpowered 不臆造（不调 wire_verdict）。"""
    import tools.long_value_run as lvr

    scratch = tmp_path / "s171_long_value"
    scratch.mkdir(parents=True)
    monkeypatch.setattr(lvr, "SCRATCH", scratch)
    # mock _build 返 1 条（<2）
    monkeypatch.setattr(lvr, "_build_q1_q5_spread_series", lambda c: ([-0.1], ["2026-05"]))
    result = lvr.wire_q1_q5_spread(line_id="S171_Q1Q5", frozen_commit="abc12345")
    assert result["status"] == "underpowered"
    assert result["returns"] == [-0.1]
    assert "不可直接交易" in result["note"] or "spread" in result["note"]


# ---------- T10: wire_q1_excess_universe（co-PRIMARY ② selection）----------


def _mock_r1_cache() -> dict:
    """2 月 + 10 股 mock R1 cache：前 5 股低 PE=value Q1，后 5 股高 PE=growth Q5。"""
    months = ["2025-12-31", "2026-01-31"]
    codes = [f"sh.60000{i}" for i in range(10)]
    kline_raw = {
        code: [
            {"date": "2025-12-31", "close": 10.0 + i, "volume": 100},
            {"date": "2026-01-31", "close": 11.0 + i, "volume": 100},
        ]
        for i, code in enumerate(codes)
    }
    profit = {
        code: {"2025Q4": {"pubDate": "2025-11-01", "epsTTM": 1.0 if i < 5 else 0.1}}
        for i, code in enumerate(codes)
    }
    universe = {m: codes for m in months}
    return {
        "kline_raw": kline_raw,
        "profit": profit,
        "universe": universe,
        "stock_basic": {},
        "kline_qfq": {},
    }


def test_wire_q1_excess_universe_empty_when_months_lt_2():
    """T10: months<2 返 data_status=empty 不臆造。"""
    result = wire_q1_excess_universe(months=["2026-01-31"])
    assert result.get("data_status") == "empty"


def test_wire_q1_excess_universe_empty_when_cache_empty(monkeypatch):
    """T10: cache 空（无 PIT profit）返 data_status=empty 不臆造。"""
    monkeypatch.setattr("tools.long_value_run.load_r1_cache", lambda: {
        "kline_raw": {}, "profit": {}, "universe": {},
        "stock_basic": {}, "kline_qfq": {},
    })
    result = wire_q1_excess_universe(months=["2025-12-31", "2026-01-31"])
    assert result.get("data_status") == "empty"


def test_wire_q1_excess_universe_calls_wire_with_selection(monkeypatch):
    """T10.1+T10.2: 构建 survivors/universe + selection edge_type + window_sanity path + dates + 月度参数。"""
    monkeypatch.setattr("tools.long_value_run.load_r1_cache", _mock_r1_cache)
    captured: dict = {}

    def fake_wire(**kwargs):
        captured.update(kwargs)
        return {"status": "test", "data_snapshot_id": "test"}

    monkeypatch.setattr("tools._s44_wire.wire_verdict", fake_wire)

    months = ["2025-12-31", "2026-01-31"]
    wire_q1_excess_universe(months=months)

    # 验 selection edge_type
    assert captured.get("edge_type") == "selection"
    # 验 survivors_by_day + universe_by_day 传了（selection 测选股力）
    assert captured.get("survivors_by_day") is not None
    assert captured.get("universe_by_day") is not None
    # 验 dates 传了（PurgedKFold 要求）——第一个月无前月跳过，只有 2026-01-31
    assert captured.get("dates") == ["2026-01-31"]
    # 验 window_sanity path（R5 前置 sanity：mean+winrate+base_rate）
    ws = captured.get("window_sanity", {})
    assert "path" in ws
    assert {"mean", "winrate", "base_rate"} <= set(ws["path"])
    # 验月度参数 5 个（S171 R3+T1：walk_train=36/walk_test=12/step=12/event_materiality_floor=0.001）
    assert captured.get("walk_train") == 36
    assert captured.get("walk_test") == 12
    assert captured.get("step") == 12
    assert captured.get("event_materiality_floor") == 0.001
    # 验 line_id + round_trip_cost
    assert captured.get("line_id") == "S171_Q1_excess_universe"
    assert captured.get("round_trip_cost") == 0.0025
    # 验 returns 传了（Q1 所有月 returns 合并，for event_metrics 双算 R8）
    assert captured.get("returns") is not None
    assert len(captured["returns"]) > 0


def test_wire_q1_excess_universe_long_only_q1(monkeypatch):
    """T10.1: survivors 是 Q1（低 PE value，前 5 股）非 Q5（高 PE growth）——long-only 可实现。"""
    monkeypatch.setattr("tools.long_value_run.load_r1_cache", _mock_r1_cache)
    captured: dict = {}

    def fake_wire(**kwargs):
        captured.update(kwargs)
        return {"status": "test"}

    monkeypatch.setattr("tools._s44_wire.wire_verdict", fake_wire)

    wire_q1_excess_universe(months=["2025-12-31", "2026-01-31"])

    # survivors Q1 应是前 5 股（epsTTM=1.0 PE 低=value），非后 5 股（epsTTM=0.1 PE 高=growth）
    survivors = captured.get("survivors_by_day", {})
    # 2026-01-31 的 survivors returns 数量 <= 5（Q1 bottom 1/5 of 10）
    surv_returns = survivors.get("2026-01-31", [])
    assert 0 < len(surv_returns) <= 5
    # universe returns 应该是全 10 股
    u_returns = captured.get("universe_by_day", {}).get("2026-01-31", [])
    assert len(u_returns) == 10


def test_monthly_return_suspended_stock_returns_none():
    """T10 辅助: 停牌 volume==0 股 _monthly_return 返 None（不取 stale close）。"""
    bars = [
        {"date": "2025-12-31", "close": 10.0, "volume": 100},
        {"date": "2026-01-31", "close": 11.0, "volume": 0},  # 停牌
    ]
    # 停牌日 close 取不到（_close_on_or_before 跳过 volume==0）→ _monthly_return None
    assert _monthly_return(bars, "2026-01-31", "2025-12-31") is None


def test_monthly_return_first_month_no_prev():
    """T10 辅助: 第一个月无前月返 None。"""
    bars = [{"date": "2025-12-31", "close": 10.0, "volume": 100}]
    assert _monthly_return(bars, "2025-12-31", None) is None


# ---------- T12: 退市 -100% inject + sensitivity 两档 ----------


def test_delisting_return_injects_on_inject_month():
    """T12.1: 退市股 inject_month 返 inject_return（-1.0），不调 _monthly_return。"""
    delisting_map = {"sh.600001": "2026-01-31"}
    bars = [{"date": "2025-12-31", "close": 10.0, "volume": 100},
            {"date": "2026-01-31", "close": 11.0, "volume": 100}]
    r = _delisting_return("sh.600001", "2026-01-31", "2025-12-31", {"sh.600001": bars}, delisting_map, -1.0)
    assert r == -1.0


def test_delisting_return_normal_when_not_inject_month():
    """T12.1: 非注入月调 _monthly_return 正常算（退市股未到 inject 月）。"""
    delisting_map = {"sh.600001": "2026-02-28"}
    bars = [{"date": "2025-12-31", "close": 10.0, "volume": 100},
            {"date": "2026-01-31", "close": 11.0, "volume": 100}]
    r = _delisting_return("sh.600001", "2026-01-31", "2025-12-31", {"sh.600001": bars}, delisting_map, -1.0)
    assert r == 0.1  # (11-10)/10 正常算


def test_delisting_return_zero_bars_fallback_anchored():
    """T12.1: 0 bars 股 inject 月 fallback outDate 锚定——delisting_map[code] 在也注入。"""
    delisting_map = {"sh.600001": "2026-01-31"}
    r = _delisting_return("sh.600001", "2026-01-31", "2025-12-31", {}, delisting_map, -1.0)
    # 0 bars 但 delisting_map 锚定 → 注入 -1.0 不取 None
    assert r == -1.0


def test_inject_delisting_survivors_universe_consistent():
    """T12.1 bug 4: survivors + universe 同月同值注入（一致，不能只注入 survivors）。"""
    survivors = {"2026-01-31": [0.05]}
    universe = {"2026-01-31": [0.05, 0.03]}
    delisting_codes = {"2026-01-31": ["sh.600001"]}
    new_s, new_u = inject_delisting(survivors, universe, delisting_codes, -1.0)
    # survivors + universe 同月都加了 -1.0
    assert -1.0 in new_s["2026-01-31"]
    assert -1.0 in new_u["2026-01-31"]
    # 同月同值：两边的 inject_return 值相等
    assert new_s["2026-01-31"][-1] == new_u["2026-01-31"][-1] == -1.0


def test_inject_delisting_immutable():
    """T12.1: 原 dict 不被 mutate（返新 dict）。"""
    survivors = {"2026-01-31": [0.05]}
    universe = {"2026-01-31": [0.05]}
    delisting_codes = {"2026-01-31": ["sh.600001"]}
    inject_delisting(survivors, universe, delisting_codes, -1.0)
    # 原 dict 不变
    assert survivors == {"2026-01-31": [0.05]}
    assert universe == {"2026-01-31": [0.05]}


def test_build_delisting_map_from_outdate():
    """T12.1: _build_delisting_map 从 stock_basic outDate 读，非退市不进 map。"""
    stock_basic = {
        "sh.600001": {"code_name": "A", "ipoDate": "2018-01-01", "outDate": "2026-01-15"},
        "sh.600002": {"code_name": "B", "ipoDate": "2019-01-01", "outDate": ""},  # 非退市
    }
    m = _build_delisting_map(stock_basic)
    assert m == {"sh.600001": "2026-01-15"}


def test_run_sensitivity_two_tier_returns_structure(monkeypatch):
    """T12.2: 返 status_-0.5/status_-1.0/consistent/lift_diff/sensitive_flag 结构。"""
    monkeypatch.setattr("tools.long_value_run.load_r1_cache", _mock_r1_cache)
    captured: dict = {}

    def fake_wire(**kwargs):
        # 两档返不同 lift 测 sensitive_flag
        ir = kwargs.get("line_id", "")
        lift = 1.2 if "-0.5" in ir else 1.6  # lift_diff=0.4>0.3 sensitive
        captured[ir] = {"status": "exploratory", "lift": lift}
        return captured[ir]

    monkeypatch.setattr("tools._s44_wire.wire_verdict", fake_wire)
    r = run_sensitivity_two_tier(months=["2025-12-31", "2026-01-31"])
    assert "status_-0.5" in r
    assert "status_-1.0" in r
    assert "consistent" in r
    assert "lift_diff" in r
    assert "sensitive_flag" in r
    assert r["consistent"] is True  # 两档 status 同 exploratory
    assert abs(r["lift_diff"] - 0.4) < 0.001  # 浮点精度非 ==
    assert r["sensitive_flag"] is True  # 0.4>0.3


def test_run_sensitivity_consistent_when_status_equal(monkeypatch):
    """T12.2: 两档 status 同→consistent=True。"""
    monkeypatch.setattr("tools.long_value_run.load_r1_cache", _mock_r1_cache)

    def fake_wire(**kwargs):
        return {"status": "exploratory", "lift": 1.0}

    monkeypatch.setattr("tools._s44_wire.wire_verdict", fake_wire)
    r = run_sensitivity_two_tier(months=["2025-12-31", "2026-01-31"])
    assert r["consistent"] is True


def test_run_sensitivity_inconsistent_when_status_diff(monkeypatch):
    """T12.2: 两档 status 不同→consistent=False（降级 exploratory 标依赖退市假设）。"""
    monkeypatch.setattr("tools.long_value_run.load_r1_cache", _mock_r1_cache)

    def fake_wire(**kwargs):
        ir = kwargs.get("line_id", "")
        return {"status": "robust_edge" if "-0.5" in ir else "falsified", "lift": 1.0}

    monkeypatch.setattr("tools._s44_wire.wire_verdict", fake_wire)
    r = run_sensitivity_two_tier(months=["2025-12-31", "2026-01-31"])
    assert r["consistent"] is False
    assert r["status_-0.5"] == "robust_edge"
    assert r["status_-1.0"] == "falsified"


def test_run_sensitivity_empty_when_months_lt_2():
    """T12.2: months<2 返 data_status=empty 不臆造。"""
    r = run_sensitivity_two_tier(months=["2026-01-31"])
    assert r.get("data_status") == "empty"
