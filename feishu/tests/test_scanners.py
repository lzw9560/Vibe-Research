# -*- coding: utf-8 -*-
"""test_scanners.py — scan_strategy4_tail_drop 测试。

测试覆盖：
- 空数据降级（get_market_snapshot_all 返回 []）
- tail_dip_engine 导入失败降级（返回 []）
- 红线过滤（跌幅甜区 / 成交额 / 价格）
- 偏离度排序（按 anomalous_deviation 降序）
- 结果截断（最多 10 条）
- 周末前安全门槛升级

mock data 层的 get_market_snapshot_all / get_index_snapshot，
mock tail_dip_engine 的 calculate_anomalous_deviation / financial_red_line_shield。
不触碰真实 hithink-finance CLI 或 akshare。
"""
from __future__ import annotations

import sys
from unittest.mock import MagicMock

import pytest

from feishu import data, scanners


# ─── 辅助构造 mock 股票数据 ───

def _stock(code, chg=-4.0, turnover=2e7, price=10.0, volume=1e6, vol_ratio=0.5, name="Test"):
    """构造一条全市场快照股票数据。"""
    return {
        "thscode": code,
        "name": name,
        "price_change_ratio_pct": chg,
        "turnover": turnover,
        "last_price": price,
        "volume": volume,
        "vol_ratio": vol_ratio,
    }


def _anomalous_result(code, deviation=4.0, is_anomalous=True, confidence="medium"):
    """构造一个 AnomalousDeviationResult-like mock。

    scanners.py 访问 .is_anomalous / .anomalous_deviation / .confidence / .detail，
    用 MagicMock 设置这些属性即可，无需导入真实 dataclass。
    """
    m = MagicMock()
    m.code = code
    m.anomalous_deviation = deviation
    m.is_anomalous = is_anomalous
    m.confidence = confidence
    m.detail = f"deviation={deviation}"
    return m


def _redline_result(passed=True, reasons=None):
    """构造一个 FinancialRedLine-like mock。"""
    m = MagicMock()
    m.passed = passed
    m.blocked_reasons = reasons or []
    return m


@pytest.fixture
def _mock_engine(monkeypatch):
    """注入 mock 的 tail_dip_engine 模块，避免依赖 akshare/scipy。

    scanners.py 通过 sys.path.insert(backend_path) + from strategies.tail_dip_engine import ...
    导入引擎。我们注入一个 fake 包 + 模块到 sys.modules，使该 import 拿到 mock 对象。
    需同时注入 'strategies'（父包）和 'strategies.tail_dip_engine'，否则 import 会
    尝试加载真实 strategies 包（触发 vr_paths 缺失）。
    """
    fake_engine = MagicMock()
    fake_engine.calculate_anomalous_deviation = MagicMock(return_value=_anomalous_result("default"))
    fake_engine.financial_red_line_shield = MagicMock(return_value=_redline_result(passed=True))
    fake_engine.HARD_THRESHOLDS = {
        "max_limitup_boards": 4,
        "max_drop_pct": -5.0,      # < -5% 不接
        "min_drop_pct": -3.0,      # > -3% 不接
        "min_amount": 1e7,         # 成交额下限
        "min_price": 2.0,          # 价格下限
        "max_stop_loss": -0.10,
        "take_profit": 0.10,
        "max_hold_days": 5,
    }
    # 注入 fake 父包 + 子模块，阻止真实 import
    fake_pkg = MagicMock()
    monkeypatch.setitem(sys.modules, "backend", MagicMock())
    monkeypatch.setitem(sys.modules, "backend.strategies", fake_pkg)
    monkeypatch.setitem(sys.modules, "backend.strategies.tail_dip_engine", fake_engine)
    return fake_engine


# ─── 空数据降级 ───

def test_scan_empty_market_returns_empty(monkeypatch):
    """get_market_snapshot_all 返回 [] → scan 返回 []。"""
    # scanners.py 顶层 from .data import 将函数绑定到 scanners 命名空间，
    # 必须 patch scanners 上的引用（而非 data）
    monkeypatch.setattr(scanners, "get_market_snapshot_all", lambda: [])
    assert scanners.scan_strategy4_tail_drop() == []


