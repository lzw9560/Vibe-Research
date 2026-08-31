# -*- coding: utf-8 -*-
"""S129：risk 三子维度（volatility/max_drawdown/liquidity_risk）provenance 诚实化。

锁住（spec §3 R1.4/R2.3/R3.5）：
- R1.4：三 _meta sibling 返 (float, data_status)——成功→ok、except→missing、
  bar 不足→degraded、liquidity 合法零→ok；原函数向后兼容仍返 float。
- R2.3：_merge_data_status 含 trio——全 missing→missing、一 degraded→degraded、全 ok→ok。
- R3.5：_build_risk_factors 消费 trio status——失败维度显"数据缺失"非"较少"；
  ok+超阈→原文本不破。

mock 复用 test_s008_t13b_kline 的 astock.kline monkeypatch 范式（raw bars 喂
kline_from_mootdx，部分 bar 仅 close+amount 即可）。不依赖 live 取数。
"""
import asyncio

import astock
import risk_models


def _partial_bars(n: int = 25, close: float = 10.0, amount: float = 60_000_000) -> list[dict]:
    """部分 bar（仅 close+amount，仿 test_s008_t13b_kline._partial_bars）。

    round 引入微小方差 → 波动率 variance>0（test_s008 同款用法）。
    """
    return [{"close": round(close * (1.005 ** i), 2), "amount": amount} for i in range(n)]


def _drawdown_bars() -> list[dict]:
    """先涨后跌 15% 的 bar（仿 test_s008 max_drawdown 用例）→ max_dd>0。"""
    return [{"close": 10.0, "amount": 60_000_000}] + [
        {"close": round(10.0 * (1.01 ** i), 2), "amount": 60_000_000} for i in range(1, 40)
    ] + [{"close": round(10.0 * (1.01 ** 39) * 0.85, 2), "amount": 60_000_000}]


# ── R1.4：trio _meta sibling ──────────────────────────────────────────────

def test_r1_trio_meta_success_returns_value_ok(monkeypatch):
    # Arrange：vol 30 根 bar（round→variance>0）；dd 先涨后跌；liquidity 低成交额→risk>0
    monkeypatch.setattr(astock, "kline", lambda code, offset=30: _partial_bars(30, 10.0))
    # Act + Assert：volatility _meta 成功 → (value>0, "ok")
    vol_val, vol_st = asyncio.run(risk_models._calculate_volatility_meta("600519", window=20))
    assert vol_val > 0 and vol_st == "ok"

    # Arrange：max_drawdown 先涨后跌 → max_dd>0
    monkeypatch.setattr(astock, "kline", lambda code, offset=70: _drawdown_bars())
    # Act + Assert
    dd_val, dd_st = asyncio.run(risk_models._calculate_max_drawdown_meta("600519", window=60))
    assert dd_val > 0 and dd_st == "ok"

    # Arrange：liquidity 低成交额（10M < 50M）→ 非零风险
    low = [{"close": 10.0, "amount": 10_000_000} for _ in range(20)]
    monkeypatch.setattr(astock, "kline", lambda code, offset=20: low)
    # Act + Assert
    liq_val, liq_st = asyncio.run(risk_models._calculate_liquidity_risk_meta("600519"))
    assert liq_val > 0 and liq_st == "ok"


def test_r1_trio_meta_exception_returns_missing(monkeypatch):
    # Arrange：astock.kline 抛 KeyError（trio except 块捕获 KeyError/ValueError/TypeError/AttributeError）
    def _raise(code, offset=30):
        raise KeyError("boom")
    monkeypatch.setattr(astock, "kline", _raise)
    # Act + Assert：三 _meta 均 (0.0, "missing")
    vol_val, vol_st = asyncio.run(risk_models._calculate_volatility_meta("600519", window=20))
    assert (vol_val, vol_st) == (0.0, "missing")
    dd_val, dd_st = asyncio.run(risk_models._calculate_max_drawdown_meta("600519", window=60))
    assert (dd_val, dd_st) == (0.0, "missing")
    liq_val, liq_st = asyncio.run(risk_models._calculate_liquidity_risk_meta("600519"))
    assert (liq_val, liq_st) == (0.0, "missing")


def test_r1_trio_meta_bar_insufficient_returns_degraded(monkeypatch):
    # Arrange：vol/dd 返 1 根 bar（len(closes)<2）；liquity 返 0 根 bar（not amounts）
    monkeypatch.setattr(astock, "kline", lambda code, offset=30: [{"close": 10.0, "amount": 60_000_000}])
    # Act + Assert：volatility/max_drawdown bar 不足 → (0.0, "degraded")
    vol_val, vol_st = asyncio.run(risk_models._calculate_volatility_meta("600519", window=20))
    assert (vol_val, vol_st) == (0.0, "degraded")
    dd_val, dd_st = asyncio.run(risk_models._calculate_max_drawdown_meta("600519", window=60))
    assert (dd_val, dd_st) == (0.0, "degraded")

    # Arrange：liquidity 返 0 根 bar → amounts=[] → not amounts
    monkeypatch.setattr(astock, "kline", lambda code, offset=20: [])
    # Act + Assert
    liq_val, liq_st = asyncio.run(risk_models._calculate_liquidity_risk_meta("600519"))
    assert (liq_val, liq_st) == (0.0, "degraded")


