# -*- coding: utf-8 -*-
"""S166 fresh tests — risk ledger: excursion MFE/MAE + at_risk + risk_rules +
attribution + inbox。

离线：journal 的网络边界（get_daily_review / em_zt_topic_pool / kline_multi）全打桩。
excursion._compute 是纯函数直接喂行情行；at_risk/risk_rules/inbox 读 journal 账本
（用 fresh fixture 隔离 VR_DATA_DIR + 写合成交易）。
"""
from __future__ import annotations

import json
import os

import pytest

import journal
import excursion
import at_risk
import risk_rules
import attribution
import inbox


_ZERO_FEES = {"commission_rate": 0.0, "commission_min": 0.0,
              "stamp_tax_rate": 0.0, "transfer_fee_rate": 0.0}


@pytest.fixture
def fresh(tmp_path, monkeypatch):
    monkeypatch.setenv("VR_DATA_DIR", str(tmp_path))
    monkeypatch.setattr(journal, "get_daily_review", lambda d: {
        "sti_phase": "高潮", "money_effect_median": 1.2, "zt_total": 33,
    })
    import astock
    monkeypatch.setattr(astock, "em_zt_topic_pool", lambda *a, **k: [])
    monkeypatch.setattr(astock, "kline_multi", lambda *a, **k: ([], "stub"))
    return journal


def _trade(cost, buy, sell, realized, code="600519", name="茅台"):
    """合成一个已平仓 trade（settled 就绪，绕过 _settle）。"""
    return {
        "id": "t1", "code": code, "name": name, "playbook": "打板",
        "settled": {"has_fills": True, "avg_cost": cost, "first_buy": buy,
                    "last_sell": sell, "realized_pct": realized,
                    "realized_pnl": realized * 100, "closed": True,
                    "amount": cost * 100},
    }


# ============================ excursion MFE/MAE ============================
class TestExcursion:
    def test_compute_capture_rate(self):
        rows = [
            {"date": "2026-08-01", "high": 12.0, "low": 9.5, "close": 11.0},
            {"date": "2026-08-02", "high": 13.0, "low": 10.5, "close": 12.0},
            {"date": "2026-08-03", "high": 11.0, "low": 9.0, "close": 10.0},
        ]
        t = _trade(10.0, "2026-08-01", "2026-08-03", 0.0)   # 落袋 0%
        r = excursion._compute(t, rows)
        assert r["available"] is True
        assert r["mfe_pct"] == 30.0          # (13/10-1)*100
        assert r["mae_pct"] == -10.0         # (9/10-1)*100
        assert r["capture_rate"] == 0.0      # 落袋0 / MFE30
        assert r["capture_note"] is not None  # "几乎没吃到"

    def test_compute_certain_inner_days(self):
        # 中间完整交易日给 mfe_certain / mae_certain
        rows = [
            {"date": "2026-08-01", "high": 11.0, "low": 9.5, "close": 10.5},
            {"date": "2026-08-02", "high": 14.0, "low": 10.0, "close": 12.0},
            {"date": "2026-08-03", "high": 12.0, "low": 9.0, "close": 11.0},
        ]
        t = _trade(10.0, "2026-08-01", "2026-08-03", 10.0)
        r = excursion._compute(t, rows)
        assert r["mfe_pct"] == 40.0          # 14/10
        # inner = 2026-08-02（严格在买卖日之间）：high14 → mfe_certain=40，low10 → mae_certain=0
        assert r["mfe_certain"] == 40.0
        assert r["mae_certain"] == 0.0
        assert r["bars_inner"] == 1
        assert "中间完整交易日" in r["precision"]

    def test_same_day_only_upper_bound(self):
        rows = [{"date": "2026-08-01", "high": 12.0, "low": 9.0, "close": 10.0}]
        t = _trade(10.0, "2026-08-01", "2026-08-01", 0.0)
        r = excursion._compute(t, rows)
        assert r["same_day"] is True
        assert r["mfe_certain"] is None      # 无中间日
        assert "上界" in r["precision"]

    def test_for_trade_cached_only_reads_cache(self, fresh, monkeypatch):
        # 写缓存行情 → for_trade_cached_only 零网络算
        import os
        from vr_paths import resolve_data_dir
        code = "600519"
        cache_dir = resolve_data_dir() / "cache" / "bars"
        cache_dir.mkdir(parents=True, exist_ok=True)
        p = cache_dir / f"{code}_2026-08-01_2026-08-01.json"
        p.write_text(json.dumps([{"date": "2026-08-01", "high": 12.0,
                                  "low": 9.0, "close": 10.0}]), encoding="utf-8")
        t = _trade(10.0, "2026-08-01", "2026-08-01", 0.0, code=code)
        r = excursion.for_trade_cached_only(t)
        assert r is not None and r["available"] is True
        assert r["mfe_pct"] == 20.0

    def test_for_trade_cached_only_returns_none_when_no_cache(self, fresh):
        t = _trade(10.0, "2026-08-01", "2026-08-03", 5.0)
        assert excursion.for_trade_cached_only(t) is None

    def test_summary_empty(self, fresh):
        r = excursion.summary()
        assert r["available"] is False


