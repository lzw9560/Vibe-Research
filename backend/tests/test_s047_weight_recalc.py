# -*- coding: utf-8 -*-
"""S047 阶段 B：新 full 权重 + 历史复算迁移测试。"""
import sqlite3

from limitup_screener.models import calc_total_score
from limitup_screener.recalc_gene_weights import FACTOR_COLS, recalc_live_rows


class TestNewFullWeights:
    def test_新权重数值(self):
        factors = {"次日溢价率": 60.0, "红盘率": 50.0, "封板率": 40.0, "炸板后溢价": 99.0, "涨停频次": 20.0}
        # 0.4*60 + 0.25*50 + 0.25*40 + 0*99 + 0.1*20 = 48.5
        assert calc_total_score(factors, "full") == 48.5

    def test_炸板后溢价不影响总分(self):
        base = {"次日溢价率": 60.0, "红盘率": 50.0, "封板率": 40.0, "涨停频次": 20.0}
        assert calc_total_score({**base, "炸板后溢价": 0.0}) == calc_total_score({**base, "炸板后溢价": 100.0})

    def test_rebuild权重不变(self):
        factors = {"次日溢价率": 60.0, "红盘率": 50.0, "涨停频次": 20.0}
        # 0.4*60 + 0.4*50 + 0.2*20 = 48.0
        assert calc_total_score(factors, "rebuild") == 48.0


def _make_db() -> sqlite3.Connection:
    conn = sqlite3.connect(":memory:")
    conn.execute(
        "CREATE TABLE gene_scores (code TEXT, date TEXT, total_score REAL, qualify INTEGER,"
        " high_gene INTEGER, data_source TEXT, " + " REAL, ".join(FACTOR_COLS) + " REAL)"
    )
    # live 行：因子 premium=60/red=50/seal=40/rebound=0/freq=20 → 新分 48.5（旧权重下存的 40.0 应被重算）
    conn.execute(
        "INSERT INTO gene_scores VALUES ('000001', '2026-07-01', 40.0, 0, 0, 'eastmoney_live',"
        " 60.0, 50.0, 40.0, 0.0, 20.0)"
    )
    # rebuild 行：不得被碰
    conn.execute(
        "INSERT INTO gene_scores VALUES ('000002', '2026-03-01', 44.0, 0, 0, 'kline_rebuild',"
        " 60.0, 50.0, 0.0, 0.0, 20.0)"
    )
    return conn


class TestRecalcLiveRows:
    def test_仅复算live行且派生列同步(self):
        conn = _make_db()
        stats = recalc_live_rows(conn)
        assert stats["n"] == 1 and stats["changed"] == 1
        live = conn.execute("SELECT total_score, qualify, high_gene FROM gene_scores WHERE code='000001'").fetchone()
        assert live == (48.5, 0, 0)  # 48.5 < 50 qualify 仍 False
        rebuild = conn.execute("SELECT total_score, qualify, high_gene FROM gene_scores WHERE code='000002'").fetchone()
        assert rebuild == (44.0, 0, 0)  # rebuild 逐行不变

    def test_qualify随新分翻转(self):
        conn = _make_db()
        # premium=80/red=60/seal=60/freq=30 → 0.4*80+0.25*60+0.25*60+0.1*30 = 65.0 → qualify True
        conn.execute(
            "INSERT INTO gene_scores VALUES ('000003', '2026-07-02', 45.0, 0, 0, 'eastmoney_live',"
            " 80.0, 60.0, 60.0, 0.0, 30.0)"
        )
        recalc_live_rows(conn)
        row = conn.execute("SELECT total_score, qualify FROM gene_scores WHERE code='000003'").fetchone()
        assert row == (65.0, 1)

    def test_dry_run不写库(self):
        conn = _make_db()
        stats = recalc_live_rows(conn, dry_run=True)
        assert stats["changed"] == 1
        assert conn.execute("SELECT total_score FROM gene_scores WHERE code='000001'").fetchone()[0] == 40.0

    def test_因子列不被迁移触碰(self):
        conn = _make_db()
        before = conn.execute("SELECT code, " + ", ".join(FACTOR_COLS) + " FROM gene_scores ORDER BY code").fetchall()
        recalc_live_rows(conn)
        after = conn.execute("SELECT code, " + ", ".join(FACTOR_COLS) + " FROM gene_scores ORDER BY code").fetchall()
        assert before == after
