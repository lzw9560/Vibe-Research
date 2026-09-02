# -*- coding: utf-8 -*-
"""S145 Tier 2 测试：path-dependent winrate gate——SL/TP/max_hold 路径模拟。

R1：simulate_holding 抽取自 strategy_backtest._backtest_single（T+1 buy + T+2 起检查 stop/take/max_hold）。
R3/R5：forward_test_records path 列 + get_forward_test_summary path-winrate/lift 双报 + verdict 切 path。
"""
from __future__ import annotations

import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

backend_dir = Path(__file__).resolve().parent.parent
if str(backend_dir) not in sys.path:
    sys.path.insert(0, str(backend_dir))

import sqlite3
from strategies.kline_returns import simulate_holding
from strategies.forward_test import (
    _ensure_table, DailyRecommendation, record_daily_recommendations,
    record_actual_returns, record_universe_returns, get_forward_test_summary,
)


@pytest.fixture
def fresh_db(tmp_path, monkeypatch):
    """每个测试用临时 DB 隔离。"""
    db_path = tmp_path / "test_s145.db"
    monkeypatch.setattr("strategies.forward_test._DB", str(db_path))
    _ensure_table()
    return str(db_path)


def _bar(date, o, h, l, c):
    """SimpleNamespace bar（strategy_backtest 风格）。"""
    return SimpleNamespace(date=date, open=o, high=h, low=l, close=c)


SIGNAL = "2026-08-01"


# ===========================================================================
# R1：simulate_holding 路径模拟
# ===========================================================================

def test_r1_take_profit_on_t2():
    """T+2 high 触止盈 → won=True, return_pct=profit, exit_reason=take。"""
    bars = [
        _bar(SIGNAL, 10.0, 10.5, 9.5, 10.0),
        _bar("2026-08-02", 10.5, 10.6, 10.5, 11.0),     # T+1 买入日（open=10.5 入场）
        _bar("2026-08-03", 11.0, 12.0, 10.5, 11.5),     # T+2 high=12≥11.32 触止盈
    ]
    res = simulate_holding(bars, SIGNAL, stop_pct=-3.0, take_profit_pct=8.0, max_hold_days=3)
    assert res is not None
    assert res["won"] is True
    assert res["return_pct"] == 8.0
    assert res["exit_reason"] == "take"
    assert res["exit_date"] == "2026-08-03"


def test_r1_stop_loss_on_t2():
    """T+2 low 触止损 → won=False, return_pct=stop, exit_reason=stop。"""
    bars = [
        _bar(SIGNAL, 10.0, 10.5, 9.5, 10.0),
        _bar("2026-08-02", 10.5, 10.6, 10.5, 11.0),     # T+1 买入日
        _bar("2026-08-03", 10.3, 10.4, 9.5, 9.6),      # T+2 low=9.5≤10.185 触止损
    ]
    res = simulate_holding(bars, SIGNAL, stop_pct=-3.0, take_profit_pct=8.0, max_hold_days=3)
    assert res is not None
    assert res["won"] is False
    assert res["return_pct"] == -3.0
    assert res["exit_reason"] == "stop"


def test_r1_max_hold_exit():
    """无 stop/take 触发 → max_hold 收盘 exit。"""
    bars = [
        _bar(SIGNAL, 10.0, 10.5, 9.5, 10.0),
        _bar("2026-08-02", 10.5, 10.6, 10.5, 10.8),     # T+1 买入日 open=10.5
        _bar("2026-08-03", 10.8, 11.0, 10.6, 10.9),     # T+2 无触发
        _bar("2026-08-04", 10.9, 11.0, 10.7, 11.0),     # T+3 exit close=11.0
    ]
    res = simulate_holding(bars, SIGNAL, stop_pct=-3.0, take_profit_pct=8.0, max_hold_days=3)
    assert res is not None
    # max_hold=3 → exit_idx=idx+1+3=T+3 close=11.0; ret=(11.0-10.5)/10.5*100≈4.76
    assert res["exit_reason"] == "max_hold"
    assert res["won"] is True
    assert res["return_pct"] == pytest.approx(4.76, abs=0.05)


def test_r1_buy_day_stop_not_triggered():
    """T+1（买入日）触止损也不触发——A 股 T+1 买入日不可卖。

    T+1 low 触止损但跳过；T+2/T+3 无触发 → max_hold exit at T+3。
    """
    bars = [
        _bar(SIGNAL, 10.0, 10.5, 9.5, 10.0),
        _bar("2026-08-02", 10.5, 10.6, 10.0, 10.2),     # T+1 买入日，low=10.0<10.185（触止损但跳过）
        _bar("2026-08-03", 10.3, 10.8, 10.2, 10.5),     # T+2 无触发
        _bar("2026-08-04", 10.5, 10.6, 10.3, 10.4),     # T+3 exit close=10.4
    ]
    res = simulate_holding(bars, SIGNAL, stop_pct=-3.0, take_profit_pct=8.0, max_hold_days=3)
    assert res is not None
    # T+1 止损跳过，T+3 max_hold exit close=10.4 → ret=(10.4-10.5)/10.5*100≈-0.95
    assert res["exit_reason"] == "max_hold"
    assert res["won"] is False
    assert res["return_pct"] == pytest.approx(-0.95, abs=0.05)


