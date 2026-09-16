# -*- coding: utf-8 -*-
"""S209 T6: post-首板 relay §44 harness 测试——DRY 复用 + underpowered 诚实 gate。

验：compute_obs 纯函数（DRY scanner/holder/cost_fn 注入）+ main underpowered 路径
（n<30 短路不调 wire_verdict）+ n≥30 wire_verdict K=2 Bonferroni（selection + event）。
"""
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock

backend_dir = Path(__file__).resolve().parent.parent
if str(backend_dir) not in sys.path:
    sys.path.insert(0, str(backend_dir))


class TestZtHistoryDates:
    def test_empty_when_no_db(self, monkeypatch, tmp_path):
        import tools.s209_t10_executor_harness as h
        monkeypatch.setattr(h, "ZT_DB", tmp_path / "nonexistent.db")
        assert h._zt_history_dates() == []


class TestComputeObs:
    def _bars(self, n=5, start=15):
        """n 天 bars，2026-01-{start}..start+n-1，非一字板（有日内区间）。"""
        return [
            {
                "date": f"2026-01-{start + i:02d}",
                "open": 10.0 + i, "high": 11.0 + i, "low": 9.0 + i,
                "close": 10.5 + i, "volume": 1000, "pctChg": 0.5,
            }
            for i in range(n)
        ]

    def test_empty_candidates(self):
        import tools.s209_t10_executor_harness as h
        cache = {"000001": self._bars()}
        obs = h.compute_obs(cache, ["2026-01-15"], scanner=lambda d, previous_trade_day=None: [])
        assert obs == []

    def test_no_bar_skips(self):
        import tools.s209_t10_executor_harness as h
        cache = {}  # 无 code 的 bars
        scanner = MagicMock(return_value=[{"code": "000001"}])
        obs = h.compute_obs(cache, ["2026-01-15"], scanner=scanner)
        assert obs == []

    def test_filters_unbuyable(self, monkeypatch):
        """一字板封死（_is_unbuyable_next_bar=True）→ 跳过 survivorship 过滤。"""
        import tools.s209_t10_executor_harness as h
        cache = {"000001": self._bars()}
        scanner = MagicMock(return_value=[{"code": "000001"}])
        monkeypatch.setattr(h, "_is_unbuyable_next_bar", lambda bar: True)
        obs = h.compute_obs(cache, ["2026-01-15"], scanner=scanner)
        assert obs == []

    def test_net_return_computed(self, monkeypatch):
        """net = return_pct - cost，win=1 if net>0。"""
        import tools.s209_t10_executor_harness as h
        cache = {"000001": self._bars()}
        scanner = MagicMock(return_value=[{"code": "000001"}])
        holder = MagicMock(return_value={"return_pct": 5.0})
        cost_fn = MagicMock(return_value=0.7)
        monkeypatch.setattr(h, "_is_unbuyable_next_bar", lambda bar: False)
        obs = h.compute_obs(
            cache, ["2026-01-15"], scanner=scanner, holder=holder, cost_fn=cost_fn
        )
        assert len(obs) == 1
        assert obs[0]["net"] == 4.3  # 5.0 - 0.7
        assert obs[0]["win"] == 1
        assert obs[0]["code"] == "000001"
        assert obs[0]["D"] == "2026-01-15"

    def test_loss_when_net_negative(self, monkeypatch):
        """net<0 → win=0。"""
        import tools.s209_t10_executor_harness as h
        cache = {"000001": self._bars()}
        scanner = MagicMock(return_value=[{"code": "000001"}])
        holder = MagicMock(return_value={"return_pct": -3.0})
        cost_fn = MagicMock(return_value=0.7)
        monkeypatch.setattr(h, "_is_unbuyable_next_bar", lambda bar: False)
        obs = h.compute_obs(
            cache, ["2026-01-15"], scanner=scanner, holder=holder, cost_fn=cost_fn
        )
        assert obs[0]["net"] == -3.7
        assert obs[0]["win"] == 0

    def test_multi_day_multi_code(self, monkeypatch):
        """2 日各 2 候选 → 4 obs（两 code × 两日，均有对应 bar）。"""
        import tools.s209_t10_executor_harness as h
        cache = {"000001": self._bars(), "000002": self._bars()}
        scanner = MagicMock(return_value=[{"code": "000001"}, {"code": "000002"}])
        holder = MagicMock(return_value={"return_pct": 2.0})
        cost_fn = MagicMock(return_value=0.5)
        monkeypatch.setattr(h, "_is_unbuyable_next_bar", lambda bar: False)
        obs = h.compute_obs(
            cache, ["2026-01-15", "2026-01-16"], scanner=scanner, holder=holder, cost_fn=cost_fn
        )
        # 2 日 × 2 候选 = 4 obs
        assert len(obs) == 4
        days = set(o["D"] for o in obs)
        assert days == {"2026-01-15", "2026-01-16"}
        codes = set(o["code"] for o in obs)
        assert codes == {"000001", "000002"}


