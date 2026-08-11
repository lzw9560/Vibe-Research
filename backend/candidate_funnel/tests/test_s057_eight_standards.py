# -*- coding: utf-8 -*-
"""S057：八项标准三态判定纯函数单测。

覆盖：八项各条件边界值 + missing 三态 + 未过数计数 + 封顶触发/不触发。
"""

import pytest

from candidate_funnel.eight_standards import check_eight_standards
from candidate_funnel.models import IndicatorSet


def _ind(**overrides) -> IndicatorSet:
    """构造测试用 IndicatorSet，默认全 None（→ missing）。"""
    base = {"code": "000001", "name": "测试"}
    base.update(overrides)
    return IndicatorSet(**base)


class TestSingleStandards:
    def test_float_cap_pass(self):
        ind = _ind(float_market_cap=80e8)  # 80 亿，在 30-150 区间
        r = check_eight_standards(ind, {})
        item = next(i for i in r.items if i.key == "1")
        assert item.status == "pass"
        assert "80.00亿" in (item.actual or "")

    def test_float_cap_fail_too_small(self):
        ind = _ind(float_market_cap=20e8)  # 20 亿，低于 30
        r = check_eight_standards(ind, {})
        item = next(i for i in r.items if i.key == "1")
        assert item.status == "fail"

    def test_float_cap_fail_too_big(self):
        ind = _ind(float_market_cap=200e8)
        r = check_eight_standards(ind, {})
        item = next(i for i in r.items if i.key == "1")
        assert item.status == "fail"

    def test_float_cap_missing(self):
        ind = _ind()
        r = check_eight_standards(ind, {})
        item = next(i for i in r.items if i.key == "1")
        assert item.status == "missing"

    def test_turnover_pass(self):
        ind = _ind(turnover_pct=10.0)
        r = check_eight_standards(ind, {})
        item = next(i for i in r.items if i.key == "2")
        assert item.status == "pass"

    def test_turnover_fail_low(self):
        ind = _ind(turnover_pct=3.0)
        r = check_eight_standards(ind, {})
        item = next(i for i in r.items if i.key == "2")
        assert item.status == "fail"

    def test_turnover_fail_high(self):
        ind = _ind(turnover_pct=25.0)
        r = check_eight_standards(ind, {})
        item = next(i for i in r.items if i.key == "2")
        assert item.status == "fail"

    def test_vol_ratio_pass(self):
        ind = _ind(vol_ratio=2.0)
        r = check_eight_standards(ind, {})
        item = next(i for i in r.items if i.key == "3")
        assert item.status == "pass"

    def test_vol_ratio_fail(self):
        ind = _ind(vol_ratio=1.0)
        r = check_eight_standards(ind, {})
        item = next(i for i in r.items if i.key == "3")
        assert item.status == "fail"

    def test_seal_time_pass(self):
        ind = _ind()
        r = check_eight_standards(ind, {"first_seal_time": "09:35"})
        item = next(i for i in r.items if i.key == "4")
        assert item.status == "pass"

    def test_seal_time_fail(self):
        ind = _ind()
        r = check_eight_standards(ind, {"first_seal_time": "11:00"})
        item = next(i for i in r.items if i.key == "4")
        assert item.status == "fail"

    def test_seal_time_missing(self):
        ind = _ind()
        r = check_eight_standards(ind, {})
        item = next(i for i in r.items if i.key == "4")
        assert item.status == "missing"

    def test_reopens_pass(self):
        ind = _ind()
        r = check_eight_standards(ind, {"open_count": 0})
        item = next(i for i in r.items if i.key == "5")
        assert item.status == "pass"

    def test_reopens_fail(self):
        ind = _ind()
        r = check_eight_standards(ind, {"open_count": 3})
        item = next(i for i in r.items if i.key == "5")
        assert item.status == "fail"

    def test_seal_ratio_pass(self):
        ind = _ind(seal_amount=2e8, float_market_cap=100e8)  # 2% > 1%
        r = check_eight_standards(ind, {})
        item = next(i for i in r.items if i.key == "6")
        assert item.status == "pass"

    def test_seal_ratio_fail(self):
        ind = _ind(seal_amount=0.5e8, float_market_cap=100e8)  # 0.5% < 1%
        r = check_eight_standards(ind, {})
        item = next(i for i in r.items if i.key == "6")
        assert item.status == "fail"

    def test_seal_ratio_missing(self):
        ind = _ind()  # 缺 seal_amount + float_market_cap
        r = check_eight_standards(ind, {})
        item = next(i for i in r.items if i.key == "6")
        assert item.status == "missing"

    def test_hot_sector_pass(self):
        ind = _ind(concepts=["AI"])
        ctx = {"hot_sectors": [{"name": "AI"}, {"name": "芯片"}]}
        r = check_eight_standards(ind, ctx)
        item = next(i for i in r.items if i.key == "7")
        assert item.status == "pass"

    def test_hot_sector_fail(self):
        ind = _ind(concepts=["白酒"])
        ctx = {"hot_sectors": [{"name": "AI"}, {"name": "芯片"}]}
        r = check_eight_standards(ind, ctx)
        item = next(i for i in r.items if i.key == "7")
        assert item.status == "fail"

    def test_hot_sector_missing_no_sectors(self):
        ind = _ind(concepts=["AI"])
        r = check_eight_standards(ind, {})
        item = next(i for i in r.items if i.key == "7")
        assert item.status == "missing"

    def test_price_position_low_first_board(self):
        ind = _ind(consec_boards=1)
        r = check_eight_standards(ind, {})
        item = next(i for i in r.items if i.key == "8")
        assert item.status == "pass"

    def test_price_position_breakout(self):
        ind = _ind(consec_boards=3, price=10.0, ma20=9.0)
        r = check_eight_standards(ind, {})
        item = next(i for i in r.items if i.key == "8")
        assert item.status == "pass"

    def test_price_position_fail(self):
        ind = _ind(consec_boards=3, price=8.0, ma20=10.0)
        r = check_eight_standards(ind, {})
        item = next(i for i in r.items if i.key == "8")
        assert item.status == "fail"