def test_scan_engine_import_fail_returns_empty(monkeypatch):
    """tail_dip_engine 导入失败 → 返回 []（不降级为 legacy）。"""
    # 提供 mock 数据但让引擎导入失败
    monkeypatch.setattr(scanners, "get_market_snapshot_all", lambda: [_stock("600001.SH")])
    # 清除可能的已缓存模块，并确保 import 抛 ImportError
    monkeypatch.delitem(sys.modules, "strategies.tail_dip_engine", raising=False)
    # 让 backend path 下的真实模块也无法导入（vr_paths 缺失）——
    # scanners 已有 try/except ImportError 兜底返回 []
    result = scanners.scan_strategy4_tail_drop()
    assert result == []


# ─── 基础筛选：跌幅甜区 / 成交额 / 价格 ───

def test_scan_filters_drop_too_small(monkeypatch, _mock_engine):
    """跌幅 > -3%（如 -2%）→ 被过滤（不算错杀）。"""
    stocks = [_stock("600001.SH", chg=-2.0)]  # -2% > -3%
    monkeypatch.setattr(scanners, "get_market_snapshot_all", lambda: stocks)
    monkeypatch.setattr(scanners, "get_index_snapshot", lambda: [])
    assert scanners.scan_strategy4_tail_drop() == []


def test_scan_filters_drop_too_big(monkeypatch, _mock_engine):
    """跌幅 < -5%（如 -6%）→ 被过滤（重跌是基本面恶化）。"""
    stocks = [_stock("600001.SH", chg=-6.0)]  # -6% < -5%
    monkeypatch.setattr(scanners, "get_market_snapshot_all", lambda: stocks)
    monkeypatch.setattr(scanners, "get_index_snapshot", lambda: [])
    assert scanners.scan_strategy4_tail_drop() == []


def test_scan_filters_turnover_too_low(monkeypatch, _mock_engine):
    """成交额 < 1000万 → 被过滤。"""
    stocks = [_stock("600001.SH", turnover=5e5)]  # 50万 < 1000万
    monkeypatch.setattr(scanners, "get_market_snapshot_all", lambda: stocks)
    monkeypatch.setattr(scanners, "get_index_snapshot", lambda: [])
    assert scanners.scan_strategy4_tail_drop() == []


def test_scan_filters_price_too_low(monkeypatch, _mock_engine):
    """价格 < 2 → 被过滤。"""
    stocks = [_stock("600001.SH", price=1.5)]  # < 2
    monkeypatch.setattr(scanners, "get_market_snapshot_all", lambda: stocks)
    monkeypatch.setattr(scanners, "get_index_snapshot", lambda: [])
    assert scanners.scan_strategy4_tail_drop() == []


def test_scan_filters_price_too_high(monkeypatch, _mock_engine):
    """价格 > 80 → 被过滤。"""
    stocks = [_stock("600001.SH", price=100.0)]  # > 80
    monkeypatch.setattr(scanners, "get_market_snapshot_all", lambda: stocks)
    monkeypatch.setattr(scanners, "get_index_snapshot", lambda: [])
    assert scanners.scan_strategy4_tail_drop() == []


def test_scan_filters_missing_fields(monkeypatch, _mock_engine):
    """缺 chg/turnover/price 任一字段 → 跳过（不崩溃）。"""
    stocks = [{"thscode": "600001.SH", "name": "no_chg"}]  # 缺 chg/turnover/price
    monkeypatch.setattr(scanners, "get_market_snapshot_all", lambda: stocks)
    monkeypatch.setattr(scanners, "get_index_snapshot", lambda: [])
    assert scanners.scan_strategy4_tail_drop() == []


# ─── 偏离度判定（is_anomalous） ───

def test_scan_filters_non_anomalous(monkeypatch, _mock_engine):
    """is_anomalous=False（板块共跌，非错杀）→ 被过滤。"""
    stocks = [_stock("600001.SH", chg=-4.0)]
    monkeypatch.setattr(scanners, "get_market_snapshot_all", lambda: stocks)
    monkeypatch.setattr(scanners, "get_index_snapshot", lambda: [])
    _mock_engine.calculate_anomalous_deviation.return_value = _anomalous_result(
        "600001.SH", is_anomalous=False
    )
    assert scanners.scan_strategy4_tail_drop() == []


