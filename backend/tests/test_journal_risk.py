"""S149 Phase 3 P3-T4f — journal_risk 家族（at_risk/risk_rules/excursion/
attribution/inbox）单测。

移植自 vibe-astock@3c3b7c8。覆盖：
- at_risk：equity_base 读写 + positions + report（在险资金汇总）
- risk_rules：rules 读写 + equity_curve（golden）+ violations + rolling + discipline
- excursion：bars 缓存 + kline_multi 改写（不裸调 akshare）+ _compute MFE/MAE + 零网络缓存读
- attribution：_read_hits 降级（Vibe-Research 无 reflection 数据→诚实返空）
- inbox：build flags（over_loss/oversized/held_long/unplanned/no_stop）
- 隐私：5 源不 import urllib/akshare/requests + 数据路径走 VR_DATA_DIR
"""
from __future__ import annotations

import json

import pytest

import at_risk
import risk_rules
import excursion
import attribution
import inbox


@pytest.fixture
def isolated_risk(monkeypatch, tmp_path):
    """VR_DATA_DIR→tmp；journal.list_trades mock；kline_multi mock（不触网）。"""
    monkeypatch.setenv("VR_DATA_DIR", str(tmp_path))
    import journal
    trades_holder = {"trades": []}

    def _fake_list(limit=200):
        return {"trades": list(trades_holder["trades"]), "total": len(trades_holder["trades"])}
    monkeypatch.setattr(journal, "list_trades", _fake_list)
    # excursion.bars 不触网——mock kline_multi
    monkeypatch.setattr(excursion.astock, "kline_multi",
                        lambda code: ([], None))
    return tmp_path, trades_holder


def _trade(tid, pnl_pct=None, fills=None, planned_stop=None, as_planned=None,
           closed_realized=None, code="605398", name="新炬网络", playbook="打板",
           date="2026-09-03"):
    """构造一笔交易记录（settled 字段可控）。"""
    settled = {"has_fills": bool(fills), "closed": False, "avg_cost": None}
    if fills:
        settled.update({"first_buy": fills[0]["date"], "closed": True,
                        "avg_cost": fills[0]["price"],
                        "last_sell": fills[-1]["date"],
                        "realized_pnl": closed_realized,
                        "realized_pct": closed_realized,
                        "hold_days": 1, "amount": fills[0]["price"] * fills[0]["shares"],
                        "realized_by_date": {fills[-1]["date"]: closed_realized or 0}})
    return {"id": tid, "date": date, "code": code, "name": name,
            "playbook": playbook, "pnl_pct": pnl_pct, "fills": fills or [],
            "settled": settled, "planned_stop": planned_stop,
            "planned_target": None, "as_planned": as_planned,
            "created_at": f"{date} 10:00:00 CST", "note": ""}


# ───────────────────────── at_risk ─────────────────────────
def test_equity_base_load_save(isolated_risk):
    assert at_risk.load_equity_base() is None      # 没填
    r = at_risk.save_equity_base(100000)
    assert r["ok"] is True
    assert at_risk.load_equity_base() == 100000
    with pytest.raises(ValueError, match="正数"):
        at_risk.save_equity_base(-1)


def test_positions_open_with_stop(isolated_risk):
    """未平仓 + 有计划止损 → bounded + at_risk 算出。"""
    t = _trade("t1", fills=[{"side": "buy", "date": "2026-09-03",
                             "price": 10.0, "shares": 100}], planned_stop=9.0)
    # 未平仓：settled.closed=False
    t["settled"]["closed"] = False
    t["settled"]["avg_cost"] = 10.0
    t["settled"].pop("realized_pnl", None)
    pos = at_risk.positions([t])
    assert len(pos) == 1
    p = pos[0]
    assert p["bounded"] is True
    assert p["at_risk"] == 100.0        # (10-9)*100 = 100 元
    assert p["at_risk_pct"] == 10.0     # (1-9/10)*100 = 10%
    assert p["capital"] == 1000.0


