# -*- coding: utf-8 -*-
"""test_tactics_ice_point_detector —— 冰点检测测试（S235 T05 辅助）。AAA 结构。"""
from __future__ import annotations
import pytest

from tactics.ice_point_detector import IcePointDetector


def _fake_runner(total: int):
    """返回固定 pagination.total 的 fake CLI runner。"""
    return lambda: {"ok": True, "data": {"pagination": {"total": total}}}


@pytest.fixture
def detector(tmp_path):
    # 注入 fake runner（默认跌停 0），db 用 tmp_path 隔离
    return IcePointDetector(db_path=tmp_path / "ice.db", runner=_fake_runner(0))


# ---------------------------------------------------------------------------
# count_limit_down
# ---------------------------------------------------------------------------

def test_count_limit_down_parses_total(detector):
    d = IcePointDetector(db_path=detector.db_path, runner=_fake_runner(80))
    assert d.count_limit_down() == 80


def test_count_limit_down_bad_payload_returns_zero(detector):
    # ok=False / 缺 pagination / 非 dict → 0
    assert IcePointDetector(db_path=detector.db_path, runner=lambda: {"ok": False}).count_limit_down() == 0
    assert IcePointDetector(db_path=detector.db_path, runner=lambda: {"ok": True, "data": {}}).count_limit_down() == 0
    assert IcePointDetector(db_path=detector.db_path, runner=lambda: None).count_limit_down() == 0


# ---------------------------------------------------------------------------
# is_ice_point
# ---------------------------------------------------------------------------

def test_is_ice_point_first_day_false(detector):
    # 首日无历史 → False（不臆造）
    assert detector.is_ice_point() is False


def test_is_ice_point_two_consecutive_days_above_50(tmp_path):
    # Arrange: 连续 2 日跌停 > 50
    d = IcePointDetector(db_path=tmp_path / "ice.db", runner=_fake_runner(60))
    d.record_today(today="2026-10-06")
    d2 = IcePointDetector(db_path=tmp_path / "ice.db", runner=_fake_runner(55))
    # Act
    d2.record_today(today="2026-10-07")
    # Assert
    assert d2.is_ice_point() is True


def test_is_ice_point_one_day_below_50(tmp_path):
    # 第 2 日跌停 40（< 50）→ 非冰点
    d = IcePointDetector(db_path=tmp_path / "ice.db", runner=_fake_runner(60))
    d.record_today(today="2026-10-06")
    d2 = IcePointDetector(db_path=tmp_path / "ice.db", runner=_fake_runner(40))
    d2.record_today(today="2026-10-07")
    assert d2.is_ice_point() is False


def test_is_ice_point_threshold_strict_above_50(tmp_path):
    # 正好 50 → 不算（> 严格）
    d = IcePointDetector(db_path=tmp_path / "ice.db", runner=_fake_runner(50))
    d.record_today(today="2026-10-06")
    d2 = IcePointDetector(db_path=tmp_path / "ice.db", runner=_fake_runner(50))
    d2.record_today(today="2026-10-07")
    assert d2.is_ice_point() is False


# ---------------------------------------------------------------------------
# is_ice_point_today（记录 + 判定一体）
# ---------------------------------------------------------------------------

def test_is_ice_point_today_first_day_false(detector):
    # 首日记录但只有 1 日历史 → False
    d = IcePointDetector(db_path=detector.db_path, runner=_fake_runner(60))
    assert d.is_ice_point_today(today="2026-10-07") is False


def test_is_ice_point_today_second_day_true(tmp_path):
    # 第 1 日记录 60，第 2 日 is_ice_point_today 记录 60 → True
    d1 = IcePointDetector(db_path=tmp_path / "ice.db", runner=_fake_runner(60))
    d1.record_today(today="2026-10-06")
    d2 = IcePointDetector(db_path=tmp_path / "ice.db", runner=_fake_runner(60))
    assert d2.is_ice_point_today(today="2026-10-07") is True


def test_record_today_replaces_same_date(tmp_path):
    # 同日重复记录 → INSERT OR REPLACE 覆盖（不堆叠）
    d = IcePointDetector(db_path=tmp_path / "ice.db", runner=_fake_runner(60))
    d.record_today(today="2026-10-07")
    d2 = IcePointDetector(db_path=tmp_path / "ice.db", runner=_fake_runner(70))
    d2.record_today(today="2026-10-07")
    # 仍只有 1 日历史
    assert d2.is_ice_point() is False
