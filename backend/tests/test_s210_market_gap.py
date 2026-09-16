# -*- coding: utf-8 -*-
"""S210 T1: market o2c gap by date 测试——event drift fix 数据层。

market o2c gap = (index_open[D+1] - index_close[D]) / index_close[D] per date。
复用 _fetch_index_bars_baostock（fields 加 open）。
"""
import sys
from pathlib import Path

backend_dir = Path(__file__).resolve().parent.parent
if str(backend_dir) not in sys.path:
    sys.path.insert(0, str(backend_dir))


class TestComputeMarketO2cGapByDate:
    def test_gap_computed_per_date(self, monkeypatch):
        """market o2c gap = (open[D+1]-close[D])/close[D] per date（list 包装兼容 event_drift）。"""
        from tools import gap_regime_stratified as grs

        bars = [
            {"date": "2026-01-15", "open": 3000.0, "close": 3010.0},
            {"date": "2026-01-16", "open": 3020.0, "close": 3000.0},
            {"date": "2026-01-17", "open": 3010.0, "close": 3050.0},
        ]
        monkeypatch.setattr(grs, "_fetch_index_bars_baostock", lambda: bars)
        gaps = grs.compute_market_o2c_gap_by_date()
        # gap[D] = (open[D+1]-close[D])/close[D]
        assert abs(gaps["2026-01-15"][0] - (3020.0 - 3010.0) / 3010.0) < 1e-6
        assert abs(gaps["2026-01-16"][0] - (3010.0 - 3000.0) / 3000.0) < 1e-6
        assert "2026-01-17" not in gaps  # 无 D+1 → skip

    def test_missing_open_close_skips(self, monkeypatch):
        """缺 open/close → 跳过该 gap（不臆造）。gap[D] 需 close[D] + open[D+1]。"""
        from tools import gap_regime_stratified as grs

        bars = [
            {"date": "2026-01-15", "open": 3000.0, "close": 3010.0},
            {"date": "2026-01-16", "open": None, "close": 3000.0},  # open None
            {"date": "2026-01-17", "open": 3010.0, "close": 3050.0},
        ]
        monkeypatch.setattr(grs, "_fetch_index_bars_baostock", lambda: bars)
        gaps = grs.compute_market_o2c_gap_by_date()
        # 01-15: close 3010 ok, 但 D+1=01-16 open=None → skip（open 缺）
        assert "2026-01-15" not in gaps
        # 01-16: close 3000 ok, D+1=01-17 open=3010 → gap=(3010-3000)/3000=0.00333
        assert "2026-01-16" in gaps
        assert abs(gaps["2026-01-16"][0] - (3010.0 - 3000.0) / 3000.0) < 1e-6
        # 01-17: 无 D+1 → skip
        assert "2026-01-17" not in gaps

    def test_empty_bars_returns_empty(self, monkeypatch):
        """无 bars → 返空 dict。"""
        from tools import gap_regime_stratified as grs

        monkeypatch.setattr(grs, "_fetch_index_bars_baostock", lambda: [])
        gaps = grs.compute_market_o2c_gap_by_date()
        assert gaps == {}

    def test_gap_decimal_not_pct(self, monkeypatch):
        """gap 用 decimal（0.0033=0.33%），非 pct——对齐 event returns decimal 口径。"""
        from tools import gap_regime_stratified as grs

        bars = [
            {"date": "2026-01-15", "open": 3000.0, "close": 3000.0},
            {"date": "2026-01-16", "open": 3010.0, "close": 3000.0},  # gap=10/3000=0.00333
        ]
        monkeypatch.setattr(grs, "_fetch_index_bars_baostock", lambda: bars)
        gaps = grs.compute_market_o2c_gap_by_date()
        assert abs(gaps["2026-01-15"][0] - 10.0 / 3000.0) < 1e-6  # decimal 0.00333 非 0.333