def test_r1_liquidity_meta_legit_zero_returns_ok(monkeypatch):
    # Arrange：avg_amount=60M >= 50M → 高流动性合法零（非断源）
    monkeypatch.setattr(astock, "kline", lambda code, offset=20: _partial_bars(20, 10.0, 60_000_000))
    # Act
    value, status = asyncio.run(risk_models._calculate_liquidity_risk_meta("600519"))
    # Assert：合法零仍标 ok（不撒谎）
    assert value == 0.0
    assert status == "ok"


def test_r1_backward_compat_original_trio_return_float(monkeypatch):
    # Arrange + Act + Assert：原函数改调 _meta 后仍返 float（非 tuple），签名不变
    monkeypatch.setattr(astock, "kline", lambda code, offset=30: _partial_bars(30, 10.0))
    vol = asyncio.run(risk_models._calculate_volatility("600519", window=20))
    assert isinstance(vol, float)

    monkeypatch.setattr(astock, "kline", lambda code, offset=70: _drawdown_bars())
    dd = asyncio.run(risk_models._calculate_max_drawdown("600519", window=60))
    assert isinstance(dd, float)

    monkeypatch.setattr(astock, "kline", lambda code, offset=20: _partial_bars(20, 10.0, 60_000_000))
    liq = asyncio.run(risk_models._calculate_liquidity_risk("600519"))
    assert isinstance(liq, float)


# ── R2.3：_merge_data_status 含 trio ──────────────────────────────────────

def test_r2_merge_data_status_trio_all_missing():
    # Arrange：base/cf/dt/seat/conc 全 ok，trio 全 missing
    # Act
    status = risk_models._merge_data_status(
        "ok", "ok", "ok", "ok", "ok", "missing", "missing", "missing"
    )
    # Assert：trio 全失败抬 data_status=missing
    assert status == "missing"


def test_r2_merge_data_status_trio_one_degraded_rest_ok():
    # Arrange：仅 vol degraded，其余（含 dd/liq）ok
    # Act
    status = risk_models._merge_data_status(
        "ok", "ok", "ok", "ok", "ok", "degraded", "ok", "ok"
    )
    # Assert：单 degraded 抬 data_status=degraded
    assert status == "degraded"


def test_r2_merge_data_status_trio_all_ok():
    # Arrange：全 ok（含 trio 三态）
    # Act
    status = risk_models._merge_data_status(
        "ok", "ok", "ok", "ok", "ok", "ok", "ok", "ok"
    )
    # Assert
    assert status == "ok"


# ── R3.5：_build_risk_factors 消费 trio status ───────────────────────────

def test_r3_build_risk_factors_trio_all_missing_shows_data_missing():
    # Arrange：trio 全 missing，值全 0（失败降级）；其余维度无风险触发
    # Act
    factors, _rec = risk_models._build_risk_factors(
        dynamic_score=50.0, risk_level="LOW",
        dragon_tiger_risk=0.0, volatility=0.0, max_drawdown=0.0,
        liquidity_risk=0.0, concentration_risk=0.0,
        capital_flow_trend="平衡", multi_seat_signal=False,
        vol_status="missing", dd_status="missing", liq_status="missing",
    )
    # Assert：三"数据缺失"均显，且不显"当前风险因素较少"（factors 非空）
    assert "波动率数据缺失" in factors
    assert "回撤数据缺失" in factors
    assert "流动性数据缺失" in factors
    assert "当前风险因素较少" not in factors


def test_r3_build_risk_factors_single_degraded_shows_corresponding_missing():
    # Arrange：仅 vol degraded（dd/liq ok），值全 0
    # Act
    factors, _rec = risk_models._build_risk_factors(
        dynamic_score=50.0, risk_level="LOW",
        dragon_tiger_risk=0.0, volatility=0.0, max_drawdown=0.0,
        liquidity_risk=0.0, concentration_risk=0.0,
        capital_flow_trend="平衡", multi_seat_signal=False,
        vol_status="degraded", dd_status="ok", liq_status="ok",
    )
    # Assert：仅波动率维度显"数据缺失"，其余两维不显（corresponding 映射）
    assert "波动率数据缺失" in factors
    assert "回撤数据缺失" not in factors
    assert "流动性数据缺失" not in factors


def test_r3_build_risk_factors_trio_ok_high_volatility_preserves_original():
    # Arrange：trio 全 ok，volatility=6.0>5 → 原行为"波动率偏高"
    # Act
    factors, _rec = risk_models._build_risk_factors(
        dynamic_score=50.0, risk_level="MEDIUM",
        dragon_tiger_risk=0.0, volatility=6.0, max_drawdown=0.0,
        liquidity_risk=0.0, concentration_risk=0.0,
        capital_flow_trend="平衡", multi_seat_signal=False,
        vol_status="ok", dd_status="ok", liq_status="ok",
    )
    # Assert：显"波动率偏高"（原文本不破），不显任何"数据缺失"
    assert any("波动率偏高" in f for f in factors)
    assert not any("数据缺失" in f for f in factors)
