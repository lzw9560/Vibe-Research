# -*- coding: utf-8 -*-
"""S144 Tier 1 测试：§44 测量地基修复——unbuyable 检测 + T+1 建模。

R1：kline_returns.compute_returns_for_codes 一字板（T+1 涨停封死）→ is_unbuyable=True。
R4：strategy_backtest._backtest_single T+1 规则——买入日（T+1）不可卖，止损/止盈从 T+2 起检查。
R5：return_open2next_close（T-open → T+1-close，可实现口径）计算。
"""
from __future__ import annotations

import sys
import types
from pathlib import Path
from types import SimpleNamespace

import pytest

backend_dir = Path(__file__).resolve().parent.parent
if str(backend_dir) not in sys.path:
    sys.path.insert(0, str(backend_dir))


# ===========================================================================
# R1：unbuyable 检测（kline_returns.compute_returns_for_codes，mock baostock）
# ===========================================================================

class _FakeRs:
    """baostock query_history_k_data_plus 返回的假结果集。"""

    def __init__(self, rows: list[list[str]]):
        # rows: 每行 = [date, open, high, low, close, volume, amount, turn, pctChg, isST]
        self._rows = rows
        self.error_code = "0"
        self._i = -1

    def next(self) -> bool:
        self._i += 1
        if self._i >= len(self._rows):
            return False
        return True

    def get_row_data(self) -> list[str]:
        return self._rows[self._i]


def _install_fake_baostock(monkeypatch, bars_by_code: dict[str, list[dict]]) -> types.ModuleType:
    """注入假 baostock 模块到 sys.modules（compute_returns_for_codes 内 import bs 用）。"""
    fake = types.ModuleType("baostock")

    class _Login:
        error_code = "0"
        error_msg = ""

    def _login():
        return _Login()

    def _logout():
        pass

    def _query(bs_code, fields, start_date, end_date, adjustflag="2"):
        # bs_code 形如 sh.600000 / sz.000001 → 取 6 位 code
        code6 = bs_code.split(".")[-1] if bs_code else ""
        rows = bars_by_code.get(code6, [])
        return _FakeRs([
            [b["date"], str(b["open"]), str(b["high"]), str(b["low"]),
             str(b["close"]), "0", "0", "0", str(b["pctChg"]), "0"]
            for b in rows
        ])

    fake.login = _login
    fake.logout = _logout
    fake.query_history_k_data_plus = _query
    monkeypatch.setitem(sys.modules, "baostock", fake)
    return fake


def test_r1_unbuyable_one_line_board_detected(monkeypatch):
    """R1：T+1 一字板（open=close=high=low + 涨停 pctChg≥9.8）→ is_unbuyable=True。"""
    signal = "2026-08-01"
    bars = [
        {"date": signal, "open": 10.0, "high": 10.5, "low": 9.8, "close": 10.0, "pctChg": 10.0},
        # T+1 一字板涨停：四价相等 + pctChg=+10%
        {"date": "2026-08-02", "open": 11.0, "high": 11.0, "low": 11.0, "close": 11.0, "pctChg": 10.0},
    ]
    _install_fake_baostock(monkeypatch, {"000001": bars})

    from strategies.kline_returns import compute_returns_for_codes
    out = compute_returns_for_codes(signal, ["000001"])

    assert "000001" in out
    assert out["000001"]["is_unbuyable"] is True
    # o2c 如实计算：一字板 o2c=(11-11)/11*100=0.0（精确断言，非弱 is-not-None）
    assert out["000001"]["return_open2close"] == pytest.approx(0.0, abs=0.01)


def test_r1_buyable_normal_up_day_not_flagged(monkeypatch):
    """R1：T+1 正常上涨（有日内区间 high>low）→ is_unbuyable=False。"""
    signal = "2026-08-01"
    bars = [
        {"date": signal, "open": 10.0, "high": 10.5, "low": 9.8, "close": 10.0, "pctChg": 1.0},
        # T+1 高开冲高回落（有区间），pctChg=+5%——可买
        {"date": "2026-08-02", "open": 10.2, "high": 10.8, "low": 10.0, "close": 10.5, "pctChg": 5.0},
    ]
    _install_fake_baostock(monkeypatch, {"000001": bars})

    from strategies.kline_returns import compute_returns_for_codes
    out = compute_returns_for_codes(signal, ["000001"])

    assert out["000001"]["is_unbuyable"] is False