class TestMainUnderpowered:
    """main() underpowered 诚实 gate（R6: n<30 或 days<60 不造假 robust_edge）。"""

    def _mock_main_deps(self, monkeypatch, obs=None, dates=None):
        import tools.s209_t10_executor_harness as h
        monkeypatch.setattr(h, "_load_kline_cache", lambda: {})
        monkeypatch.setattr(h, "validate_or_reject", lambda *a, **k: None)
        monkeypatch.setattr(h, "_zt_history_dates", lambda: dates if dates is not None else [])
        if obs is not None:
            monkeypatch.setattr(h, "compute_obs", lambda cache, dates: obs)

    def test_no_dates_underpowered(self, monkeypatch):
        import tools.s209_t10_executor_harness as h
        self._mock_main_deps(monkeypatch, dates=[])
        result = h.main()
        assert result["status"] == "underpowered"
        assert result["n"] == 0

    def test_n_lt_30_underpowered(self, monkeypatch):
        """n<30 → underpowered，不调 wire_verdict（短路 return 前不 reach）。"""
        import tools.s209_t10_executor_harness as h
        obs = [{"D": "2026-01-15", "code": "000001", "net": 1.0, "win": 1, "cost": 0.7}
               for _ in range(10)]  # n=10 < 30
        self._mock_main_deps(monkeypatch, obs=obs, dates=["2026-01-15"])
        wire_calls = MagicMock()
        monkeypatch.setattr(h, "wire_verdict", wire_calls)
        result = h.main()
        assert result["status"] == "underpowered"
        assert result["n"] == 10
        assert wire_calls.call_count == 0  # n<30 短路，wire_verdict 不调

    def test_n_ge_30_wires_verdict_k2(self, monkeypatch):
        """n≥30 → wire_verdict 调 2 次（selection + event），n_comparisons=2 Bonferroni K=2。"""
        import tools.s209_t10_executor_harness as h
        obs = [{"D": f"2026-01-{i + 1:02d}", "code": f"00000{i}", "net": 1.0, "win": 1, "cost": 0.7}
               for i in range(40)]  # n=40 ≥ 30，40 不同日
        self._mock_main_deps(monkeypatch, obs=obs, dates=[o["D"] for o in obs])
        calls = []
        fake_v = SimpleNamespace(
            status="underpowered", selection_lift=1.0, n=40, days_robust=5, note=""
        )

        def fake_wire(**kwargs):
            calls.append(kwargs)
            return fake_v

        monkeypatch.setattr(h, "wire_verdict", fake_wire)
        result = h.main()
        assert len(calls) == 2, f"应调 wire_verdict 2 次（selection + event），got {len(calls)}"
        # selection arm
        assert calls[0]["edge_type"] == "selection"
        assert calls[0]["n_comparisons"] == 2  # Bonferroni K=2
        assert calls[0]["line_id"] == "post_first_board:selection"
        assert calls[0]["survivors_by_day"] is not None
        assert calls[0]["universe_by_day"] is not None
        # event arm
        assert calls[1]["edge_type"] == "event"
        assert calls[1]["n_comparisons"] == 2
        assert calls[1]["line_id"] == "post_first_board:event"
        # event 不传 survivors/universe（群体收益 edge，非选股 lift）
        assert "survivors_by_day" not in calls[1] or calls[1].get("survivors_by_day") is None
        # summary
        assert "selection" in result
        assert "event" in result
        assert result["n_obs"] == 40
        assert result["days"] == 40

    def test_frozen_commit_constant(self):
        """FROZEN 是真实 commit SHA（非臆造占位）——reproduce 须可追溯。"""
        import tools.s209_t10_executor_harness as h
        assert h.FROZEN and len(h.FROZEN) >= 7, f"FROZEN 须是 commit SHA，got {h.FROZEN}"
        assert h.FROZEN != "PLACEHOLDER", "FROZEN 不可留占位"
