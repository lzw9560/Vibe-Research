# -*- coding: utf-8 -*-
"""S060 验证条件对账卡单测。

覆盖：生成器模板（≥5 条）+ 对账三态（met_up/met_down/within/data_missing）+ 持久化 + 编排。
"""

import sqlite3
from datetime import datetime
from unittest.mock import patch

import pytest


@pytest.fixture
def isolated_db(tmp_path, monkeypatch):
    db_path = tmp_path / "verification_card.db"
    import workflow.verification_card as vc
    monkeypatch.setattr(vc, "_DB_PATH", str(db_path))
    vc.run_migrations()
    return str(db_path)


def _emotion(zt=58, br=0.15, mb=3, sr=0.85, pr=0.4, yzt=99):
    return {
        "date": "2026-08-12",
        "zt_count": zt, "zb_count": 10, "dt_count": 5,
        "max_boards": mb, "lianban_count": 20,
        "seal_rate": sr, "break_rate": br,
        "promotion_rate": pr, "yzt_count": yzt,
    }


class TestGenerateConditions:
    def test_generates_at_least_five_conditions(self):
        from workflow.verification_card import generate_conditions
        conds = generate_conditions(_emotion())
        assert len(conds) >= 5
        metrics = {c.metric for c in conds}
        assert "zt_count" in metrics
        assert "break_rate" in metrics
        assert "max_boards" in metrics
        assert "seal_rate" in metrics

    def test_zt_count_thresholds_20pct(self):
        from workflow.verification_card import generate_conditions
        conds = generate_conditions(_emotion(zt=100))
        zt = next(c for c in conds if c.metric == "zt_count")
        assert zt.baseline == 100
        assert zt.threshold_up == 120
        assert zt.threshold_down == 80

    def test_break_rate_thresholds_5pct(self):
        from workflow.verification_card import generate_conditions
        conds = generate_conditions(_emotion(br=0.15))
        br = next(c for c in conds if c.metric == "break_rate")
        assert br.baseline == 0.15
        assert br.threshold_up == 0.20
        assert abs(br.threshold_down - 0.10) < 1e-6

    def test_max_boards_thresholds_1_board(self):
        from workflow.verification_card import generate_conditions
        conds = generate_conditions(_emotion(mb=3))
        mb = next(c for c in conds if c.metric == "max_boards")
        assert mb.baseline == 3
        assert mb.threshold_up == 4
        assert mb.threshold_down == 2

    def test_missing_field_skipped(self):
        """缺数据的指标不生成条件（不臆造）。"""
        from workflow.verification_card import generate_conditions
        emo = _emotion()
        emo["break_rate"] = None
        conds = generate_conditions(emo)
        assert all(c.metric != "break_rate" for c in conds)

    def test_yzt_count_thresholds_30pct(self):
        from workflow.verification_card import generate_conditions
        conds = generate_conditions(_emotion(yzt=100))
        yzt = next(c for c in conds if c.metric == "yzt_count")
        assert yzt.baseline == 100
        assert yzt.threshold_up == 130
        assert yzt.threshold_down == 70


class TestVerifyConditions:
    def test_met_up(self):
        from workflow.verification_card import generate_conditions, verify_conditions
        conds = generate_conditions(_emotion(zt=100))
        zt = next(c for c in conds if c.metric == "zt_count")
        # T+1 涨停 130 ≥ 120
        next_emo = _emotion(zt=130)
        verified = verify_conditions([zt], next_emo)
        assert verified[0].status == "met_up"

    def test_met_down(self):
        from workflow.verification_card import generate_conditions, verify_conditions
        conds = generate_conditions(_emotion(zt=100))
        zt = next(c for c in conds if c.metric == "zt_count")
        # T+1 涨停 75 ≤ 80
        next_emo = _emotion(zt=75)
        verified = verify_conditions([zt], next_emo)
        assert verified[0].status == "met_down"

    def test_within(self):
        from workflow.verification_card import generate_conditions, verify_conditions
        conds = generate_conditions(_emotion(zt=100))
        zt = next(c for c in conds if c.metric == "zt_count")
        # T+1 涨停 100 在 80-120 区间内
        next_emo = _emotion(zt=100)
        verified = verify_conditions([zt], next_emo)
        assert verified[0].status == "within"

    def test_data_missing_when_next_emotion_empty(self):
        from workflow.verification_card import generate_conditions, verify_conditions
        conds = generate_conditions(_emotion(zt=100))
        zt = next(c for c in conds if c.metric == "zt_count")
        verified = verify_conditions([zt], {})  # T+1 数据缺失
        assert verified[0].status == "data_missing"

    def test_yzt_count_uses_next_day_zt_count(self):
        """yzt_count 的对账用 next_day 的 zt_count（昨涨停今日溢价代理）。"""
        from workflow.verification_card import generate_conditions, verify_conditions
        conds = generate_conditions(_emotion(yzt=100))
        yzt = next(c for c in conds if c.metric == "yzt_count")
        # T+1 涨停 140 ≥ 130（yzt_count 的 threshold_up）
        next_emo = _emotion(zt=140)
        verified = verify_conditions([yzt], next_emo)
        assert verified[0].status == "met_up"


class TestPersistence:
    def test_save_and_get(self, isolated_db):
        from workflow.verification_card import generate_and_save, get_conditions
        conds = generate_and_save(_emotion(), "2026-08-12")
        assert len(conds) >= 5

        rows = get_conditions("2026-08-12")
        assert len(rows) == len(conds)
        assert all(r["status"] == "pending" for r in rows)

    def test_update_verified(self, isolated_db):
        from workflow.verification_card import (
            generate_and_save, get_conditions, get_pending_conditions, update_verified,
            VerificationCondition,
        )
        generate_and_save(_emotion(zt=100), "2026-08-12")
        pending = get_pending_conditions()
        assert len(pending) > 0

        # 模拟对账
        verified = [
            VerificationCondition(
                date="2026-08-12", metric=r["metric"], subject=r["subject"] or "",
                baseline=r["baseline"], threshold_up=r["threshold_up"],
                threshold_down=r["threshold_down"], actual=130.0,
                status="met_up", note="test",
            )
            for r in pending
        ]
        updated = update_verified(verified)
        assert updated == len(pending)

        # 确认已更新
        rows = get_conditions("2026-08-12")
        assert all(r["status"] == "met_up" for r in rows)
        assert all(r["actual"] == 130.0 for r in rows)


class TestGenerateAndSave:
    def test_generate_and_save_returns_conditions(self, isolated_db):
        from workflow.verification_card import generate_and_save
        conds = generate_and_save(_emotion(), "2026-08-12")
        assert len(conds) >= 5
        assert all(c.date == "2026-08-12" for c in conds)
