"""Tests for backend/predict/features/behavior.py — S018 behavior/micro feature specs.

TDD: (a)-(g) covering FeatureSpec construction, registration, look-ahead guard,
and pure computation functions (short_term_reversal, abnormal_turnover, day_trip_risk).

All tests are offline (no network calls).
"""

import pytest


# ── (a) 5 个 FeatureSpec 构造合法 ─────────────────────────────────


def test_behavior_specs_count_and_names():
    """BEHAVIOR_SPECS 包含 5 个特征，名称正确。"""
    from predict.features.behavior import BEHAVIOR_SPECS

    assert len(BEHAVIOR_SPECS) == 5
    names = {s.name for s in BEHAVIOR_SPECS}
    assert names == {
        "short_term_reversal",
        "abnormal_turnover",
        "auction_signal",
        "yesterday_limit_today",
        "day_trip_risk",
    }


def test_behavior_specs_compliance_flags():
    """day_trip_risk 的 compliance_flag 是 aggregate_only，其余是 ok。"""
    from predict.features.behavior import BEHAVIOR_SPECS

    flags = {s.name: s.compliance_flag for s in BEHAVIOR_SPECS}
    assert flags["short_term_reversal"] == "ok"
    assert flags["abnormal_turnover"] == "ok"
    assert flags["auction_signal"] == "ok"
    assert flags["yesterday_limit_today"] == "ok"
    assert flags["day_trip_risk"] == "aggregate_only"


def test_behavior_specs_stages():
    """auction_signal stage 是 s3，其余 4 个是 s1。"""
    from predict.features.behavior import BEHAVIOR_SPECS

    stages = {s.name: s.stage for s in BEHAVIOR_SPECS}
    assert stages["short_term_reversal"] == "s1"
    assert stages["abnormal_turnover"] == "s1"
    assert stages["yesterday_limit_today"] == "s1"
    assert stages["day_trip_risk"] == "s1"
    assert stages["auction_signal"] == "s3"


def test_behavior_specs_sources():
    """各特征 source 声明正确。"""
    from predict.features.behavior import BEHAVIOR_SPECS

    sources = {s.name: s.source for s in BEHAVIOR_SPECS}
    assert sources["short_term_reversal"] == "computed"
    assert sources["abnormal_turnover"] == "computed"
    assert sources["auction_signal"] == "astock.em_get"
    assert sources["yesterday_limit_today"] == "limitup_sti"
    assert sources["day_trip_risk"] == "limitup_sti"


def test_behavior_specs_category():
    """全部 5 个特征的 category 都是 behavior。"""
    from predict.features.behavior import BEHAVIOR_SPECS

    for spec in BEHAVIOR_SPECS:
        assert spec.category == "behavior"


def test_behavior_specs_availability_offset():
    """offset 正确：s1 特征 = 0 或 1，s3 特征 = 0。"""
    from predict.features.behavior import BEHAVIOR_SPECS

    offsets = {s.name: s.availability_offset for s in BEHAVIOR_SPECS}
    assert offsets["short_term_reversal"] == 0
    assert offsets["abnormal_turnover"] == 0
    assert offsets["auction_signal"] == 0
    assert offsets["yesterday_limit_today"] == 1
    assert offsets["day_trip_risk"] == 1


def test_behavior_specs_descriptions():
    """所有特征都有非空 description。"""
    from predict.features.behavior import BEHAVIOR_SPECS

    for spec in BEHAVIOR_SPECS:
        assert spec.description and len(spec.description) > 0


# ── (b) register_behavior 注册全 5 个；get_by_name 能取回 ──────────


def test_register_behavior_registers_all_five():
    """register_behavior 把 5 个 spec 注册进新 Registry 实例。"""
    from predict.features.behavior import register_behavior, BEHAVIOR_SPECS
    from predict.features.registry import Registry

    registry = Registry()
    register_behavior(registry)

    for spec in BEHAVIOR_SPECS:
        assert registry.get_by_name(spec.name) is spec


# ── (c) 重复注册同名 raise KeyError ─────────────────────────────────