# ============================ at_risk 在险资金 ============================
class TestAtRisk:
    def test_positions_bounded_and_unbounded(self, fresh):
        # 写两笔未平仓：一笔有止损，一笔没有
        fresh.add_trade("2026-08-01", "600519", "茅台", "打板",
                        fills=[{"side": "buy", "date": "2026-08-01",
                                "price": 10.0, "shares": 100}],
                        planned_stop=9.0)
        fresh.add_trade("2026-08-01", "000001", "平安", "低吸",
                        fills=[{"side": "buy", "date": "2026-08-01",
                                "price": 20.0, "shares": 200}])
        trades = fresh.all_trades()
        pos = at_risk.positions(trades)
        assert len(pos) == 2
        bounded = [p for p in pos if p["bounded"]]
        unbounded = [p for p in pos if not p["bounded"]]
        assert len(bounded) == 1 and bounded[0]["at_risk"] == 100.0   # (10-9)*100
        assert len(unbounded) == 1 and unbounded[0]["at_risk"] is None

    def test_report_with_equity_base(self, fresh):
        at_risk.save_equity_base(100000.0)
        fresh.add_trade("2026-08-01", "600519", "茅台", "打板",
                        fills=[{"side": "buy", "date": "2026-08-01",
                                "price": 10.0, "shares": 100}],
                        planned_stop=9.0)
        rep = at_risk.report()
        assert rep["available"] is True
        assert rep["total_at_risk"] == 100.0
        assert rep["at_risk_of_equity_pct"] == 0.1   # 100/100000*100
        # R3 诚实标签
        assert "risk_status" in rep
        assert any(l["key"] == "stop_gap_down_ritual" for l in rep["risk_status"]["labels"])

    def test_report_unbounded_note(self, fresh):
        fresh.add_trade("2026-08-01", "000001", "平安", "低吸",
                        fills=[{"side": "buy", "date": "2026-08-01",
                                "price": 20.0, "shares": 200}])
        rep = at_risk.report()
        assert rep["unbounded_count"] == 1
        assert "unbounded_note" in rep
        assert rep["risk_status"]["labels"][0]["key"] == "unbounded_unknown"

    def test_report_no_positions(self, fresh):
        rep = at_risk.report()
        assert rep["available"] is False

    def test_save_equity_base_rejects_nonpositive(self, fresh):
        with pytest.raises(ValueError, match="正数"):
            at_risk.save_equity_base(-100.0)

    def test_honest_risk_labels_has_kill_switch_note(self):
        rs = at_risk.honest_risk_labels([{}], [])
        assert "kill_switch" in rs["kill_switch_note"]
        assert "非阻断" in rs["kill_switch_note"]              # 通知级非阻断
        assert "不是 core 风控保护" in rs["kill_switch_note"]   # 不宣称 core 风控保护
        assert "非 'core 风控保护'" in rs["honest_summary"]    # 诚实标：非保护


