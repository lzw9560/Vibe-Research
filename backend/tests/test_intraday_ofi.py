# -*- coding: utf-8 -*-
"""S176 T1 — OFI + bid_ask_pressure 纯函数测试（无 IO，纯函数）。

OFI = (Σbuy_vol - Σsell_vol) / (Σbuy_vol + Σsell_vol) ∈ [-1, 1]（归一化，跨股可比）。
bid_ask_pressure = Σbuy_vol / Σsell_vol（涨停 sell=0 → cap 999.0）。
"""
import sys
from pathlib import Path

import pytest

backend_dir = Path(__file__).resolve().parent.parent
if str(backend_dir) not in sys.path:
    sys.path.insert(0, str(backend_dir))


def _levels(vols):
    """[{level, price, vol}×5] from vol list（price 不影响 OFI，统一 10.0）。"""
    return [{"level": i + 1, "price": 10.0, "vol": v} for i, v in enumerate(vols)]


class TestOFI:
    def test_ofi_normalized_balanced_tilt(self):
        from engine.intraday_ofi import compute_ofi
        buy = _levels([100, 200, 150, 80, 50])  # Σ=580
        sell = _levels([50, 100, 75, 40, 25])   # Σ=290
        # OFI = (580-290)/(580+290) = 290/870 = 0.333
        assert compute_ofi(buy, sell) == pytest.approx(0.333, abs=0.01)

    def test_ofi_zero_when_balanced(self):
        from engine.intraday_ofi import compute_ofi
        buy = _levels([100, 100, 100, 100, 100])
        sell = _levels([100, 100, 100, 100, 100])
        assert compute_ofi(buy, sell) == pytest.approx(0.0, abs=0.01)

    def test_ofi_all_buy_no_sell_limit_up(self):
        """涨停 sell=0 → OFI=1.0（全买压）。"""
        from engine.intraday_ofi import compute_ofi
        buy = _levels([100, 200, 150, 80, 50])
        sell = _levels([0, 0, 0, 0, 0])
        assert compute_ofi(buy, sell) == pytest.approx(1.0, abs=0.01)

    def test_ofi_all_sell_no_buy(self):
        from engine.intraday_ofi import compute_ofi
        buy = _levels([0, 0, 0, 0, 0])
        sell = _levels([100, 200, 150, 80, 50])
        assert compute_ofi(buy, sell) == pytest.approx(-1.0, abs=0.01)

    def test_ofi_empty_levels(self):
        """空五档 → 0.0（不崩）。"""
        from engine.intraday_ofi import compute_ofi
        assert compute_ofi([], []) == 0.0

    def test_ofi_missing_vol_field(self):
        """vol 缺失/None → 当 0 处理（数据质量门）。"""
        from engine.intraday_ofi import compute_ofi
        buy = [{"level": 1, "price": 10.0, "vol": 100}, {"level": 2, "price": 10.0}]  # vol 缺失
        sell = [{"level": 1, "price": 10.0, "vol": 50}]
        assert compute_ofi(buy, sell) == pytest.approx(0.333, abs=0.01)  # (100-50)/150

    def test_ofi_abs(self):
        from engine.intraday_ofi import compute_ofi_abs
        buy = _levels([100, 200, 150, 80, 50])  # Σ=580
        sell = _levels([50, 100, 75, 40, 25])   # Σ=290
        assert compute_ofi_abs(buy, sell) == pytest.approx(290.0, abs=0.01)


class TestBidAskPressure:
    def test_pressure_balanced(self):
        from engine.intraday_ofi import compute_bid_ask_pressure
        buy = _levels([100, 200, 150, 80, 50])  # Σ=580
        sell = _levels([50, 100, 75, 40, 25])   # Σ=290
        assert compute_bid_ask_pressure(buy, sell) == pytest.approx(2.0, abs=0.01)  # 580/290

    def test_pressure_sell_zero_cap_limit_up(self):
        """涨停 sell=0 → pressure ∞ → cap 999.0。"""
        from engine.intraday_ofi import compute_bid_ask_pressure
        buy = _levels([100, 200, 150, 80, 50])
        sell = _levels([0, 0, 0, 0, 0])
        assert compute_bid_ask_pressure(buy, sell) == 999.0

    def test_pressure_both_zero(self):
        from engine.intraday_ofi import compute_bid_ask_pressure
        buy = _levels([0, 0, 0, 0, 0])
        sell = _levels([0, 0, 0, 0, 0])
        assert compute_bid_ask_pressure(buy, sell) == 0.0

    def test_pressure_empty(self):
        from engine.intraday_ofi import compute_bid_ask_pressure
        assert compute_bid_ask_pressure([], []) == 0.0

    def test_pressure_caps_extreme(self):
        """pressure > 999 → cap 999（极端买压）。"""
        from engine.intraday_ofi import compute_bid_ask_pressure
        buy = _levels([10000, 20000, 15000, 8000, 5000])
        sell = _levels([1, 1, 1, 1, 1])  # Σ=5 vs Σ=58000 → 11600
        assert compute_bid_ask_pressure(buy, sell) == 999.0


