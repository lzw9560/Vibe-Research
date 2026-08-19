# -*- coding: utf-8 -*-
"""S085 A7 — GeneScore per-score date 戳 单测。

验证：模型加 date 字段（默认 ""）；compute_gene_score 戳 date；load_gene_scores 从 DB hydrate date。
零 winrate 影响（结算/胜率读 final_candidates 不读 GeneScore，见 核实报告.md A7）。
"""
from __future__ import annotations

from limitup_screener.data import get_db, load_gene_scores, run_migrations
from limitup_screener.models import GeneScore, compute_gene_score

_EMPTY_FACTORS = {
    "次日溢价率": 0.0, "红盘率": 0.0, "封板率": 0.0, "炸板后溢价": 0.0, "涨停频次": 0.0,
}


def test_genescore_has_date_field_default_empty():
    # Arrange / Act — 必填字段补齐（last_zt_dates/qualify/high_gene 无默认值）
    g = GeneScore(code="600519", name="X", total_score=0.0, factors={},
                  wilson_adjusted=0.0, qualify=False, high_gene=False,
                  last_zt_dates=[], zt_count_250d=0)
    # Assert
    assert hasattr(g, "date")
    assert g.date == ""


def test_compute_gene_score_stamps_date():
    # Act
    g = compute_gene_score("600519", "贵州茅台", [], [], [], date="2026-08-19")
    # Assert
    assert g.date == "2026-08-19"
    assert g.code == "600519"


def test_compute_gene_score_date_defaults_empty():
    """旧调用方不传 date 须向后兼容（默认 ""）。"""
    # Act
    g = compute_gene_score("600519", "贵州茅台", [], [], [])
    # Assert
    assert g.date == ""


def test_load_gene_scores_hydrates_date():
    """DB 已有 date 列（PK），load 须 hydrate 到 GeneScore.date（修复 stale 口径）。"""
    # Arrange — 幂等迁移保表存在；直接插行专测 load hydrate（绕开 save 的 code_industry 依赖）
    run_migrations()
    conn = get_db()
    try:
        conn.execute(
            "INSERT OR REPLACE INTO gene_scores "
            "(date, code, name, total_score, factor_premium_rate, factor_red_rate, "
            "factor_seal_rate, factor_rebound_rate, factor_freq_score, wilson_adjusted, "
            "qualify, high_gene, zt_count_250d, data_source, missing_factors, industry) "
            "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            ("2026-08-19", "600519", "贵州茅台", 0.0, 0, 0, 0, 0, 0, 0.0, 0, 0, 0,
             "eastmoney_live", "[]", ""),
        )
        conn.commit()
    finally:
        conn.close()
    # Act
    loaded = load_gene_scores("2026-08-19")
    # Assert
    assert loaded is not None
    assert any(s.code == "600519" and s.date == "2026-08-19" for s in loaded)


def test_load_gene_scores_date_empty_for_legacy_row():
    """旧行无 date 问题不可能（date 是 PK NOT NULL），但 hydrate 路径对 row.keys() 防御性兜底。"""
    run_migrations()
    conn = get_db()
    try:
        conn.execute(
            "INSERT OR REPLACE INTO gene_scores "
            "(date, code, name, total_score, factor_premium_rate, factor_red_rate, "
            "factor_seal_rate, factor_rebound_rate, factor_freq_score, wilson_adjusted, "
            "qualify, high_gene, zt_count_250d, data_source, missing_factors, industry) "
            "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            ("2026-08-17", "000001", "平安银行", 10.0, 0, 0, 0, 0, 0, 0.0, 0, 0, 0,
             "eastmoney_live", "[]", ""),
        )
        conn.commit()
    finally:
        conn.close()
    loaded = load_gene_scores("2026-08-17")
    assert loaded is not None
    assert any(s.code == "000001" and s.date == "2026-08-17" for s in loaded)