def test_r1_limit_down_one_line_board_is_buyable(monkeypatch):
    """R1：T+1 一字跌停（pctChg≤-9.8）对做多策略是可买的（跌停有人抛、买家成交）→ is_unbuyable=False。

    spec §5 写 abs(pctChg)>=9.8% 粗判，但做多策略只有涨停封死不可买；
    跌停一字板可买（独立判断修正：is_unbuyable 只覆盖涨停方向）。
    """
    signal = "2026-08-01"
    bars = [
        {"date": signal, "open": 10.0, "high": 10.5, "low": 9.8, "close": 10.0, "pctChg": 1.0},
        {"date": "2026-08-02", "open": 9.0, "high": 9.0, "low": 9.0, "close": 9.0, "pctChg": -10.0},
    ]
    _install_fake_baostock(monkeypatch, {"000001": bars})

    from strategies.kline_returns import compute_returns_for_codes
    out = compute_returns_for_codes(signal, ["000001"])

    assert out["000001"]["is_unbuyable"] is False, "一字跌停对做多策略可买，不应标 unbuyable"


def test_r5_open2next_close_computed(monkeypatch):
    """R5：return_open2next_close = (T+2 close - T+1 open)/T+1 open*100（可实现 T+1 口径）。

    信号 T 盘后知，买 T+1 开盘（nb.open），A 股 T+1 买入日不可卖，卖 T+2 收盘（nnb.close）。
    o2c（T+1 intraday）非策略收益；o2nc 才是可实现收益。
    """
    signal = "2026-08-01"
    bars = [
        {"date": signal, "open": 10.0, "high": 10.5, "low": 9.8, "close": 10.2, "pctChg": 2.0},
        {"date": "2026-08-02", "open": 10.3, "high": 10.8, "low": 10.1, "close": 10.6, "pctChg": 3.92},  # T+1 (nb)
        {"date": "2026-08-03", "open": 10.7, "high": 11.0, "low": 10.5, "close": 10.9, "pctChg": 2.83},  # T+2 (nnb)
    ]
    _install_fake_baostock(monkeypatch, {"000001": bars})

    from strategies.kline_returns import compute_returns_for_codes
    out = compute_returns_for_codes(signal, ["000001"])

    # o2nc = (T+2 close - T+1 open)/T+1 open = (10.9 - 10.3)/10.3*100 ≈ 5.83（可实现 T+1）
    assert out["000001"]["return_open2next_close"] == pytest.approx(5.83, abs=0.05)
    # o2c = (T+1 close - T+1 open)/T+1 open = (10.6-10.3)/10.3*100 ≈ 2.91（T+0 intraday，诚实基线）
    assert out["000001"]["return_open2close"] == pytest.approx(2.91, abs=0.05)


def test_r5_open2next_close_none_when_t2_missing(monkeypatch):
    """R5：缺 T+2 bar（近期 picks，T+2 未可得）→ return_open2next_close=None（is_win fallback o2c）。"""
    signal = "2026-08-01"
    bars = [
        {"date": signal, "open": 10.0, "high": 10.5, "low": 9.8, "close": 10.2, "pctChg": 2.0},
        {"date": "2026-08-02", "open": 10.3, "high": 10.8, "low": 10.1, "close": 10.6, "pctChg": 3.92},  # 只有 T+1
    ]
    _install_fake_baostock(monkeypatch, {"000001": bars})

    from strategies.kline_returns import compute_returns_for_codes
    out = compute_returns_for_codes(signal, ["000001"])

    assert out["000001"]["return_open2next_close"] is None  # T+2 缺，o2nc 不可算
    assert out["000001"]["return_open2close"] is not None  # o2c 仍可得（T+1 intraday）


# ===========================================================================
# R4：strategy_backtest T+1 建模（_backtest_single）
# ===========================================================================

def _backtest_single(bars, date, max_hold_days=3, stop_pct=-3.0, profit_pct=8.0):
    from strategies.strategy_backtest import _backtest_single as _bs
    return _bs(bars, date, max_hold_days, stop_pct, profit_pct)