def test_positions_no_stop_unbounded(isolated_risk):
    """未平仓 + 无计划止损 → unbounded（at_risk=None，不混入总数）。"""
    t = _trade("t1", fills=[{"side": "buy", "date": "2026-09-03",
                             "price": 10.0, "shares": 100}], planned_stop=None)
    t["settled"]["closed"] = False
    t["settled"]["avg_cost"] = 10.0
    pos = at_risk.positions([t])
    assert pos[0]["bounded"] is False
    assert pos[0]["at_risk"] is None


def test_at_risk_report_aggregates(isolated_risk):
    """report：有边界合计在险 + unbounded 单独报 + 占账户比。"""
    _, trades_holder = isolated_risk
    t1 = _trade("t1", fills=[{"side": "buy", "date": "2026-09-03",
                              "price": 10.0, "shares": 100}], planned_stop=9.0)
    t1["settled"]["closed"] = False; t1["settled"]["avg_cost"] = 10.0
    t2 = _trade("t2", fills=[{"side": "buy", "date": "2026-09-03",
                              "price": 5.0, "shares": 200}], planned_stop=None)
    t2["settled"]["closed"] = False; t2["settled"]["avg_cost"] = 5.0
    trades_holder["trades"] = [t1, t2]
    at_risk.save_equity_base(10000)
    rep = at_risk.report()
    assert rep["available"] is True
    assert rep["position_count"] == 2
    assert rep["total_at_risk"] == 100.0     # 只有 t1 bounded (10-9)*100
    assert rep["unbounded_count"] == 1
    assert rep["at_risk_of_equity_pct"] == 1.0   # 100/10000*100


# ───────────────────────── risk_rules ─────────────────────────
def test_rules_load_save(isolated_risk):
    rules = risk_rules.load_rules()
    assert rules["_is_default"] is True
    assert rules["max_positions"] == 3
    r = risk_rules.save_rules({"max_positions": 5, "max_loss_per_trade_pct": 3.0})
    assert r["ok"] is True
    again = risk_rules.load_rules()
    assert again["_is_default"] is False
    assert again["max_positions"] == 5
    with pytest.raises(ValueError, match="正数"):
        risk_rules.save_rules({"max_positions": -1})


def test_equity_curve_golden(isolated_risk):
    """equity_curve：2 笔 [+100, -50] → cum=50, peak=100, drawdown=50, win_rate=0.5。"""
    _, trades_holder = isolated_risk
    t1 = _trade("t1", fills=[{"side": "buy", "date": "2026-09-03", "price": 10, "shares": 100},
                             {"side": "sell", "date": "2026-09-04", "price": 11, "shares": 100}],
                closed_realized=100.0)
    t2 = _trade("t2", fills=[{"side": "buy", "date": "2026-09-05", "price": 10, "shares": 100},
                             {"side": "sell", "date": "2026-09-06", "price": 9.5, "shares": 100}],
                closed_realized=-50.0, date="2026-09-05")
    trades_holder["trades"] = [t1, t2]
    eq = risk_rules.equity_curve([t1, t2])
    assert eq["available"] is True
    assert eq["trades"] == 2
    assert eq["net_pnl"] == 50.0
    assert eq["peak"] == 100.0
    assert eq["current_drawdown"] == 50.0
    assert eq["win_rate"] == 0.5
    assert eq["worst_trade"] == -50.0


def test_violations_max_positions_breach(isolated_risk):
    """violations：同日持有超过 max_positions → 违反。"""
    # 3 只票同日未平仓（max_positions default=3 → 不超；改 2 测超）
    trades = []
    for i, code in enumerate(["000001", "000002", "000003"]):
        t = _trade(f"t{i}", code=code, fills=[{"side": "buy", "date": "2026-09-03",
                                                "price": 10, "shares": 100}])
        t["settled"]["closed"] = False
        t["settled"]["avg_cost"] = 10
        trades.append(t)
    rules = risk_rules.load_rules()
    rules["max_positions"] = 2
    v = risk_rules.violations(trades, rules)
    assert v["available"] is True
    pos_violations = [x for x in v["violations"] if x["rule"] == "max_positions"]
    assert len(pos_violations) >= 1
    assert pos_violations[0]["actual"] == 3