def test_r1_missing_t2_returns_none():
    """缺 T+2 bar（max_hold=1 需 T+2 exit）→ None（无法评估 T+1）。"""
    bars = [
        _bar(SIGNAL, 10.0, 10.5, 9.5, 10.0),
        _bar("2026-08-02", 10.5, 11.0, 10.3, 10.8),     # 只有 T+1
    ]
    res = simulate_holding(bars, SIGNAL, stop_pct=-3.0, take_profit_pct=8.0, max_hold_days=1)
    assert res is None


def test_r1_accepts_dict_bars():
    """simulate_holding 兼容 dict bars（kline_returns 风格）。"""
    bars = [
        {"date": SIGNAL, "open": 10.0, "high": 10.5, "low": 9.5, "close": 10.0},
        {"date": "2026-08-02", "open": 10.5, "high": 10.6, "low": 10.5, "close": 11.0},
        {"date": "2026-08-03", "open": 11.0, "high": 12.0, "low": 10.5, "close": 11.5},
    ]
    res = simulate_holding(bars, SIGNAL, stop_pct=-3.0, take_profit_pct=8.0, max_hold_days=3)
    assert res is not None and res["exit_reason"] == "take"


# ===========================================================================
# R3/R4：forward_test path 列回填 + get_forward_test_summary path 双报
# ===========================================================================

def test_r3_path_columns_backfilled(fresh_db):
    """R3: record_actual_returns 回填 return_path/is_win_path/exit_reason。"""
    rec = DailyRecommendation("2026-08-13", "000001", "X", "first_plate", 70.0)
    record_daily_recommendations("2026-08-13", [rec])
    updated = record_actual_returns("2026-08-13", {
        "000001": {"return_open2close": 2.0, "return_close2close": 2.0, "next_pctChg": 2.0,
                   "return_open2next_close": 3.0, "is_unbuyable": False,
                   "return_path": 8.0, "is_win_path": True, "exit_reason": "take"},
    })
    assert updated == 1
    conn = sqlite3.connect(fresh_db)
    row = conn.execute(
        "SELECT return_path, is_win_path, exit_reason FROM forward_test_records WHERE code='000001'"
    ).fetchone()
    conn.close()
    assert row == (8.0, 1, "take")


def test_r3_path_null_for_unbuyable(fresh_db):
    """R3: unbuyable pick → path=NULL（不可买无意义，is_win_path NULL 排除）。"""
    rec = DailyRecommendation("2026-08-13", "000001", "X", "first_plate", 70.0)
    record_daily_recommendations("2026-08-13", [rec])
    record_actual_returns("2026-08-13", {
        "000001": {"return_open2close": 0.0, "return_close2close": 0.0, "next_pctChg": 10.0,
                   "is_unbuyable": True,  # 一字板封死，path 不该有意义
                   "return_path": None, "is_win_path": None, "exit_reason": None},
    })
    conn = sqlite3.connect(fresh_db)
    row = conn.execute(
        "SELECT return_path, is_win_path, is_win FROM forward_test_records WHERE code='000001'"
    ).fetchone()
    conn.close()
    assert row[0] is None  # path NULL
    assert row[1] is None  # is_win_path NULL（排除）
    assert row[2] is None  # is_win NULL（排除非 0 计亏）


def test_r4_path_dual_report_vs_o2c(fresh_db):
    """R4: get_forward_test_summary 双报 win_rate_path + path_lift（vs o2c endpoint）。

    o2c 全赢（T+0 100%），path 只在 day%2==0 赢（52%——止损摩擦更低）。
    universe path 全赢（默认 params）→ path_lift = 52/100 = 0.52。
    """
    for day in range(25):
        date = f"2026-08-{day+1:02d}"
        recs = [DailyRecommendation(date, f"00{day}01", "A", "first_plate", 70.0)]
        record_daily_recommendations(date, recs)
        o2c = 2.0
        path_won = (day % 2 == 0)
        path_ret = 8.0 if path_won else -3.0
        record_actual_returns(date, {
            f"00{day}01": {"return_open2close": o2c, "return_close2close": o2c, "next_pctChg": o2c,
                           "return_open2next_close": o2c, "is_unbuyable": False,
                           "return_path": path_ret, "is_win_path": path_won,
                           "exit_reason": "take" if path_won else "stop"},
        })
        uni = {f"1{day}0{i}": {"return_open2close": 1.0, "return_close2close": 1.0, "next_pctChg": 1.0,
                               "is_unbuyable": False, "return_path": 1.0, "is_win_path": True,
                               "exit_reason": "max_hold"}
               for i in range(5)}
        record_universe_returns(date, uni)

    result = get_forward_test_summary(benchmark_win_rate=60.0, min_days=20)
    # o2c verdict（escape hatch）= 100%；path 双报 = 52%（13/25）——path 更低（止损摩擦）
    assert result.win_rate == 100.0
    assert result.win_rate_path == 52.0
    assert result.path_settled == 25
    # universe path 全赢（默认 params）→ path_lift = 52/100 = 0.52
    assert result.random_win_rate_path == 100.0
    assert result.path_lift == 0.52
