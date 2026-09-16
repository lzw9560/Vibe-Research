# -*- coding: utf-8 -*-
"""S203 consecutive_relay §44 harness 测试——compute_obs 纯函数 DI + decimal 口径 + 诚实 gate。

验：
  - compute_obs 纯函数（DI cost_fn 注入）
  - gap_ret decimal 口径（0.02=2%，非 pct 2.0）——对齐 regime_stats net_mean_pct=arr.mean()*100
  - cost _cost_pct/100 转 decimal（同口径）
  - _is_unbuyable_next_bar 过滤一字板（survivorship）
  - 缺 bars / 缺 date 跳过
"""
import sys
from pathlib import Path

backend_dir = Path(__file__).resolve().parent.parent
if str(backend_dir) not in sys.path:
    sys.path.insert(0, str(backend_dir))


class TestZtHistoryPicksLbc2:
    def test_empty_when_no_db(self, monkeypatch, tmp_path):
        import tools.s203_consecutive_relay_harness as h
        monkeypatch.setattr(h, "ZT_DB", tmp_path / "nonexistent.db")
        assert h._zt_history_picks_lbc2() == []


class TestComputeObs:
    def _bars(self):
        """2 天 bars: D=2026-01-15 close=10.0, D+1=2026-01-16 open=10.2（gap +2%）。"""
        return [
            {
                "date": "2026-01-15", "open": 10.0, "high": 10.5, "low": 9.5,
                "close": 10.0, "volume": 1000, "pctChg": 0.5,
            },
            {
                "date": "2026-01-16", "open": 10.2, "high": 10.8, "low": 9.8,
                "close": 10.5, "volume": 1000, "pctChg": 5.0,
            },
        ]

    def test_no_bar_skips(self):
        import tools.s203_consecutive_relay_harness as h
        cache = {}
        obs = h.compute_obs(cache, [("2026-01-15", "000001")])
        assert obs == []

    def test_missing_date_skips(self):
        import tools.s203_consecutive_relay_harness as h
        cache = {"000001": self._bars()}
        obs = h.compute_obs(cache, [("2026-02-01", "000001")])  # date 不在 bars
        assert obs == []

    def test_filters_d_day_unbuyable(self, monkeypatch):
        """D 日一字板（close 买不到）→ 过滤。验 filter 查 D 日非 D+1（verify w5d3urvxz CRITICAL fix）。"""
        import tools.s203_consecutive_relay_harness as h
        cache = {"000001": self._bars()}
        # mock: 只 D 日 bar（2026-01-15）返 True（一字板），D+1 返 False
        monkeypatch.setattr(
            h, "_is_unbuyable_next_bar",
            lambda bar: str(bar.get("date", ""))[:10] == "2026-01-15",
        )
        obs = h.compute_obs(
            cache, [("2026-01-15", "000001")], cost_fn=lambda *a, **k: 0.0
        )
        assert obs == []  # D 日一字板 → 入场日 close 买不到 → 过滤

    def test_d1_unbuyable_does_not_filter(self, monkeypatch):
        """D+1 一字板（不影响 D 日 close 买入）→ 不过滤。验 filter 查 D 日非 D+1。"""
        import tools.s203_consecutive_relay_harness as h
        cache = {"000001": self._bars()}
        # mock: 只 D+1 bar（2026-01-16）返 True，D 日返 False
        monkeypatch.setattr(
            h, "_is_unbuyable_next_bar",
            lambda bar: str(bar.get("date", ""))[:10] == "2026-01-16",
        )
        obs = h.compute_obs(
            cache, [("2026-01-15", "000001")], cost_fn=lambda *a, **k: 0.0
        )
        assert len(obs) == 1  # D 日可买 → 不过滤；D+1 一字板不影响 D 日 close 入场

    def test_gap_ret_decimal_not_pct(self, monkeypatch):
        """gap_ret 用 decimal（0.02=2%），非 pct（2.0）——对齐 regime_stats。"""
        import tools.s203_consecutive_relay_harness as h
        cache = {"000001": self._bars()}
        monkeypatch.setattr(h, "_is_unbuyable_next_bar", lambda bar: False)
        obs = h.compute_obs(
            cache, [("2026-01-15", "000001")], cost_fn=lambda *a, **k: 0.0
        )
        assert len(obs) == 1
        # close=10.0, open_d1=10.2 → gap_ret=(10.2-10.0)/10.0=0.02 (decimal)
        assert abs(obs[0]["net"] - 0.02) < 1e-9
        assert obs[0]["win"] == 1

    def test_cost_decimal_divided_by_100(self, monkeypatch):
        """cost_pct / 100 转 decimal——_cost_pct 返 pct（1.0=1%），caller /100=0.01 decimal。"""
        import tools.s203_consecutive_relay_harness as h
        cache = {"000001": self._bars()}
        monkeypatch.setattr(h, "_is_unbuyable_next_bar", lambda bar: False)
        obs = h.compute_obs(
            cache, [("2026-01-15", "000001")], cost_fn=lambda *a, **k: 1.0
        )
        assert len(obs) == 1
        # gap_ret=0.02 decimal, cost=1.0/100=0.01 decimal, net=0.01
        assert abs(obs[0]["cost"] - 0.01) < 1e-9
        assert abs(obs[0]["net"] - 0.01) < 1e-9
        assert obs[0]["win"] == 1

    def test_net_negative_when_cost_exceeds_gap(self, monkeypatch):
        """gap 小但 cost 大 → net 负，win=0。"""
        import tools.s203_consecutive_relay_harness as h
        cache = {"000001": self._bars()}
        monkeypatch.setattr(h, "_is_unbuyable_next_bar", lambda bar: False)
        obs = h.compute_obs(
            cache, [("2026-01-15", "000001")], cost_fn=lambda *a, **k: 5.0
        )
        assert len(obs) == 1
        # gap_ret=0.02, cost=0.05, net=-0.03
        assert abs(obs[0]["net"] - (-0.03)) < 1e-9
        assert obs[0]["win"] == 0

    def test_close_zero_skips(self, monkeypatch):
        """close_d<=0 → 跳过（防除零）。"""
        import tools.s203_consecutive_relay_harness as h
        bars = [
            {"date": "2026-01-15", "open": 10.0, "high": 10.5, "low": 9.5,
             "close": 0.0, "volume": 1000, "pctChg": 0.5},
            {"date": "2026-01-16", "open": 10.2, "high": 10.8, "low": 9.8,
             "close": 10.5, "volume": 1000, "pctChg": 5.0},
        ]
        cache = {"000001": bars}
        monkeypatch.setattr(h, "_is_unbuyable_next_bar", lambda bar: False)
        obs = h.compute_obs(cache, [("2026-01-15", "000001")])
        assert obs == []
