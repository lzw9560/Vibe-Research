# -*- coding: utf-8 -*-
"""S204 T10: early_admission test（TDD）。

验证 pre-涨停候选识别 + T-1 pit guard + 入池过滤（非 pre-涨停 不入池）。
"""
from __future__ import annotations

from early_admission import EarlyAdmitCandidate, scan_early_admission


def test_high_gene_admitted():
    """high_gene=1 → 入池（signal_type=high_gene）。"""
    cands = [{"code": "600000", "high_gene": 1, "sector_rank": 5}]
    out = scan_early_admission("2026-01-10", cands, previous_trade_day="2026-01-09")
    assert len(out) == 1
    assert out[0].code == "600000"
    assert out[0].signal_type == "high_gene"
    assert out[0].admit_date == "2026-01-09"  # T-1


def test_relay_seed_admitted():
    """lbc≥1（连板苗子）→ 入池（signal_type=relay_seed）。"""
    cands = [{"code": "600001", "lbc": 1, "zt_count_today": 0}]
    out = scan_early_admission("2026-01-10", cands, "2026-01-09")
    assert len(out) == 1
    assert out[0].signal_type == "relay_seed"


def test_sector_startup_admitted():
    """zt_count_today≥2（板块启动）→ 入池（signal_type=sector_startup）。"""
    cands = [{"code": "600002", "zt_count_today": 3, "lbc": 0, "high_gene": 0}]
    out = scan_early_admission("2026-01-10", cands, "2026-01-09")
    assert len(out) == 1
    assert out[0].signal_type == "sector_startup"


def test_non_pre_limitup_not_admitted():
    """非 pre-涨停（无信号）不入池。"""
    cands = [{"code": "600003", "zt_count_today": 0, "lbc": 0, "high_gene": 0, "sector_rank": 10}]
    out = scan_early_admission("2026-01-10", cands, "2026-01-09")
    assert len(out) == 0


def test_already_limitup_not_admitted():
    """已涨停（lbc≥2 当下涨停）不入池（pre-涨停 only）。"""
    cands = [{"code": "600004", "lbc": 2}]  # lbc≥2 = 已 2 板，非 pre
    out = scan_early_admission("2026-01-10", cands, "2026-01-09")
    assert len(out) == 0  # lbc≥2 已涨停，非连板苗子（lbc=1）


def test_t1_pit_guard_admit_date():
    """admit_date = T-1（pit guard：T 日未开盘，入池日 T-1）。"""
    cands = [{"code": "600000", "high_gene": 1}]
    out = scan_early_admission("2026-01-10", cands, previous_trade_day="2026-01-09")
    assert all(c.admit_date == "2026-01-09" for c in out)


def test_no_candidates_empty():
    """空候选 → 空列表。"""
    assert scan_early_admission("2026-01-10", [], "2026-01-09") == []


def test_indicators_t1_captured():
    """T-1 指标快照入 EarlyAdmitCandidate（供 escalation maturity 评）。"""
    cands = [{"code": "600000", "high_gene": 1, "sector_rank": 2, "zt_count_today": 3, "lbc": 1}]
    out = scan_early_admission("2026-01-10", cands, "2026-01-09")
    assert out[0].indicators_t1 == {"sector_rank": 2, "zt_count_today": 3, "lbc": 1, "high_gene": 1}


def test_early_admit_candidate_immutable():
    """EarlyAdmitCandidate frozen dataclass。"""
    import pytest

    c = EarlyAdmitCandidate("600000", "2026-01-09", "high_gene", {})
    with pytest.raises(Exception):
        c.code = "other"  # frozen


def test_high_gene_priority_over_relay():
    """high_gene=1 + lbc=1 → signal_type=high_gene（优先级最高）。"""
    cands = [{"code": "600000", "high_gene": 1, "lbc": 1, "zt_count_today": 3}]
    out = scan_early_admission("2026-01-10", cands, "2026-01-09")
    assert len(out) == 1
    assert out[0].signal_type == "high_gene"  # 优先