class TestOfiStore:
    """S176 T2 — intraday_accumulation_store extend ofi_snapshots（独立 store，不喂 trade_journal）。"""

    def test_save_and_load_ofi(self, tmp_path, monkeypatch):
        import data.intraday_accumulation_store as store
        monkeypatch.setattr(store, "_DB_PATH", str(tmp_path / "test_ofi.db"))
        from data.intraday_accumulation_store import save_ofi, load_ofi
        n = save_ofi("2026-01-15", "10:30", "000001",
                     ofi=0.333, ofi_abs=290.0, bid_ask_pressure=2.0,
                     buy_vols_json="[100,200]", sell_vols_json="[50,100]",
                     seal_amount=5000000.0, regime="strong_trend")
        assert n == 1
        recs = load_ofi("2026-01-15", "2026-01-15")
        assert len(recs) == 1
        assert recs[0]["code"] == "000001"
        assert recs[0]["ofi"] == pytest.approx(0.333, abs=0.01)
        assert recs[0]["bid_ask_pressure"] == pytest.approx(2.0, abs=0.01)
        assert recs[0]["regime"] == "strong_trend"

    def test_save_ofi_idempotent_insert_or_replace(self, tmp_path, monkeypatch):
        """同 (date, ts, code) INSERT OR REPLACE 幂等不翻倍。"""
        import data.intraday_accumulation_store as store
        monkeypatch.setattr(store, "_DB_PATH", str(tmp_path / "test_ofi.db"))
        from data.intraday_accumulation_store import save_ofi, load_ofi
        save_ofi("2026-01-15", "10:30", "000001", ofi=0.1, ofi_abs=100, bid_ask_pressure=1.5,
                 buy_vols_json="[]", sell_vols_json="[]", seal_amount=None, regime=None)
        save_ofi("2026-01-15", "10:30", "000001", ofi=0.5, ofi_abs=500, bid_ask_pressure=3.0,
                 buy_vols_json="[]", sell_vols_json="[]", seal_amount=None, regime=None)
        recs = load_ofi("2026-01-15", "2026-01-15")
        assert len(recs) == 1  # INSERT OR REPLACE 不翻倍
        assert recs[0]["ofi"] == pytest.approx(0.5, abs=0.01)  # 最新值

    def test_save_ofi_multiple_codes(self, tmp_path, monkeypatch):
        import data.intraday_accumulation_store as store
        monkeypatch.setattr(store, "_DB_PATH", str(tmp_path / "test_ofi.db"))
        from data.intraday_accumulation_store import save_ofi, load_ofi
        for code in ["000001", "000002", "600519"]:
            save_ofi("2026-01-15", "10:30", code, ofi=0.2, ofi_abs=100, bid_ask_pressure=1.5,
                     buy_vols_json="[]", sell_vols_json="[]", seal_amount=None, regime=None)
        recs = load_ofi("2026-01-15", "2026-01-15")
        assert len(recs) == 3