class TestEightStandardResult:
    def test_all_pass(self):
        ind = _ind(
            float_market_cap=80e8,
            turnover_pct=10.0,
            vol_ratio=2.0,
            seal_amount=2e8,
            concepts=["AI"],
            consec_boards=1,
        )
        ctx = {"first_seal_time": "09:35", "open_count": 0, "hot_sectors": [{"name": "AI"}]}
        r = check_eight_standards(ind, ctx)
        assert r.fail_count == 0
        assert r.missing_count == 0
        assert len(r.items) == 8

    def test_three_fails_triggers_cap(self):
        ind = _ind(
            float_market_cap=20e8,  # fail ①
            turnover_pct=3.0,  # fail ②
            vol_ratio=1.0,  # fail ③
            seal_amount=2e8,
            concepts=["AI"],
            consec_boards=1,
        )
        ctx = {"first_seal_time": "09:35", "open_count": 0, "hot_sectors": [{"name": "AI"}]}
        r = check_eight_standards(ind, ctx)
        assert r.fail_count == 3
        assert r.missing_count == 0

    def test_missing_not_counted_as_fail(self):
        ind = _ind()  # 全 None → 全 missing
        r = check_eight_standards(ind, {})
        assert r.fail_count == 0
        assert r.missing_count == 8

    def test_two_fails_no_cap(self):
        ind = _ind(
            float_market_cap=20e8,  # fail ①
            turnover_pct=3.0,  # fail ②
            vol_ratio=2.0,
            seal_amount=2e8,
            concepts=["AI"],
            consec_boards=1,
        )
        ctx = {"first_seal_time": "09:35", "open_count": 0, "hot_sectors": [{"name": "AI"}]}
        r = check_eight_standards(ind, ctx)
        assert r.fail_count == 2
        assert r.missing_count == 0


class TestDiagnosisCardIntegration:
    def test_build_diagnosis_card_populates_eight_standards(self):
        from candidate_funnel.diagnosis import build_diagnosis_card
        from candidate_funnel.models import BaseThreshold

        ind = _ind(
            float_market_cap=80e8,
            turnover_pct=10.0,
            vol_ratio=2.0,
            seal_amount=2e8,
            concepts=["AI"],
            consec_boards=1,
        )
        ctx = {"first_seal_time": "09:35", "open_count": 0, "hot_sectors": [{"name": "AI"}]}
        card = build_diagnosis_card("000001", "测试", ind, BaseThreshold(), market_ctx=ctx)
        assert card.eight_standards is not None
        assert card.eight_standards.fail_count == 0
        assert card.capped is False
        assert card.cap_reason is None

    def test_build_diagnosis_card_capped_when_three_fails(self):
        from candidate_funnel.diagnosis import build_diagnosis_card
        from candidate_funnel.models import BaseThreshold

        ind = _ind(
            float_market_cap=20e8,  # fail
            turnover_pct=3.0,  # fail
            vol_ratio=1.0,  # fail
            seal_amount=2e8,
            concepts=["AI"],
            consec_boards=1,
        )
        ctx = {"first_seal_time": "09:35", "open_count": 0, "hot_sectors": [{"name": "AI"}]}
        card = build_diagnosis_card("000001", "测试", ind, BaseThreshold(), market_ctx=ctx)
        assert card.capped is True
        assert card.cap_reason is not None
        assert "55" in card.cap_reason