def test_register_behavior_duplicate_raises():
    """重复注册同名 feature 时 Registry 抛 KeyError。"""
    from predict.features.behavior import register_behavior
    from predict.features.registry import Registry

    registry = Registry()
    register_behavior(registry)
    with pytest.raises(KeyError, match="already registered"):
        register_behavior(registry)


# ── (d) list_for_stage look-ahead 防护 ──────────────────────────────


def test_list_for_stage_s1_excludes_auction():
    """list_for_stage('s1') 包含 4 个 s1 特征，排除 auction_signal（s3）。"""
    from predict.features.behavior import register_behavior
    from predict.features.registry import Registry

    registry = Registry()
    register_behavior(registry)
    s1_names = {s.name for s in registry.list_for_stage("s1")}
    assert "short_term_reversal" in s1_names
    assert "abnormal_turnover" in s1_names
    assert "yesterday_limit_today" in s1_names
    assert "day_trip_risk" in s1_names
    assert "auction_signal" not in s1_names


def test_list_for_stage_s3_includes_all_five():
    """list_for_stage('s3') 包含全部 5 个特征。"""
    from predict.features.behavior import register_behavior
    from predict.features.registry import Registry

    registry = Registry()
    register_behavior(registry)
    s3_names = {s.name for s in registry.list_for_stage("s3")}
    assert s3_names == {
        "short_term_reversal",
        "abnormal_turnover",
        "auction_signal",
        "yesterday_limit_today",
        "day_trip_risk",
    }


# ── (e) short_term_reversal_ret ─────────────────────────────────────


def test_short_term_reversal_ret_normal():
    """正常 5 日累计收益百分数。"""
    from predict.features.behavior import short_term_reversal_ret

    bars = [
        {"close": 10.0},
        {"close": 11.0},
        {"close": 12.0},
        {"close": 13.0},
        {"close": 14.0},
        {"close": 15.0},
    ]
    # (15 - 10) / 10 * 100 = 50.0%
    assert short_term_reversal_ret(bars, window=5) == 50.0


def test_short_term_reversal_ret_insufficient_bars():
    """bars 不足 window+1 返回 None。"""
    from predict.features.behavior import short_term_reversal_ret

    bars = [
        {"close": 10.0},
        {"close": 11.0},
    ]
    assert short_term_reversal_ret(bars, window=5) is None


def test_short_term_reversal_ret_window_1():
    """window=1 时取最后 1 日收益。"""
    from predict.features.behavior import short_term_reversal_ret

    bars = [
        {"close": 10.0},
        {"close": 11.0},
    ]
    # (11 - 10) / 10 * 100 = 10.0%
    assert short_term_reversal_ret(bars, window=1) == 10.0


def test_short_term_reversal_ret_window_3():
    """window=3 时取最后 3 日累计收益。"""
    from predict.features.behavior import short_term_reversal_ret

    bars = [
        {"close": 10.0},
        {"close": 11.0},
        {"close": 12.0},
        {"close": 13.0},
    ]
    # (13 - 10) / 10 * 100 = 30.0%
    assert short_term_reversal_ret(bars, window=3) == 30.0


def test_short_term_reversal_ret_empty():
    """空 bars 返回 None。"""
    from predict.features.behavior import short_term_reversal_ret

    assert short_term_reversal_ret([]) is None


def test_short_term_reversal_ret_none_close():
    """参与计算的某根 bar 缺少 close 时返回 None（不抛异常）。"""
    from predict.features.behavior import short_term_reversal_ret

    # window=1 需要 2 根 bar，最后一根缺少 close
    bars = [
        {"close": 10.0},
        {"open": 9.0},
    ]
    assert short_term_reversal_ret(bars, window=1) is None


# ── (f) abnormal_turnover_ratio ─────────────────────────────────────


def test_abnormal_turnover_ratio_normal():
    """正常量比计算 = 当日 / 前 avg_window 日均量。"""
    from predict.features.behavior import abnormal_turnover_ratio

    # 6 个元素：当日=60, 前 5 日=[10,20,30,40,50], 均量=30, 量比=2.0
    volumes = [10.0, 20.0, 30.0, 40.0, 50.0, 60.0]
    assert abnormal_turnover_ratio(volumes, avg_window=5) == 60.0 / 30.0


