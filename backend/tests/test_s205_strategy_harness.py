# -*- coding: utf-8 -*-
"""S212 S205 4 战法 caller 测试——compute_obs + match threshold + decimal 口径。

验：
  - compute_obs 纯函数（DI match_fn + cost_fn）
  - match 返 None → 不命中 skip；返 composite → 命中算 return
  - gap_ret decimal 口径 + D 日一字板 filter + cost /100
"""
import sys
from pathlib import Path

backend_dir = Path(__file__).resolve().parent.parent
if str(backend_dir) not in sys.path:
    sys.path.insert(0, str(backend_dir))


class TestZtPicks:
    def test_empty_when_no_db(self, monkeypatch, tmp_path):
        import tools.s205_strategy_harness as h
        monkeypatch.setattr(h, "ZT_DB", tmp_path / "nonexistent.db")
        assert h._zt_picks() == []


class TestComputeObs:
    def _bars(self):
        """2 天 bars: D=2026-01-15 close=10.0, D+1=2026-01-16 open=10.2（gap +2%）。"""
        return [
            {"date": "2026-01-15", "open": 10.0, "high": 10.5, "low": 9.5,
             "close": 10.0, "volume": 1000, "pctChg": 0.5},
            {"date": "2026-01-16", "open": 10.2, "high": 10.8, "low": 9.8,
             "close": 10.5, "volume": 1000, "pctChg": 5.0},
        ]

    def test_no_bar_skips(self):
        import tools.s205_strategy_harness as h
        cache = {}
        obs = h.compute_obs(cache, [("2026-01-15", "000001")], match_fn=lambda *a, **k: 50.0)
        assert obs == []

    def test_missing_date_skips(self):
        import tools.s205_strategy_harness as h
        cache = {"000001": self._bars()}
        obs = h.compute_obs(cache, [("2026-02-01", "000001")], match_fn=lambda *a, **k: 50.0)
        assert obs == []

    def test_filters_d_day_unbuyable(self, monkeypatch):
        """D 日一字板（close 买不到）→ 过滤。"""
        import tools.s205_strategy_harness as h
        cache = {"000001": self._bars()}
        monkeypatch.setattr(h, "_is_unbuyable_next_bar", lambda bar: str(bar.get("date", ""))[:10] == "2026-01-15")
        obs = h.compute_obs(cache, [("2026-01-15", "000001")], match_fn=lambda *a, **k: 50.0)
        assert obs == []

    def test_match_none_skips(self, monkeypatch):
        """match_fn 返 None（不命中）→ skip。"""
        import tools.s205_strategy_harness as h
        cache = {"000001": self._bars()}
        monkeypatch.setattr(h, "_is_unbuyable_next_bar", lambda bar: False)
        obs = h.compute_obs(cache, [("2026-01-15", "000001")], match_fn=lambda *a, **k: None)
        assert obs == []

    def test_match_hit_computes_return(self, monkeypatch):
        """match_fn 返 composite（命中）→ 算 gap_ret decimal。"""
        import tools.s205_strategy_harness as h
        cache = {"000001": self._bars()}
        monkeypatch.setattr(h, "_is_unbuyable_next_bar", lambda bar: False)
        obs = h.compute_obs(
            cache, [("2026-01-15", "000001")],
            match_fn=lambda *a, **k: 50.0,  # composite > 30 命中
            cost_fn=lambda *a, **k: 0.0,
        )
        assert len(obs) == 1
        assert abs(obs[0]["net"] - 0.02) < 1e-9  # gap decimal 0.02
        assert obs[0]["score"] == 50.0
        assert obs[0]["win"] == 1

    def test_cost_decimal_divided_by_100(self, monkeypatch):
        """cost_pct / 100 转 decimal。"""
        import tools.s205_strategy_harness as h
        cache = {"000001": self._bars()}
        monkeypatch.setattr(h, "_is_unbuyable_next_bar", lambda bar: False)
        obs = h.compute_obs(
            cache, [("2026-01-15", "000001")],
            match_fn=lambda *a, **k: 50.0,
            cost_fn=lambda *a, **k: 1.0,  # pct
        )
        assert len(obs) == 1
        assert abs(obs[0]["cost"] - 0.01) < 1e-9
        assert abs(obs[0]["net"] - 0.01) < 1e-9  # gap 0.02 - cost 0.01

    def test_match_fn_receives_code_date_bars(self, monkeypatch):
        """match_fn 收到 code, date, bars, msc 参数。"""
        import tools.s205_strategy_harness as h
        cache = {"000001": self._bars()}
        monkeypatch.setattr(h, "_is_unbuyable_next_bar", lambda bar: False)
        captured = {}

        def _match(code, date, bars=None, msc=None, **kw):
            captured.update(code=code, date=date, bars_len=len(bars) if bars else 0, msc=msc)
            return 40.0

        obs = h.compute_obs(
            cache, [("2026-01-15", "000001")], match_fn=_match, cost_fn=lambda *a, **k: 0.0
        )
        assert len(obs) == 1
        assert captured["code"] == "000001"
        assert captured["date"] == "2026-01-15"
        assert captured["bars_len"] == 2
        assert captured["msc"] is None  # caller 传 msc=None
