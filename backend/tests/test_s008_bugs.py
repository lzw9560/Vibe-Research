"""S008 阶段 0 — 5 个静默 bug 回归测（全离线）。

覆盖：
- R5 risk_models._calculate_* 用 astock.kline（非 get_kline），返回非 0 真实值
- R6 limitup_screener/data.py 可 import datetime（模块导入不报错）
- R7 chat.SYSTEM_PROMPT_NO_TOOLS 全模块仅一处赋值
- R8 limitup_screener/models.py 不 import astock（模型不依赖数据源）
- R9 seat_engine SeatProfile 两实例 set 不共享
"""
import asyncio
import inspect
import textwrap

import pytest


# ── R5: risk_models 调 astock.kline，三指标对 mock 数据非 0 ───────────────

def test_risk_models_uses_kline_not_get_kline():
    """源码中 _calculate_* 调 astock.kline（offset=），不出现 get_kline。"""
    import risk_models
    src = inspect.getsource(risk_models)
    assert "get_kline" not in src, "risk_models 仍引用 get_kline（应为 kline）"
    assert "astock.kline(code, offset=" in src, "risk_models 应调 astock.kline(code, offset=...)"


def _fake_bars(n=30, base=10.0):
    """生成 n 根递增收盘的 mock kline（带 close/amount）。"""
    bars = []
    price = base
    for i in range(n):
        price *= 1.005  # 每日 +0.5%
        bars.append({"close": round(price, 2), "amount": 60_000_000})
    return bars


def test_risk_models_volatility_nonzero(monkeypatch):
    import astock
    import risk_models
    monkeypatch.setattr(astock, "kline", lambda code, offset=60: _fake_bars(30, 10.0))
    v = asyncio.run(risk_models._calculate_volatility("600519", window=20))
    assert v > 0, f"波动率应为正（mock 递增序列），得 {v}"


def test_risk_models_max_drawdown_nonzero(monkeypatch):
    import astock
    import risk_models
    # 先涨后跌序列：制造回撤
    bars = [{"close": 10.0, "amount": 60_000_000}] + [
        {"close": round(10.0 * (1.01 ** i), 2), "amount": 60_000_000} for i in range(1, 40)
    ] + [{"close": round(10.0 * (1.01 ** 39) * 0.85, 2), "amount": 60_000_000}]  # 回撤 15%
    monkeypatch.setattr(astock, "kline", lambda code, offset=60: bars)
    dd = asyncio.run(risk_models._calculate_max_drawdown("600519", window=60))
    assert dd > 0, f"最大回撤应为正，得 {dd}"


def test_risk_models_liquidity_nonzero(monkeypatch):
    """成交额 < 5000 万 → 流动性风险 > 0；成交额充足 → 0。"""
    import astock
    import risk_models
    monkeypatch.setattr(astock, "kline", lambda code, offset=20: _fake_bars(20, 10.0))
    # mock amount=60M > 50M 阈值 → 流动性风险 0（充足）
    risk = asyncio.run(risk_models._calculate_liquidity_risk("600519"))
    assert risk == 0.0, f"成交额充足应无流动性风险，得 {risk}"
    # 低成交额 → 风险 > 0
    low = [{"close": 10.0, "amount": 10_000_000} for _ in range(20)]
    monkeypatch.setattr(astock, "kline", lambda code, offset=20: low)
    risk2 = asyncio.run(risk_models._calculate_liquidity_risk("600519"))
    assert risk2 > 0, f"低成交额应有流动性风险，得 {risk2}"


# ── R6: limitup_screener/data.py 可导入 ──────────────────────────────────

def test_limitup_screener_data_imports_datetime():
    """模块应可正常导入（datetime 已补 import）。"""
    import importlib
    mod = importlib.import_module("limitup_screener.data")
    src = inspect.getsource(mod)
    assert "from datetime import" in src or "import datetime" in src, "data.py 应导入 datetime"


# ── R7: chat.SYSTEM_PROMPT_NO_TOOLS 仅一处赋值 ───────────────────────────

def test_chat_prompt_no_dup():
    import chat
    src = inspect.getsource(chat)
    # 统计顶层赋值次数（去除字符串内出现的同名文本）
    count = src.count("SYSTEM_PROMPT_NO_TOOLS = ")
    assert count == 1, f"SYSTEM_PROMPT_NO_TOOLS 应仅一处赋值，实际 {count}"
    # 变量可访问
    assert hasattr(chat, "SYSTEM_PROMPT_NO_TOOLS")
    assert "投研助理" in chat.SYSTEM_PROMPT_NO_TOOLS


# ── R8: limitup_screener/models.py 不 import astock ──────────────────────

def test_limitup_models_no_astock_import():
    import limitup_screener.models as m
    src = inspect.getsource(m)
    # 不应有顶层 import astock
    for line in src.splitlines():
        s = line.strip()
        if s.startswith("import astock") or s.startswith("from astock"):
            pytest.fail(f"models.py 不应依赖 astock：{line}")
    # _numf 已内联
    assert hasattr(m, "_numf")
    assert m._numf(1.5) == 1.5
    assert m._numf("-") is None  # 停牌/无数据 → None
    assert m._numf("abc") is None


# ── R9: seat_engine SeatProfile 实例间 set 不共享 ─────────────────────────

def test_seat_engine_defaults_not_shared():
    from seat_engine.models import SeatProfile
    a = SeatProfile(seat_name="A")
    b = SeatProfile(seat_name="B")
    a._stocks_traded.add("600519")
    a._stock_buy_sell_pairs.add(("600519", "A"))
    assert "600519" not in b._stocks_traded, "两实例不应共享 _stocks_traded"
    assert ("600519", "A") not in b._stock_buy_sell_pairs, "两实例不应共享 _stock_buy_sell_pairs"
    assert a._buy_appearances == 0 and b._buy_appearances == 0