def test_rolling_windows(isolated_risk):
    """rolling：终身 + 10/20/50 窗口。样本不够标 enough=False。"""
    trades = [_trade(f"t{i}", fills=[{"side": "buy", "date": "2026-09-03", "price": 10, "shares": 100},
                                     {"side": "sell", "date": "2026-09-04", "price": 11, "shares": 100}],
                     closed_realized=10.0) for i in range(15)]
    r = risk_rules.rolling(trades)
    assert r["available"] is True
    assert r["lifetime"]["trades"] == 15
    assert r["windows"]["10"]["enough"] is True
    assert r["windows"]["50"]["enough"] is False   # 只有 15 笔 < 50


# ───────────────────────── excursion ─────────────────────────
def test_excursion_no_akshare_urllib_in_source():
    """防封底线：excursion 不得 import urllib/akshare/requests（走 kline_multi）。"""
    import inspect
    src = inspect.getsource(excursion)
    assert "import urllib" not in src
    assert "import akshare" not in src
    assert "import requests" not in src


def test_excursion_compute_mfe_mae_golden():
    """_compute：cost=10, bars high=[11,12], low=[9.5,9] → MFE=20%, MAE=-10%。"""
    trade = _trade("t1", fills=[{"side": "buy", "date": "2026-09-03", "price": 10, "shares": 100},
                                {"side": "sell", "date": "2026-09-05", "price": 11, "shares": 100}],
                   closed_realized=10.0)
    trade["settled"]["realized_pct"] = 10.0
    rows = [{"date": "2026-09-03", "high": 11.0, "low": 9.5, "close": 10.5},
            {"date": "2026-09-04", "high": 12.0, "low": 9.0, "close": 11.5},
            {"date": "2026-09-05", "high": 11.5, "low": 10.5, "close": 11.0}]
    r = excursion._compute(trade, rows)
    assert r["available"] is True
    assert r["mfe_pct"] == 20.0      # max high 12 → (12/10-1)*100
    assert r["mae_pct"] == -10.0     # min low 9 → (9/10-1)*100
    assert r["same_day"] is False
    # inner = [2026-09-04]（严格在 buy<sell 之间）
    assert r["bars_inner"] == 1
    assert r["mfe_certain"] == 20.0  # inner high=12
    assert r["mae_certain"] == -10.0  # inner low=9


def test_excursion_cached_only_zero_network(isolated_risk, monkeypatch):
    """for_trade_cached_only：只读缓存，一次网络请求都不发。"""
    _, _ = isolated_risk
    # 先写一份缓存
    import os
    cache = str(isolated_risk[0] / "cache" / "bars" / "605398_2026-09-03_2026-09-05.json")
    os.makedirs(os.path.dirname(cache), exist_ok=True)
    rows = [{"date": "2026-09-04", "high": 12.0, "low": 9.0, "close": 11.5}]
    with open(cache, "w", encoding="utf-8") as fh:
        json.dump(rows, fh)
    # kline_multi 若被调 → fail（零网络契约）
    monkeypatch.setattr(excursion.astock, "kline_multi",
                        lambda code: (_ for _ in ()).throw(AssertionError("缓存命中不应触网")))
    trade = _trade("t1", fills=[{"side": "buy", "date": "2026-09-03", "price": 10, "shares": 100},
                                {"side": "sell", "date": "2026-09-05", "price": 11, "shares": 100}],
                   closed_realized=10.0)
    r = excursion.for_trade_cached_only(trade)
    assert r is not None
    assert r["available"] is True