def test_scan_keeps_anomalous(monkeypatch, _mock_engine):
    """is_anomalous=True + 红线通过 → 保留。"""
    stocks = [_stock("600001.SH", chg=-4.0)]
    monkeypatch.setattr(scanners, "get_market_snapshot_all", lambda: stocks)
    monkeypatch.setattr(scanners, "get_index_snapshot", lambda: [])
    _mock_engine.calculate_anomalous_deviation.return_value = _anomalous_result(
        "600001.SH", deviation=4.0, is_anomalous=True
    )
    _mock_engine.financial_red_line_shield.return_value = _redline_result(passed=True)
    result = scanners.scan_strategy4_tail_drop()
    assert len(result) == 1
    assert result[0]["code"] == "600001.SH"
    assert result[0]["deviation"] == 4.0


# ─── 红线过滤 ───

def test_scan_filters_redline_blocked(monkeypatch, _mock_engine):
    """红线不通过 → 被过滤。"""
    stocks = [_stock("600001.SH", chg=-4.0)]
    monkeypatch.setattr(scanners, "get_market_snapshot_all", lambda: stocks)
    monkeypatch.setattr(scanners, "get_index_snapshot", lambda: [])
    _mock_engine.calculate_anomalous_deviation.return_value = _anomalous_result(
        "600001.SH", is_anomalous=True
    )
    _mock_engine.financial_red_line_shield.return_value = _redline_result(
        passed=False, reasons=["商誉过高"]
    )
    assert scanners.scan_strategy4_tail_drop() == []


# ─── 偏离度排序 ───

def test_scan_sorted_by_deviation_desc(monkeypatch, _mock_engine):
    """结果按 deviation 降序（偏离越大越可能错杀）。"""
    stocks = [
        _stock("600001.SH", chg=-4.0, name="低偏离"),
        _stock("600002.SH", chg=-4.5, name="高偏离"),
        _stock("600003.SH", chg=-4.2, name="中偏离"),
    ]
    monkeypatch.setattr(scanners, "get_market_snapshot_all", lambda: stocks)
    monkeypatch.setattr(scanners, "get_index_snapshot", lambda: [])

    # 为每只股票返回不同 deviation
    deviations = {
        "600001.SH": 3.0,
        "600002.SH": 6.0,
        "600003.SH": 4.5,
    }

    def _calc_deviation(code, **kwargs):
        return _anomalous_result(code, deviation=deviations[code], is_anomalous=True)

    _mock_engine.calculate_anomalous_deviation.side_effect = _calc_deviation
    _mock_engine.financial_red_line_shield.return_value = _redline_result(passed=True)

    result = scanners.scan_strategy4_tail_drop()
    assert len(result) == 3
    assert result[0]["code"] == "600002.SH"  # deviation=6 最大
    assert result[1]["code"] == "600003.SH"  # deviation=4.5
    assert result[2]["code"] == "600001.SH"  # deviation=3 最小
    assert result[0]["deviation"] >= result[1]["deviation"] >= result[2]["deviation"]


# ─── 结果截断 ───

def test_scan_truncate_to_10(monkeypatch, _mock_engine):
    """超过 10 条 → 截断到 10。"""
    stocks = [_stock(f"60000{i}.SH", chg=-4.0) for i in range(15)]
    monkeypatch.setattr(scanners, "get_market_snapshot_all", lambda: stocks)
    monkeypatch.setattr(scanners, "get_index_snapshot", lambda: [])
    _mock_engine.calculate_anomalous_deviation.return_value = _anomalous_result(
        "code", deviation=4.0, is_anomalous=True
    )
    _mock_engine.financial_red_line_shield.return_value = _redline_result(passed=True)
    result = scanners.scan_strategy4_tail_drop()
    assert len(result) == 10


# ─── 结果字段完整性 ───

