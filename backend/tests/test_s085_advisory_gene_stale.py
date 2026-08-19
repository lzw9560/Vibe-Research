# -*- coding: utf-8 -*-
"""S085 A7 消费方接线单测 — _latest_gene_map 回退时 AdvisoryItem 标注 stale。

验证：今日无 gene_scores 静默回退 DB MAX(date) 时，下游 advise_recommendations /
watchlist / holdings 拿到的 AdvisoryItem.extra 含 ``gene_data_date`` + ``data_stale``，
risk_notes 加一条「数据日=X，非今日…」如实呈现（binary 标注，不降级仓位/win_rate）。

工程底线（CLAUDE.md §1.2）：不臆造——无 date（``gene_data_date==""``）时 not stale，
不标「异常」。周末/节假日 latest!=today 属正常，措辞用「非今日」如实呈现。
"""
from __future__ import annotations

import asyncio
from datetime import datetime
from types import SimpleNamespace

import pytest

from strategies import position_advisor_v2 as adv


@pytest.fixture(autouse=True)
def _clear_advisory_caches():
    adv.clear_caches()
    yield
    adv.clear_caches()


def _gene(code: str, score: float = 70, name: str = "X", date: str = "") -> SimpleNamespace:
    """测试用 gene（含 .date，模拟 DB hydrate 后的 GeneScore）。"""
    return SimpleNamespace(code=code, name=name, total_score=score, factors={}, date=date)


def _sig(code: str, strategy_code: str = "SB", strategy_name: str = "首板挖掘") -> SimpleNamespace:
    return SimpleNamespace(code=code, strategy_code=strategy_code, strategy_name=strategy_name)


def _bt(strategy_code: str = "SB", win_rate: float = 0.62,
        sample_size: int = 30, strategy_name: str = "首板挖掘") -> SimpleNamespace:
    return SimpleNamespace(strategy_code=strategy_code, win_rate=win_rate,
                           sample_size=sample_size, strategy_name=strategy_name)


def _stale_db_conn(latest_date: str):
    """fake get_db：_latest_gene_map 回退分支 fetchone 返回 {d: latest_date}。"""
    from limitup_screener import data as ldata

    class _Cursor:
        def fetchone(self):
            return {"d": latest_date}

        def fetchall(self):
            return []

    class _Conn:
        def execute(self, *a, **kw):
            return _Cursor()

        def close(self):
            pass

    return _Conn


# ===========================================================================
# advise_recommendations —— stale 回退标注
# ===========================================================================

class TestRecommendationsStaleAnnotation:
    def test_stale_fallback_annotates_data_date_and_stale(self, monkeypatch):
        """今日无 gene_scores → 回退 DB MAX(date)=旧日 → AdvisoryItem 标 stale。"""
        stale_date = "2026-08-17"
        today = datetime.now().strftime("%Y-%m-%d")
        assert stale_date != today  # 旧日，触发 stale

        def _fake_load(d):
            if d == stale_date:
                return [_gene("600519", 80, date=stale_date)]
            return []

        monkeypatch.setattr(adv, "load_gene_scores", _fake_load)
        monkeypatch.setattr(adv, "run_strategy_backtest", lambda n=90: [_bt("SB", 0.62, 30)])
        monkeypatch.setattr(adv, "match_strategies", lambda code, gene: [_sig(code, "SB")])
        from limitup_screener import data as ldata
        monkeypatch.setattr(ldata, "get_db", lambda: _stale_db_conn(stale_date)())

        items = adv.advise_recommendations(limit=10)

        assert len(items) == 1
        item = items[0]
        # extra 注入 gene_data_date / data_stale
        assert item.extra["gene_data_date"] == stale_date
        assert item.extra["data_stale"] is True
        # risk_notes 含「非今日」如实呈现
        assert any("非今日" in n and stale_date in n for n in item.risk_notes)
        # binary 标注不降级仓位/win_rate（阈值留待回溯）
        assert item.win_rate == 0.62
        assert item.extra["suggested_pct"] == 0.15

    def test_today_data_not_stale(self, monkeypatch):
        """今日有 gene_scores → data_stale=False，无「非今日」risk_note。"""
        today = datetime.now().strftime("%Y-%m-%d")

        monkeypatch.setattr(adv, "load_gene_scores",
                            lambda d: [_gene("600519", 80, date=today)])
        monkeypatch.setattr(adv, "run_strategy_backtest", lambda n=90: [_bt("SB", 0.62, 30)])
        monkeypatch.setattr(adv, "match_strategies", lambda code, gene: [_sig(code, "SB")])

        items = adv.advise_recommendations(limit=10)
        assert len(items) == 1
        item = items[0]
        assert item.extra["gene_data_date"] == today
        assert item.extra["data_stale"] is False
        assert not any("非今日" in n for n in item.risk_notes)

    def test_no_data_empty_date_not_stale(self, monkeypatch):
        """不臆造：无 date（无 scores + DB 无 latest）→ gene_data_date="" / data_stale=False。"""
        monkeypatch.setattr(adv, "load_gene_scores", lambda d: [])
        from limitup_screener import data as ldata

        class _Cursor:
            def fetchone(self):
                return None  # DB 无 latest

        class _Conn:
            def execute(self, *a, **kw):
                return _Cursor()

            def close(self):
                pass

        monkeypatch.setattr(ldata, "get_db", lambda: _Conn())

        # recommendations 空 gene_map 早返 []，无 item 可验；改测 watchlist no_signal 标注
        # （见 TestWatchlistStaleAnnotation）——这里仅验 _latest_gene_map 口径
        gene_map, data_date, data_stale = adv._latest_gene_map()
        assert gene_map == {}
        assert data_date == ""
        assert data_stale is False