# ============================ risk_rules 风险宪法 ============================
class TestRiskRules:
    def test_load_default_rules(self, fresh):
        r = risk_rules.load_rules()
        assert r["_is_default"] is True
        assert r["max_positions"] == 3

    def test_save_then_load(self, fresh):
        risk_rules.save_rules({"max_positions": 5, "max_loss_per_trade_pct": 7.0})
        r = risk_rules.load_rules()
        assert r["_is_default"] is False
        assert r["max_positions"] == 5
        assert r["max_loss_per_trade_pct"] == 7.0

    def test_save_rejects_unknown_key(self, fresh):
        with pytest.raises(ValueError, match="没有可保存的规则"):
            risk_rules.save_rules({"bogus_key": 1.0})

    def test_equity_curve_drawdown(self, fresh):
        trades = [
            {"settled": {"realized_pnl": 100.0, "last_sell": "2026-08-01"}, "date": "2026-08-01", "created_at": "1"},
            {"settled": {"realized_pnl": -50.0, "last_sell": "2026-08-02"}, "date": "2026-08-02", "created_at": "2"},
            {"settled": {"realized_pnl": -30.0, "last_sell": "2026-08-03"}, "date": "2026-08-03", "created_at": "3"},
        ]
        eq = risk_rules.equity_curve(trades)
        assert eq["available"] is True
        assert eq["net_pnl"] == 20.0
        assert eq["peak"] == 100.0
        assert eq["current_drawdown"] == 80.0     # 100 - 20
        assert eq["max_drawdown"] == 80.0
        assert eq["win_rate"] == round(1 / 3, 3)   # 1 win / (1 win + 2 loss)
        assert eq["profit_factor"] == round(100 / 80, 2)

    def test_equity_curve_empty(self, fresh):
        assert risk_rules.equity_curve([])["available"] is False

    def test_rolling_windows(self, fresh):
        trades = [
            {"settled": {"realized_pnl": float(v), "last_sell": f"2026-08-{i:02d}"},
             "date": f"2026-08-{i:02d}", "created_at": str(i)}
            for i, v in enumerate([5, -3, 4, -2, 6, -1, 3, -2, 7, -4, 2], start=1)
        ]
        r = risk_rules.rolling(trades)
        assert r["available"] is True
        assert r["lifetime"]["trades"] == 11
        assert r["windows"]["10"]["window"] == 10
        assert r["windows"]["10"]["enough"] is True

    def test_violations_over_position_limit(self, fresh):
        risk_rules.save_rules({"max_positions": 1})
        # 同一天持有 2 只
        trades = [
            {"code": "600519", "date": "2026-08-01",
             "settled": {"has_fills": True, "first_buy": "2026-08-01", "closed": False}},
            {"code": "000001", "date": "2026-08-01",
             "settled": {"has_fills": True, "first_buy": "2026-08-01", "closed": False}},
        ]
        v = risk_rules.violations(trades)
        assert v["available"] is True
        keys = [f["rule"] for f in v["violations"]]
        assert "max_positions" in keys

    def test_violations_single_loss_over_limit(self, fresh):
        risk_rules.save_rules({"max_loss_per_trade_pct": 5.0})
        trades = [{"date": "2026-08-01", "pnl_pct": -8.0, "name": "茅台", "code": "600519"}]
        v = risk_rules.violations(trades)
        assert any(f["rule"] == "max_loss_per_trade_pct" for f in v["violations"])

    def test_report_no_closed(self, fresh):
        rep = risk_rules.report()
        assert rep["equity"]["available"] is False

    def test_render_offline_no_ai(self, fresh):
        # render 是纯文本兜底，不接 AI
        rep = {"equity": {"available": False}, "trade_count": 0}
        assert risk_rules.render(rep).startswith("[个人风控")


# ============================ attribution 归因 ============================
class TestAttribution:
    def test_degrades_without_hits(self, fresh):
        # Vibe-Research 无 reflection 数据源 → available:False，不臆造命中
        fresh.add_trade("2026-08-01", "600519", "茅台", "打板",
                        fills=[{"side": "buy", "date": "2026-08-01", "price": 10.0, "shares": 100},
                               {"side": "sell", "date": "2026-08-02", "price": 12.0, "shares": 100}])
        r = attribution.attribution()
        assert r["available"] is False
        assert "市场判断记录" in r["reason"]

    def test_render_empty(self):
        assert attribution.render({"available": False}) == ""


# ============================ inbox 收件箱 ============================
class TestInbox:
    def test_build_empty(self, fresh):
        r = inbox.build()
        assert r["available"] is False

    def test_build_flags_over_loss_limit(self, fresh):
        risk_rules.save_rules({"max_loss_per_trade_pct": 5.0})
        fresh.add_trade("2026-08-01", "600519", "茅台", "打板", pnl_pct=-8.0)
        r = inbox.build()
        assert r["available"] is True
        keys = [f["key"] for f in r["items"][0]["flags"]]
        assert "over_loss_limit" in keys

    def test_build_flags_unplanned(self, fresh):
        fresh.add_trade("2026-08-01", "600519", "茅台", "打板", pnl_pct=3.0, as_planned=False)
        r = inbox.build()
        keys = [f["key"] for f in r["items"][0]["flags"]]
        assert "unplanned" in keys

    def test_build_flags_no_stop_on_open(self, fresh):
        # 未平仓 + 有成交明细 + 无计划止损 → no_stop
        fresh.add_trade("2026-08-01", "600519", "茅台", "打板",
                        fills=[{"side": "buy", "date": "2026-08-01", "price": 10.0, "shares": 100}])
        r = inbox.build()
        keys = [f["key"] for f in r["items"][0]["flags"]]
        assert "no_stop" in keys

    def test_build_uses_cached_excursion_zero_network(self, fresh, monkeypatch):
        # 已平仓 + 缓存行情 → inbox 走 for_trade_cached_only（零网络）
        fresh.add_trade("2026-08-01", "600519", "茅台", "打板",
                        fills=[{"side": "buy", "date": "2026-08-01", "price": 10.0, "shares": 100},
                               {"side": "sell", "date": "2026-08-02", "price": 12.0, "shares": 100}])
        # 打桩 for_trade_cached_only 返回深 MAE
        monkeypatch.setattr(excursion, "for_trade_cached_only", lambda t: {
            "available": True, "mae_pct": -12.0, "mfe_pct": 30.0,
            "realized_pct": 20.0, "capture_rate": 0.67, "same_day": False})
        r = inbox.build()
        assert r["available"] is True
        assert r["excursion_available"] is True
        keys = [f["key"] for f in r["items"][0]["flags"]]
        assert "deep_mae" in keys