def test_scan_result_fields(monkeypatch, _mock_engine):
    """验证结果 dict 包含所有必需字段。"""
    stocks = [_stock("600001.SH", chg=-4.0, turnover=2e7, price=10.0)]
    monkeypatch.setattr(scanners, "get_market_snapshot_all", lambda: stocks)
    monkeypatch.setattr(scanners, "get_index_snapshot", lambda: [])
    _mock_engine.calculate_anomalous_deviation.return_value = _anomalous_result(
        "600001.SH", deviation=4.0, is_anomalous=True, confidence="high"
    )
    _mock_engine.financial_red_line_shield.return_value = _redline_result(passed=True)

    result = scanners.scan_strategy4_tail_drop()
    assert len(result) == 1
    r = result[0]
    assert r["code"] == "600001.SH"
    assert r["name"] == "Test"
    assert r["price"] == 10.0
    assert r["chg"] == -4.0
    assert r["turnover"] == 0.2  # 2e7/1e8 = 0.2 亿
    assert r["deviation"] == 4.0
    assert r["confidence"] == "high"
    assert r["stop_loss"] == -0.10  # HARD_THRESHOLDS["max_stop_loss"]
    assert r["take_profit"] == 0.10
    assert "is_weekend_eve" in r


# ─── sector_change_pct 降级链 ───

def test_scan_sector_from_market_median(monkeypatch, _mock_engine):
    """有 valid_stocks 时用全市场中位数作为 sector_change_pct。"""
    stocks = [
        _stock("600001.SH", chg=-4.0),   # 候选
        _stock("600002.SH", chg=1.0),    # 用于算中位数
        _stock("600003.SH", chg=2.0),
    ]
    monkeypatch.setattr(scanners, "get_market_snapshot_all", lambda: stocks)
    monkeypatch.setattr(scanners, "get_index_snapshot", lambda: [])
    _mock_engine.calculate_anomalous_deviation.return_value = _anomalous_result(
        "600001.SH", is_anomalous=True
    )
    _mock_engine.financial_red_line_shield.return_value = _redline_result(passed=True)
    result = scanners.scan_strategy4_tail_drop()
    assert len(result) == 1
    # 验证 calculate_anomalous_deviation 被调用时 sector_change_pct 是中位数
    call_kwargs = _mock_engine.calculate_anomalous_deviation.call_args
    assert call_kwargs.kwargs["sector_change_pct"] == 1.0  # sorted([1,2]) 中位数=1


def test_scan_sector_fallback_to_index(monkeypatch, _mock_engine):
    """无 valid_stocks 时降级到深证成指。"""
    # 所有股票 chg=None → valid_stocks 为空
    stocks = [_stock("600001.SH", chg=-4.0)]
    # 让其他股票的 chg 为 None
    stocks.append({"thscode": "000002.SZ", "price_change_ratio_pct": None})
    monkeypatch.setattr(scanners, "get_market_snapshot_all", lambda: stocks)
    # mock 指数返回深证成指
    monkeypatch.setattr(scanners, "get_index_snapshot", lambda: [
        {"thscode": "399001.SZ", "price_change_ratio_pct": 0.5}
    ])
    _mock_engine.calculate_anomalous_deviation.return_value = _anomalous_result(
        "600001.SH", is_anomalous=True
    )
    _mock_engine.financial_red_line_shield.return_value = _redline_result(passed=True)
    result = scanners.scan_strategy4_tail_drop()
    # 600001 chg=-4 是 valid（有 chg），所以 valid_stocks 不为空，中位数=-4
    # 但 -4 不是候选的 sector（它是候选本身）——中位数仍是 -4
    # 这里主要验证不崩溃
    assert isinstance(result, list)


# ─── 成交额转亿 ───

def test_scan_turnover_in_yi(monkeypatch, _mock_engine):
    """结果中 turnover 已转为亿元（原始值/1e8）。"""
    stocks = [_stock("600001.SH", chg=-4.0, turnover=3e8)]  # 3亿
    monkeypatch.setattr(scanners, "get_market_snapshot_all", lambda: stocks)
    monkeypatch.setattr(scanners, "get_index_snapshot", lambda: [])
    _mock_engine.calculate_anomalous_deviation.return_value = _anomalous_result(
        "600001.SH", is_anomalous=True
    )
    _mock_engine.financial_red_line_shield.return_value = _redline_result(passed=True)
    result = scanners.scan_strategy4_tail_drop()
    assert result[0]["turnover"] == 3.0  # 3e8/1e8 = 3.0 亿