# ===========================================================================
# advise_watchlist —— no_signal 项也如实标注
# ===========================================================================

class TestWatchlistStaleAnnotation:
    def test_no_signal_item_annotated_when_stale(self, monkeypatch):
        """stale 回退时，no_signal 项也标 gene_data_date/data_stale（如实：池非今日）。"""
        stale_date = "2026-08-17"
        today = datetime.now().strftime("%Y-%m-%d")
        assert stale_date != today

        def _fake_load(d):
            if d == stale_date:
                return [_gene("000001", 75, date=stale_date)]
            return []

        monkeypatch.setattr(adv, "load_gene_scores", _fake_load)
        monkeypatch.setattr(adv, "run_strategy_backtest", lambda n=90: [_bt("SB", 0.62, 30)])
        monkeypatch.setattr(adv, "match_strategies",
                            lambda code, gene: [_sig(code, "SB")] if code == "000001" else [])
        import routers.watchlist as wl
        monkeypatch.setattr(wl, "watchlist_get", lambda: {"codes": ["000001", "600519"]})
        from limitup_screener import data as ldata
        monkeypatch.setattr(ldata, "get_db", lambda: _stale_db_conn(stale_date)())

        items = adv.advise_watchlist()
        by_code = {i.code: i for i in items}
        # 600519 不在 stale 池 → no_signal，但仍标 stale（池本身非今日）
        ns = by_code["600519"]
        assert ns.action == "no_signal"
        assert ns.extra["gene_data_date"] == stale_date
        assert ns.extra["data_stale"] is True
        assert any("非今日" in n and stale_date in n for n in ns.risk_notes)
        # 000001 enter 项同样标 stale
        enter = by_code["000001"]
        assert enter.extra["gene_data_date"] == stale_date
        assert enter.extra["data_stale"] is True


# ===========================================================================
# advise_holdings —— 第三消费方接线
# ===========================================================================

class TestHoldingsStaleAnnotation:
    @staticmethod
    def _h(code: str, pnl_pct: float, cost: float = 10.0, price: float = 10.0) -> dict:
        return {"code": code, "name": code, "price": price, "shares": 100,
                "cost": cost, "pnl_pct": pnl_pct}

    def test_stale_fallback_annotates_holding_item(self, monkeypatch):
        """stale 回退时，持仓项也标 gene_data_date/data_stale。"""
        stale_date = "2026-08-17"
        today = datetime.now().strftime("%Y-%m-%d")
        assert stale_date != today

        monkeypatch.setattr(adv, "STRATEGY_REGISTRY", [
            {"code": "SB", "name": "首板", "stop_loss_pct": -3, "take_profit_pct": 15, "max_hold_days": 3},
        ])

        def _fake_load(d):
            if d == stale_date:
                return [_gene("000001", 70, date=stale_date)]
            return []

        monkeypatch.setattr(adv, "load_gene_scores", _fake_load)
        monkeypatch.setattr(adv, "run_strategy_backtest", lambda n=90: [_bt("SB", 0.62, 30)])
        monkeypatch.setattr(adv, "match_strategies", lambda code, gene: [_sig(code, "SB")])
        from limitup_screener import data as ldata
        # _latest_gene_map 回退用 fetchone；层1全命中不查 fetchall
        monkeypatch.setattr(ldata, "get_db", lambda: _stale_db_conn(stale_date)())
        monkeypatch.setattr(adv, "_atr_trailing_stop", lambda code, cost, sfp=None: (None, None, False))

        import portfolio as pf

        async def _pf():
            return {"holdings": [self._h("000001", 5.0)]}

        monkeypatch.setattr(pf, "get_portfolio", _pf)

        items = asyncio.run(adv.advise_holdings())
        assert len(items) == 1
        item = items[0]
        assert item.extra["gene_data_date"] == stale_date
        assert item.extra["data_stale"] is True
        assert any("非今日" in n and stale_date in n for n in item.risk_notes)
        # binary 标注不降级 layer/win_rate
        assert item.extra["layer"] == 1
        assert item.win_rate == 0.62