def test_r4_buy_day_stop_loss_not_triggered():
    """R4：T+1（买入日）触止损也不触发——A 股 T+1 买入日不可卖。

    构造：T+1 open=10.5 入场，T+1 low=10.0（跌破 -3% 止损 10.185），
    但 T+1 不可卖；T+2/T+3 未触止损/止盈 → 持有到 T+3 exit close=10.4 → ret≈-0.95。
    旧代码（range idx+1）会在 T+1 触发止损返 {False,-3.0}；新代码 {False,-0.95} 精确区分。
    """
    bars = [
        SimpleNamespace(date="2026-08-01", open=10.0, high=10.5, low=9.8, close=10.0),
        SimpleNamespace(date="2026-08-02", open=10.5, high=10.6, low=10.0, close=10.2),  # T+1 买入日，low 触止损
        SimpleNamespace(date="2026-08-03", open=10.3, high=10.8, low=10.2, close=10.5),  # T+2 未触止损/止盈
        SimpleNamespace(date="2026-08-04", open=10.5, high=10.6, low=10.3, close=10.4),  # T+3 exit close=10.4
    ]
    res = _backtest_single(bars, "2026-08-01", max_hold_days=3, stop_pct=-3.0, profit_pct=8.0)
    assert res is not None
    # 新代码：T+1 止损被跳过（买入日不可卖），持有到 T+3 exit close=10.4 → ret=(10.4-10.5)/10.5*100≈-0.95
    # 旧代码：T+1 触止损返 {False,-3.0}。精确断言区分（非弱永真式）。
    assert res["won"] is False  # exit at T+3 loss（非止损触发）
    assert res["return_pct"] == pytest.approx(-0.95, abs=0.05)


def test_r4_take_profit_on_buy_day_skipped():
    """R4：T+1（买入日）触止盈也不触发——A 股 T+1 买入日不可卖。

    构造：T+1 high=11≥止盈阈值 10.8（旧代码在 T+1 触发返 {True,8.0}），
    但 T+1 不可卖；T+2 未触止盈、T+3 low=9.5≤9.7 触止损 → 新代码 {False,-3.0} 精确区分。
    """
    bars = [
        SimpleNamespace(date="2026-08-01", open=10.0, high=10.5, low=9.5, close=10.0),
        SimpleNamespace(date="2026-08-02", open=10.0, high=11.0, low=10.0, close=10.5),  # T+1 买入日，high≥10.8 触止盈（旧触发）
        SimpleNamespace(date="2026-08-03", open=10.5, high=10.6, low=10.2, close=9.8),  # T+2 未触止盈（high<10.8）
        SimpleNamespace(date="2026-08-04", open=9.8, high=10.0, low=9.5, close=9.6),  # T+3 low=9.5≤9.7 触止损
    ]
    res = _backtest_single(bars, "2026-08-01", max_hold_days=3, stop_pct=-3.0, profit_pct=8.0)
    assert res is not None
    # 新代码：T+1 止盈被跳过，T+2 无触发，T+3 触止损 → {False,-3.0}
    # 旧代码：T+1 触止盈 → {True,8.0}。精确区分（非弱永真式）。
    assert res["won"] is False
    assert res["return_pct"] == -3.0  # T+3 止损触发（非 T+1 止盈）


def test_r4_max_hold_1_exits_at_t2_not_buy_day():
    """R4：max_hold_days=1（break_reseal/reverse_package）——T+1 买入，T+2 exit（非 T+1 买入日）。

    构造 max_hold=1：买入日 T+1 不可卖，持有到 T+2 收盘 exit。
    旧代码 exit_idx=idx+1=T+1（买入日，T+0 违规）；新代码 exit_idx=idx+2=T+2。
    """
    bars = [
        SimpleNamespace(date="2026-08-01", open=10.0, high=10.5, low=9.5, close=10.0),
        SimpleNamespace(date="2026-08-02", open=10.5, high=11.0, low=10.3, close=10.8),  # T+1 买入日
        SimpleNamespace(date="2026-08-03", open=10.8, high=11.2, low=10.6, close=11.0),  # T+2 exit
    ]
    res = _backtest_single(bars, "2026-08-01", max_hold_days=1, stop_pct=-3.0, profit_pct=8.0)
    assert res is not None
    # max_hold=1：T+2 exit close=11.0 → ret=(11.0-10.5)/10.5*100≈4.76>0 → won=True
    assert res["return_pct"] == pytest.approx(4.76, abs=0.05)
    assert res["won"] is True


def test_r4_missing_t2_bar_skipped():
    """R4：缺 T+2 bar（只有 T+1 买入日）→ 无法评估 T+1（不可卖首日=买入日）→ skip（None）。"""
    bars = [
        SimpleNamespace(date="2026-08-01", open=10.0, high=10.5, low=9.5, close=10.0),
        SimpleNamespace(date="2026-08-02", open=10.5, high=11.0, low=10.3, close=10.8),  # 只有 T+1
    ]
    res = _backtest_single(bars, "2026-08-01", max_hold_days=3, stop_pct=-3.0, profit_pct=8.0)
    assert res is None, "缺 T+2（首可卖日）→ 无法 T+1 评估，skip"
