# -*- coding: utf-8 -*-
"""S205 T1-T5 TDD test：5 战法维度集 + 7 compute + 5 match + 5 harness。"""
import sys
from pathlib import Path

import pytest

backend_dir = Path(__file__).resolve().parent.parent
if str(backend_dir) not in sys.path:
    sys.path.insert(0, str(backend_dir))


class TestS205Registry:
    def test_5战法_config_declared(self):
        from strategies.s205_registry import _S205_CONFIGS
        assert len(_S205_CONFIGS) == 5
        for name, cfg in _S205_CONFIGS.items():
            assert cfg.dimensions, f"{name} dimensions 空"

    def test_weights_sum_one(self):
        from strategies.s205_registry import _S205_CONFIGS
        for name, cfg in _S205_CONFIGS.items():
            s = sum(cfg.weights.values())
            assert abs(s - 1.0) < 0.01, f"{name} weights sum={s} != 1.0"

    def test_edge_type_marked_unverified(self):
        from strategies.s205_registry import _S205_CONFIGS
        for name, cfg in _S205_CONFIGS.items():
            assert "待验" in cfg.edge_type, f"{name} edge_type={cfg.edge_type} 应含待验"

    def test_7_new_dims_in_registry(self):
        # import s205_registry triggers DIMENSION_REGISTRY.update
        from strategies.s205_registry import _S205_NEW_DIMS  # noqa: F401
        from strategies.dimension_registry import DIMENSION_REGISTRY
        for dim_id in ("auction_signal", "expectation_gap_reversal", "volume_rhythm",
                       "pullback_structure", "leader_identity", "pullback_rhythm", "reversal_confirm"):
            assert dim_id in DIMENSION_REGISTRY, f"{dim_id} 未在 DIMENSION_REGISTRY"

    def test_7_new_dims_data_source_not_fabricated(self):
        from strategies.s205_registry import _S205_NEW_DIMS
        for dim_id, dim in _S205_NEW_DIMS.items():
            assert dim.data_source, f"{dim_id} data_source 空"
            assert not dim.data_source.startswith("臆造"), f"{dim_id} data_source 臆造"

    def test_configs_frozen(self):
        from strategies.s205_registry import _S205_CONFIGS
        import dataclasses
        for cfg in _S205_CONFIGS.values():
            assert dataclasses.is_dataclass(cfg)


class TestS205Compute:
    def test_compute_returns_float_0_1(self):
        from strategies import pattern_scan_s205 as ps
        bars = [{"date": f"2026-01-{i:02d}", "open": 10.0, "high": 10.5, "low": 9.5,
                 "close": 10.2, "volume": 10000} for i in range(1, 6)]
        for fn in (ps.compute_expectation_gap_reversal, ps.compute_volume_rhythm,
                   ps.compute_pullback, ps.compute_reversal_confirm):
            v = fn(code="000001", date="2026-01-05", bars=bars) if fn is ps.compute_expectation_gap_reversal else fn(bars=bars)
            assert isinstance(v, float)
            assert 0.0 <= v <= 1.0

    def test_missing_data_returns_zero(self):
        from strategies import pattern_scan_s205 as ps
        assert ps.compute_volume_rhythm(bars=None) == 0.0
        assert ps.compute_pullback(bars=[]) == 0.0
        assert ps.compute_reversal_confirm(bars=None) == 0.0
        assert ps.compute_expectation_gap_reversal("x", "d", bars=None) == 0.0
        assert ps.compute_leader_identity() == 0.0
        assert ps.compute_pullback_rhythm() == 0.0

    def test_immutable_pure_function(self):
        from strategies import pattern_scan_s205 as ps
        bars = [{"date": f"2026-01-{i:02d}", "open": 10.0, "high": 10.5, "low": 9.5,
                 "close": 10.2, "volume": 10000} for i in range(1, 6)]
        bars_copy = [dict(b) for b in bars]
        ps.compute_volume_rhythm(bars=bars)
        ps.compute_pullback(bars=bars)
        assert bars == bars_copy, "compute 改了输入 bars（非 immutable）"

    def test_auction_signal_blocked(self):
        from strategies import pattern_scan_s205 as ps
        assert ps.AUCTION_SIGNAL_BLOCKER is True
        assert ps.compute_auction_signal("000001", "2026-01-05") == 0.0

    def test_leader_identity_sector_rank_le3(self):
        from strategies import pattern_scan_s205 as ps
        assert ps.compute_leader_identity(sector_rank=2, lbc=3, high_gene=1) == 1.0
        assert ps.compute_leader_identity(sector_rank=5, lbc=1, high_gene=0) == 0.0


class TestS205Match:
    def test_match_returns_composite_or_none(self):
        from strategies import s205_match as m
        bars = [{"date": f"2026-01-{i:02d}", "open": 10.0+i*0.1, "high": 10.5+i*0.1,
                 "low": 9.5+i*0.1, "close": 10.2+i*0.1, "volume": 10000+i*1000} for i in range(1, 6)]
        msc = {"sector_rank": 2, "lbc": 2, "high_gene": 1, "zt_count_today": 5,
               "sti_score": 70, "volume_breakout_ratio": 2.0, "tech_score": 0.7}
        for fn in (m.match_ruozhuanqiang, m.match_nzi_fanji, m.match_dixi_longtou, m.match_xingtai_fanbao):
            v = fn("000001", "2026-01-05", bars=bars, msc=msc)
            assert v is None or isinstance(v, float), f"{fn.__name__} 返 {type(v)}"

    def test_yizi_jingjia_blocked(self):
        from strategies import s205_match as m
        assert m.match_yizi_jingjia("000001", "2026-01-05") is None  # BLOCKER

    def test_match_missing_data_none(self):
        from strategies import s205_match as m
        assert m.match_ruozhuanqiang("x", "d", bars=None, msc=None) is None


class TestS205Harness:
    def test_harness_5_run(self):
        for name in ("yizi_jingjia", "ruozhuanqiang", "nzi_fanji", "dixi_longtou", "xingtai_fanbao"):
            mod = __import__(f"tools.regime_stratified_{name}_lift", fromlist=["run"])
            assert hasattr(mod, "run")
            assert hasattr(mod, "STRATEGY_NAME")
            assert mod.STRATEGY_NAME == name

    def test_harness_small_n_skip(self):
        from tools.regime_stratified_ruozhuanqiang_lift import run
        regime_map = {"2026-01-01": "bull", "2026-01-02": "bull"}
        r = run(returns=[0.01, -0.02], dates=["2026-01-01", "2026-01-02"], regime_map=regime_map)
        assert isinstance(r, dict)
