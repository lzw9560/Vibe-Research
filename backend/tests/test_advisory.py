# -*- coding: utf-8 -*-
"""S042 统一持仓建议引擎 v2 测试。

mock strategy_backtest / load_gene_scores / match_strategies / portfolio /
watchlist，验证三场景建议逻辑 + D2 持仓规则各分支。离线（-m "not live"）。
"""
import asyncio
from types import SimpleNamespace

from strategies import position_advisor_v2 as adv


def _gene(code: str, score: float = 70, name: str = "X") -> SimpleNamespace:
    return SimpleNamespace(code=code, name=name, total_score=score, factors={})


def _sig(code: str, strategy_code: str = "SB", strategy_name: str = "首板挖掘") -> SimpleNamespace:
    return SimpleNamespace(code=code, strategy_code=strategy_code, strategy_name=strategy_name)


def _bt(strategy_code: str = "SB", win_rate: float = 0.62,
        sample_size: int = 30, strategy_name: str = "首板挖掘") -> SimpleNamespace:
    return SimpleNamespace(strategy_code=strategy_code, win_rate=win_rate,
                           sample_size=sample_size, strategy_name=strategy_name)


class TestHoldingActionD2:
    """D2 持仓规则表（纯函数 _holding_action，覆盖各分支）。"""

    def test_触及止损_弱胜率_close(self):
        assert adv._holding_action(-4.0, 0.3, -3.0)[0] == "close"

    def test_触及止损_强胜率_hold(self):
        assert adv._holding_action(-4.0, 0.55, -3.0)[0] == "hold"

    def test_盈利_弱胜率_reduce(self):
        assert adv._holding_action(8.0, 0.3, -7.0)[0] == "reduce"

    def test_盈利_强胜率_hold(self):
        assert adv._holding_action(8.0, 0.65, -7.0)[0] == "hold"

    def test_亏损未触止损_弱胜率_close(self):
        assert adv._holding_action(-3.5, 0.3, -7.0)[0] == "close"

    def test_亏损未触止损_强胜率_hold(self):
        assert adv._holding_action(-3.5, 0.55, -7.0)[0] == "hold"

    def test_中性_弱胜率_reduce(self):
        assert adv._holding_action(0.0, 0.3, -7.0)[0] == "reduce"

    def test_中性_强胜率_hold(self):
        assert adv._holding_action(0.0, 0.55, -7.0)[0] == "hold"

    def test_无胜率_中性_hold(self):
        assert adv._holding_action(0.0, None, -7.0)[0] == "hold"

    def test_无胜率_触止损_close(self):
        assert adv._holding_action(-4.0, None, -3.0)[0] == "close"


class TestAdviseRecommendations:
    def test_输出入场建议_win_rate_backtest(self, monkeypatch):
        monkeypatch.setattr(adv, "load_gene_scores",
                            lambda d: [_gene("000001", 75), _gene("600519", 80)])
        monkeypatch.setattr(adv, "run_strategy_backtest", lambda n=90: [_bt("SB", 0.62, 30)])
        monkeypatch.setattr(adv, "match_strategies",
                            lambda code, gene: [_sig(code, "SB")])
        items = adv.advise_recommendations(limit=10)
        assert len(items) == 2
        # 按 total_score 降序 → 600519(80) 在前
        assert items[0].code == "600519"
        assert items[0].action == "enter"
        assert items[0].win_rate == 0.62
        assert items[0].win_rate_source == "backtest_90d"
        assert items[0].extra["suggested_pct"] == 0.15  # win_rate>=0.6 → 15%
        assert items[0].extra["gene_score"] == 80

    def test_弱胜率_仓位10pct(self, monkeypatch):
        monkeypatch.setattr(adv, "load_gene_scores", lambda d: [_gene("000001", 75)])
        monkeypatch.setattr(adv, "run_strategy_backtest", lambda n=90: [_bt("SB", 0.45, 20)])
        monkeypatch.setattr(adv, "match_strategies", lambda code, gene: [_sig(code, "SB")])
        items = adv.advise_recommendations()
        assert items[0].extra["suggested_pct"] == 0.10  # 0.4-0.6 → 10%

    def test_空gene返空(self, monkeypatch):
        monkeypatch.setattr(adv, "load_gene_scores", lambda d: [])
        assert adv.advise_recommendations() == []