# ============================ router 16 端点（TestClient，不依赖 app.py）============================
# app.py 因并发编辑被 defer（M）。这里用最小 FastAPI app 仅挂 journal router 验证 16 端点实跑绿。
class TestRouter:
    @pytest.fixture
    def client(self, tmp_path, monkeypatch):
        from fastapi import FastAPI
        from fastapi.testclient import TestClient
        from routers import journal as jr

        monkeypatch.setenv("VR_DATA_DIR", str(tmp_path))
        monkeypatch.setattr(journal, "get_daily_review", lambda d: {
            "sti_phase": "高潮", "money_effect_median": 1.2, "zt_total": 33})
        import astock
        monkeypatch.setattr(astock, "em_zt_topic_pool", lambda *a, **k: [])
        monkeypatch.setattr(astock, "kline_multi", lambda *a, **k: ([], "stub"))
        app = FastAPI()
        app.include_router(jr.router)
        return TestClient(app)

    def test_journal_list_empty(self, client):
        r = client.get("/api/journal/list")
        assert r.status_code == 200
        assert r.json() == {"trades": [], "total": 0}

    def test_journal_add_then_list(self, client):
        r = client.post("/api/journal/add", json={
            "date": "2026-08-01", "code": "600519", "name": "茅台", "playbook": "打板",
            "fills": [{"side": "buy", "date": "2026-08-01", "price": 10.0, "shares": 100},
                      {"side": "sell", "date": "2026-08-01", "price": 12.0, "shares": 100}]})
        assert r.status_code == 200 and r.json()["ok"] is True
        assert client.get("/api/journal/list").json()["total"] == 1

    def test_journal_add_bad_code_400(self, client):
        r = client.post("/api/journal/add", json={
            "date": "2026-08-01", "code": "abc", "name": "x", "playbook": "打板"})
        assert r.status_code == 400

    def test_journal_stats_and_fees(self, client):
        assert client.get("/api/journal/stats").status_code == 200
        fees = client.get("/api/journal/fees").json()
        assert fees["is_default"] is True

    def test_risk_rules_get_default(self, client):
        r = client.get("/api/risk/rules")
        assert r.status_code == 200 and r.json()["_is_default"] is True

    def test_risk_rules_save(self, client):
        r = client.post("/api/risk/rules", json={"max_positions": 5})
        assert r.status_code == 200
        assert client.get("/api/risk/rules").json()["max_positions"] == 5

    def test_risk_at_risk_empty(self, client):
        assert client.get("/api/risk/at-risk").json()["available"] is False

    def test_risk_attribution_degrades(self, client):
        # 无 reflection 数据 → 降级 available:False，不臆造
        r = client.get("/api/risk/attribution")
        assert r.status_code == 200 and r.json()["available"] is False

    def test_risk_inbox_empty(self, client):
        assert client.get("/api/risk/inbox").json()["available"] is False

    def test_risk_excursion_empty(self, client):
        assert client.get("/api/risk/excursion").json()["available"] is False

    def test_equity_base_get_set(self, client):
        assert client.get("/api/risk/equity-base").json() == {"equity_base": None}
        r = client.post("/api/risk/equity-base", json={"base": 100000.0})
        assert r.status_code == 200 and r.json()["equity_base"] == 100000.0

    def test_risk_report_empty(self, client):
        # 无已平仓交易 → equity 不可用，但不报 500
        r = client.get("/api/risk/report")
        assert r.status_code == 200
        assert r.json()["equity"]["available"] is False

    def test_risk_at_risk_has_honest_label(self, client):
        # 写一笔未平仓持仓 → report 带 R3 诚实标签
        client.post("/api/risk/equity-base", json={"base": 100000.0})
        client.post("/api/journal/add", json={
            "date": "2026-08-01", "code": "600519", "name": "茅台", "playbook": "打板",
            "fills": [{"side": "buy", "date": "2026-08-01", "price": 10.0, "shares": 100}],
            "planned_stop": 9.0})
        rep = client.get("/api/risk/at-risk").json()
        assert rep["available"] is True
        assert "risk_status" in rep
        assert any(l["key"] == "stop_gap_down_ritual"
                   for l in rep["risk_status"]["labels"])