class TestOfiCollector:
    """S176 T4 — 五档时序轮询采集器（mock tencent fetch_raw + 数据质量门）。"""

    def _patch_store(self, tmp_path, monkeypatch):
        import data.intraday_accumulation_store as store
        monkeypatch.setattr(store, "_DB_PATH", str(tmp_path / "test_ofi.db"))

    def test_collect_ofi_for_codes(self, tmp_path, monkeypatch):
        self._patch_store(tmp_path, monkeypatch)
        def mock_fetch(codes):
            return {
                "000001": {"buy": [{"level": 1, "vol": 100}, {"level": 2, "vol": 200}],
                           "sell": [{"level": 1, "vol": 50}, {"level": 2, "vol": 100}]},
                "000002": {"buy": [{"level": 1, "vol": 200}], "sell": [{"level": 1, "vol": 100}]},
            }
        monkeypatch.setattr("data.sources.tencent.fetch_raw", mock_fetch)
        from engine.intraday_ofi_collector import collect_ofi_for_codes
        result = collect_ofi_for_codes(["000001", "000002"], "2026-01-15", "10:30", regime="strong_trend")
        assert result["n_collected"] == 2
        assert result["n_skipped"] == 0
        from data.intraday_accumulation_store import load_ofi
        recs = load_ofi("2026-01-15", "2026-01-15")
        assert len(recs) == 2
        r1 = next(r for r in recs if r["code"] == "000001")
        assert r1["ofi"] == pytest.approx(0.333, abs=0.01)  # (300-150)/450
        assert r1["regime"] == "strong_trend"

    def test_collect_skips_missing_codes(self, tmp_path, monkeypatch):
        self._patch_store(tmp_path, monkeypatch)
        def mock_fetch(codes):
            return {"000001": {"buy": [{"vol": 100}], "sell": [{"vol": 50}]}}  # 缺 000002
        monkeypatch.setattr("data.sources.tencent.fetch_raw", mock_fetch)
        from engine.intraday_ofi_collector import collect_ofi_for_codes
        result = collect_ofi_for_codes(["000001", "000002"], "2026-01-15", "10:30")
        assert result["n_collected"] == 1
        assert result["n_skipped"] == 1  # 000002 缺失跳过

    def test_collect_skips_empty_levels(self, tmp_path, monkeypatch):
        self._patch_store(tmp_path, monkeypatch)
        def mock_fetch(codes):
            return {"000001": {"buy": [], "sell": []}}  # 全空（停牌/坏档）
        monkeypatch.setattr("data.sources.tencent.fetch_raw", mock_fetch)
        from engine.intraday_ofi_collector import collect_ofi_for_codes
        result = collect_ofi_for_codes(["000001"], "2026-01-15", "10:30")
        assert result["n_collected"] == 0
        assert result["n_skipped"] == 1

    def test_collect_fetch_failure_skips_all(self, tmp_path, monkeypatch):
        """tencent fetch_raw 异常 → 全跳过，不崩。"""
        self._patch_store(tmp_path, monkeypatch)
        def mock_fetch(codes):
            raise ConnectionError("tencent down")
        monkeypatch.setattr("data.sources.tencent.fetch_raw", mock_fetch)
        from engine.intraday_ofi_collector import collect_ofi_for_codes
        result = collect_ofi_for_codes(["000001", "000002"], "2026-01-15", "10:30")
        assert result["n_collected"] == 0
        assert result["n_skipped"] == 2

    def test_collect_empty_codes(self, tmp_path, monkeypatch):
        from engine.intraday_ofi_collector import collect_ofi_for_codes
        result = collect_ofi_for_codes([], "2026-01-15", "10:30")
        assert result["n_codes"] == 0
        assert result["n_collected"] == 0


class TestOfiCollectExecutor:
    """S176 T5+T6 — ofi_collect executor dispatch + wrapper + 不喂 trade_journal 隔离（A3）。"""

    def test_ofi_collect_in_dispatch(self):
        from scheduler.executors import TaskExecutor
        executor = TaskExecutor()
        assert "ofi_collect" in executor._executors
        assert callable(executor._executors["ofi_collect"])

    def test_ofi_collect_executor_calls_collector(self, tmp_path, monkeypatch):
        import data.intraday_accumulation_store as store
        monkeypatch.setattr(store, "_DB_PATH", str(tmp_path / "test_ofi.db"))
        def mock_fetch(codes):
            return {"000001": {"buy": [{"vol": 100}], "sell": [{"vol": 50}]}}
        monkeypatch.setattr("data.sources.tencent.fetch_raw", mock_fetch)
        from scheduler.executors.intraday import ofi_collect
        result = ofi_collect({"codes": ["000001"], "regime": "test"})
        assert result["n_collected"] == 1

    def test_ofi_collect_no_codes_returns_empty(self):
        from scheduler.executors.intraday import ofi_collect
        result = ofi_collect({})
        assert result["n_codes"] == 0
        assert result["n_collected"] == 0

    def test_ofi_collect_does_not_touch_trade_journal(self):
        """A3: ofi_collect + collect_ofi_for_codes 不 import/调 trade_journal（独立 store 隔离）。

        docstring 提"不喂 trade_journal" 是注释（非 import）；检查实际 import/call 模式。
        """
        import inspect
        from scheduler.executors.intraday import ofi_collect
        from engine.intraday_ofi_collector import collect_ofi_for_codes
        src1 = inspect.getsource(ofi_collect)
        src2 = inspect.getsource(collect_ofi_for_codes)
        # 不 import trade_journal / 不调 trade_journal.insert
        assert "import trade_journal" not in src1
        assert "import trade_journal" not in src2
        assert "from engine.trade_journal" not in src1
        assert "from engine.trade_journal" not in src2
        assert "trade_journal.insert" not in src1
        assert "trade_journal.insert" not in src2
        assert "TradeJournal" not in src1  # 不构造 TradeJournal 实例
        assert "TradeJournal" not in src2

    def test_execute_ofi_collect_wrapper_delegates(self, tmp_path, monkeypatch):
        import data.intraday_accumulation_store as store
        monkeypatch.setattr(store, "_DB_PATH", str(tmp_path / "test_ofi.db"))
        def mock_fetch(codes):
            return {"000001": {"buy": [{"vol": 100}], "sell": [{"vol": 50}]}}
        monkeypatch.setattr("data.sources.tencent.fetch_raw", mock_fetch)
        from scheduler.executors import TaskExecutor
        result = TaskExecutor()._execute_ofi_collect({"codes": ["000001"]})
        assert result["n_collected"] == 1