class TestAdviseWatchlist:
    def test_有信号_无信号并存(self, monkeypatch):
        monkeypatch.setattr(adv, "load_gene_scores", lambda d: [_gene("000001", 75)])
        monkeypatch.setattr(adv, "run_strategy_backtest", lambda n=90: [_bt("SB", 0.62, 30)])
        monkeypatch.setattr(adv, "match_strategies",
                            lambda code, gene: [_sig(code, "SB")] if code == "000001" else [])
        import routers.watchlist as wl
        monkeypatch.setattr(wl, "watchlist_get", lambda: {"codes": ["000001", "600519"]})
        items = adv.advise_watchlist()
        assert len(items) == 2
        by_code = {i.code: i for i in items}
        assert by_code["000001"].action == "enter"
        assert by_code["000001"].win_rate_source == "backtest_90d"
        assert by_code["600519"].action == "no_signal"
        assert by_code["600519"].win_rate_source == "none"

    def test_空自选返空(self, monkeypatch):
        import routers.watchlist as wl
        monkeypatch.setattr(wl, "watchlist_get", lambda: {"codes": []})
        assert adv.advise_watchlist() == []


class TestAdviseHoldings:
    @staticmethod
    def _h(code: str, pnl_pct: float, cost: float = 10.0, price: float = 10.0) -> dict:
        return {"code": code, "name": code, "price": price, "shares": 100,
                "cost": cost, "pnl_pct": pnl_pct}

    def _setup_holdings(self, monkeypatch):
        monkeypatch.setattr(adv, "STRATEGY_REGISTRY", [
            {"code": "SB", "name": "首板", "stop_loss_pct": -3, "take_profit_pct": 15, "max_hold_days": 3},
            {"code": "LB", "name": "连板", "stop_loss_pct": -3, "take_profit_pct": 15, "max_hold_days": 3},
        ])
        monkeypatch.setattr(adv, "load_gene_scores",
                            lambda d: [_gene("000001"), _gene("000002"), _gene("000003")])
        monkeypatch.setattr(adv, "run_strategy_backtest",
                            lambda n=90: [_bt("SB", 0.62, 30), _bt("LB", 0.30, 30)])

        def _match(code, gene):
            if code == "000001":
                return [_sig(code, "SB")]
            if code == "000002":
                return [_sig(code, "LB")]
            return []  # 000003 无战法

        monkeypatch.setattr(adv, "match_strategies", _match)

    def test_持仓三态_hold_close_无战法(self, monkeypatch):
        self._setup_holdings(monkeypatch)
        import portfolio as pf

        async def _pf():
            return {"holdings": [
                self._h("000001", 8.0),    # 强胜率盈利 → hold
                self._h("000002", -4.0),   # 弱胜率触止损 → close
                self._h("000003", 0.0),    # 无战法中性 → hold
            ]}

        monkeypatch.setattr(pf, "get_portfolio", _pf)
        items = asyncio.run(adv.advise_holdings())
        by_code = {i.code: i for i in items}
        assert by_code["000001"].action == "hold"
        assert by_code["000001"].win_rate == 0.62
        assert by_code["000002"].action == "close"
        assert by_code["000002"].win_rate == 0.30
        assert by_code["000003"].action == "hold"
        assert by_code["000003"].win_rate_source == "none"
        assert by_code["000003"].matched_strategy is None

    def test_空持仓返空(self, monkeypatch):
        monkeypatch.setattr(adv, "load_gene_scores", lambda d: [])
        import portfolio as pf

        async def _pf():
            return {"holdings": []}

        monkeypatch.setattr(pf, "get_portfolio", _pf)
        assert asyncio.run(adv.advise_holdings()) == []


class TestAdvisorySummary:
    def test_三场景汇总_免责(self, monkeypatch):
        monkeypatch.setattr(adv, "load_gene_scores", lambda d: [_gene("000001", 75)])
        monkeypatch.setattr(adv, "run_strategy_backtest", lambda n=90: [_bt("SB", 0.62, 30)])
        monkeypatch.setattr(adv, "match_strategies", lambda code, gene: [_sig(code, "SB")])
        import routers.watchlist as wl
        monkeypatch.setattr(wl, "watchlist_get", lambda: {"codes": ["000001"]})
        import portfolio as pf

        async def _pf():
            return {"holdings": [TestAdviseHoldings._h("000001", 8.0)]}

        monkeypatch.setattr(pf, "get_portfolio", _pf)
        summary = asyncio.run(adv.advisory_summary(limit=10))
        assert set(summary.keys()) == {"recommendations", "watchlist", "holdings", "disclaimer"}
        assert summary["disclaimer"] == adv._DISCLAIMER
        assert summary["recommendations"][0]["scene"] == "recommendation"
        assert summary["watchlist"][0]["scene"] == "watchlist"
        assert summary["holdings"][0]["scene"] == "holding"
        # 每条挂免责
        for scene in ("recommendations", "watchlist", "holdings"):
            for item in summary[scene]:
                assert item["disclaimer"] == adv._DISCLAIMER