def test_excursion_bars_uses_kline_multi(isolated_risk, monkeypatch):
    """bars：调 kline_multi（防封，adjust='none' raw 口径）+ filter [start,end] + 缓存。"""
    called = {"n": 0}

    def _fake_kline(code, sources=None, adjust=None):
        called["n"] += 1
        return ([{"date": "2026-09-03", "high": 11, "low": 9.5, "close": 10.5},
                 {"date": "2026-09-04", "high": 12, "low": 9, "close": 11.5},
                 {"date": "2026-09-10", "high": 13, "low": 10, "close": 12}], "baidu")
    monkeypatch.setattr(excursion.astock, "kline_multi", _fake_kline)
    rows = excursion.bars("605398", "2026-09-03", "2026-09-05")
    assert called["n"] == 1
    assert len(rows) == 2          # 2026-09-10 过滤掉（>end）
    # 缓存命中——再调不触网
    monkeypatch.setattr(excursion.astock, "kline_multi",
                        lambda code: (_ for _ in ()).throw(AssertionError("缓存命中不应触网")))
    rows2 = excursion.bars("605398", "2026-09-03", "2026-09-05")
    assert rows2 == rows


# ───────────────────────── attribution（降级）─────────────────────────
def test_attribution_degrades_without_reflection_data(isolated_risk):
    """Vibe-Research 无 reflection 数据 → _read_hits 返空 → attribution 降级（不臆造）。"""
    _, trades_holder = isolated_risk
    t = _trade("t1", fills=[{"side": "buy", "date": "2026-09-03", "price": 10, "shares": 100},
                            {"side": "sell", "date": "2026-09-04", "price": 11, "shares": 100}],
               closed_realized=100.0)
    trades_holder["trades"] = [t]
    assert attribution._read_hits() == {}      # 诚实返空
    rep = attribution.attribution()
    assert rep["available"] is False
    assert "市场判断记录" in rep["reason"] or "reflection" in rep["reason"]


# ───────────────────────── inbox ─────────────────────────
def test_inbox_flags_over_loss(isolated_risk):
    """inbox.build：亏损超自设单笔上限 → over_loss_limit flag。"""
    _, trades_holder = isolated_risk
    t = _trade("t1", pnl_pct=-8.0, fills=[{"side": "buy", "date": "2026-09-03", "price": 10, "shares": 100},
                                          {"side": "sell", "date": "2026-09-04", "price": 9.2, "shares": 100}],
               closed_realized=-80.0, as_planned=False)
    trades_holder["trades"] = [t]
    rep = inbox.build()
    assert rep["available"] is True
    assert rep["count"] == 1
    keys = {f["key"] for f in rep["items"][0]["flags"]}
    assert "over_loss_limit" in keys      # -8% > default 5%
    assert "unplanned" in keys            # as_planned=False


def test_inbox_no_trades(isolated_risk):
    _, trades_holder = isolated_risk
    rep = inbox.build()
    assert rep["available"] is False
    assert rep["reason"] == "还没有交易记录"


# ───────────────────────── 路径 + 隐私 ─────────────────────────
def test_risk_paths_under_vr_data_dir(isolated_risk):
    tmp_path, _ = isolated_risk
    assert str(tmp_path) in at_risk._risk_dir()
    assert str(tmp_path) in risk_rules._risk_dir()
    assert str(tmp_path) in excursion._cache_dir()


def test_personal_modules_no_external_http_import():
    """5 个人数据模块不裸调 urllib/akshare/requests（em_get/kline_multi 防封）。"""
    import inspect
    for mod in (at_risk, risk_rules, excursion, attribution, inbox):
        src = inspect.getsource(mod)
        assert "import urllib" not in src, f"{mod.__name__} 不得 import urllib"
        assert "import akshare" not in src, f"{mod.__name__} 不得 import akshare"
        assert "import requests" not in src, f"{mod.__name__} 不得裸调 requests"
