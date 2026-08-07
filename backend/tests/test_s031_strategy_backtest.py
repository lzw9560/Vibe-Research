# -*- coding: utf-8 -*-
"""S031 T22：按战法回测引擎单测。

mock DB gene_scores + K 线 → 验证 8 战法聚合 win_rate/avg_return/sample_size +
K 线缺失跳过 + 端点 shape。不联网（mootdx/astock 全 mock）。
"""

from types import SimpleNamespace
from unittest.mock import patch

from limitup_screener.models import GeneScore


def _gene_matching_first_plate():
    """构造一个只命中 first_plate 的 GeneScore（其余 7 战法条件均不满足）。"""
    return GeneScore(
        code="000001", name="X", total_score=62.0,
        factors={"次日溢价率": 40, "红盘率": 50, "封板率": 30, "炸板后溢价": 0, "涨停频次": 25},
        wilson_adjusted=60.0, qualify=True, high_gene=False, last_zt_dates=[], zt_count_250d=1,
    )


def _bars_with_profit_on_day1():
    """K 线：2026-08-01 为信号日，次日开盘 10.5 入场，当日 high=11.5 触发 +8% 止盈。"""
    return [
        SimpleNamespace(date="2026-08-01", open=10, high=11, low=9.5, close=10.5),
        SimpleNamespace(date="2026-08-02", open=10.5, high=11.5, low=10.5, close=11),
        SimpleNamespace(date="2026-08-03", open=11, high=12, low=10.5, close=11.5),
    ]


@patch("strategies.strategy_backtest.astock")
@patch("strategies.strategy_backtest.kline_from_mootdx")
@patch("strategies.strategy_backtest.load_gene_scores")
@patch("strategies.strategy_backtest._get_available_dates")
def test_run_strategy_backtest_aggregates(mock_dates, mock_load, mock_kline_mapper, _mock_astock):
    """8 战法各返结果；命中的 first_plate win_rate=1.0/avg_return=8.0；其余 sample_size=0。"""
    from strategies.strategy_backtest import run_strategy_backtest, clear_cache
    clear_cache()
    mock_dates.return_value = ["2026-08-01"]
    mock_load.return_value = [_gene_matching_first_plate()]
    mock_kline_mapper.return_value = SimpleNamespace(bars=_bars_with_profit_on_day1())

    results = run_strategy_backtest(60)

    assert len(results) == 8
    assert all(r.available_days == 1 for r in results)  # DB 实际可用天数
    first_plate = next(r for r in results if r.strategy_code == "first_plate")
    assert first_plate.sample_size == 1
    assert first_plate.win_rate == 1.0  # 1/1
    assert first_plate.avg_return == 8.0  # take_profit_pct=8
    others = [r for r in results if r.strategy_code != "first_plate"]
    assert all(r.sample_size == 0 for r in others), "其余 7 战法不应命中"


@patch("strategies.strategy_backtest.astock")
@patch("strategies.strategy_backtest.kline_from_mootdx")
@patch("strategies.strategy_backtest.load_gene_scores")
@patch("strategies.strategy_backtest._get_available_dates")
def test_run_strategy_backtest_skips_missing_kline(mock_dates, mock_load, mock_kline_mapper, _mock_astock):
    """K 线缺失（bars 空）→ 该笔跳过，sample_size=0、skipped 计数。"""
    from strategies.strategy_backtest import run_strategy_backtest, clear_cache
    clear_cache()
    mock_dates.return_value = ["2026-08-01"]
    mock_load.return_value = [_gene_matching_first_plate()]
    mock_kline_mapper.return_value = SimpleNamespace(bars=[])

    results = run_strategy_backtest(60)
    first_plate = next(r for r in results if r.strategy_code == "first_plate")
    assert first_plate.sample_size == 0
    assert first_plate.skipped == 1  # 命中但因无 K 线跳过


def test_backtest_endpoint_returns_8_strategies(monkeypatch):
    """GET /api/strategy/backtest 返 8 战法 + available_days + disclaimer。"""
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    from routers import strategy as strat_router
    from strategies.strategy_backtest import StrategyBacktestResult

    fake = [
        StrategyBacktestResult(
            strategy_code=f"s{i}", strategy_name=f"战法{i}",
            win_rate=0.5, avg_return=1.0, sample_size=10, available_days=8,
        )
        for i in range(8)
    ]
    monkeypatch.setattr("strategies.strategy_backtest.run_strategy_backtest", lambda lookback_days: fake)

    app = FastAPI()
    app.include_router(strat_router.router)
    client = TestClient(app)

    resp = client.get("/api/strategy/backtest?lookback_days=60")
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert len(body["data"]) == 8
    assert body["available_days"] == 8
    assert "历史统计特征" in body["disclaimer"]
    assert body["data"][0]["strategy_code"] == "s0"
    assert body["data"][0]["win_rate"] == 0.5