def test_abnormal_turnover_ratio_with_nones():
    """含 None 时跳过 None 计算均量。"""
    from predict.features.behavior import abnormal_turnover_ratio

    # 6 个元素：当日=60, 前 5 日=[10,None,30,40,50], 有效=[10,30,40,50], 均量=32.5
    volumes = [10.0, None, 30.0, 40.0, 50.0, 60.0]
    expected = 60.0 / 32.5
    result = abnormal_turnover_ratio(volumes, avg_window=5)
    assert result is not None
    assert abs(result - expected) < 1e-9


def test_abnormal_turnover_ratio_insufficient():
    """不足 avg_window+1 个元素返回 None。"""
    from predict.features.behavior import abnormal_turnover_ratio

    volumes = [10.0, 20.0]
    assert abnormal_turnover_ratio(volumes, avg_window=5) is None


def test_abnormal_turnover_ratio_all_none():
    """全 None 返回 None。"""
    from predict.features.behavior import abnormal_turnover_ratio

    volumes = [None, None, None, None, None, None, None]
    assert abnormal_turnover_ratio(volumes, avg_window=5) is None


def test_abnormal_turnover_ratio_window_1():
    """window=1 时只用 1 个前日值。"""
    from predict.features.behavior import abnormal_turnover_ratio

    volumes = [10.0, 20.0, 30.0]
    # 当日=30, 前 1 日=20.0, 量比=30/20=1.5
    assert abnormal_turnover_ratio(volumes, avg_window=1) == 1.5


def test_abnormal_turnover_ratio_empty():
    """空 volumes 返回 None。"""
    from predict.features.behavior import abnormal_turnover_ratio

    assert abnormal_turnover_ratio([]) is None


# ── (g) day_trip_risk_score ────────────────────────────────────────


def test_day_trip_risk_all_one_day():
    """全部 hold_days <= 1 时返回 1.0。"""
    from predict.features.behavior import day_trip_risk_score

    seat_records = [
        {"hold_days": 1}, {"hold_days": 0}, {"hold_days": 1}
    ]
    assert day_trip_risk_score(seat_records) == 1.0


def test_day_trip_risk_all_long_hold():
    """全部 hold_days > 1 时返回 0.0。"""
    from predict.features.behavior import day_trip_risk_score

    seat_records = [
        {"hold_days": 2}, {"hold_days": 5}, {"hold_days": 3}
    ]
    assert day_trip_risk_score(seat_records) == 0.0


def test_day_trip_risk_empty_list():
    """空列表返回 None。"""
    from predict.features.behavior import day_trip_risk_score

    assert day_trip_risk_score([]) is None


def test_day_trip_risk_all_none():
    """全部 hold_days 为 None 返回 None。"""
    from predict.features.behavior import day_trip_risk_score

    seat_records = [
        {"hold_days": None}, {"hold_days": None}
    ]
    assert day_trip_risk_score(seat_records) is None


def test_day_trip_risk_mixed():
    """混合占比正确：2/5 <=1，3/5 >1，结果 = 0.4。"""
    from predict.features.behavior import day_trip_risk_score

    seat_records = [
        {"hold_days": 1},    # <=1
        {"hold_days": 0},    # <=1
        {"hold_days": 3},    # >1
        {"hold_days": None}, # ignored
        {"hold_days": 5},    # >1
    ]
    # total_valid = 4, count <=1 = 2
    # 2/4 = 0.5
    assert day_trip_risk_score(seat_records) == 0.5


def test_day_trip_risk_all_hold_days_present():
    """确保函数接受 dict 列表，key 是 hold_days。"""
    from predict.features.behavior import day_trip_risk_score

    seat_records = [
        {"hold_days": 1},
        {"hold_days": 2},
        {"hold_days": 3},
    ]
    # 1 <= 1, 2 > 1, 3 > 1  -> 1/3
    assert day_trip_risk_score(seat_records) == 1.0 / 3.0
