# -*- coding: utf-8 -*-
"""S085 A1 — seal_amount 接线单测。

修复：build_indicator_set 不设 ind.seal_amount → 八项标准⑥(_check_seal_ratio) 恒 missing
→ fail_count 偏置 → capped 判定偏（capped = fail_count>=3 → 选股池得分封顶 55）。
正解：build_diagnosis_card 内 check_eight_standards 之前，从 pool_item.fund（封单额，元）
注入 ind.seal_amount。命名碰撞守护：用 pool_item.get("fund")（封单额）非 fund 参数（资金流）。

承重：改 seal_amount 会改 ⑥ status → 改 fail_count → 改 capped。零回溯影响（capped 是 run 时判定，
不进历史 DB），但要回归确认 final_candidates 血脉不破。
单位：fund（封单额，元）+ float_market_cap（元）→ ratio = sa/fmc 无量纲，阈值 1%（EIGHT_STANDARD_SEAL_RATIO_MIN）。
"""
from __future__ import annotations

from datetime import datetime

from candidate_funnel.diagnosis import build_diagnosis_card
from candidate_funnel.models import BaseThreshold, IndicatorSet


def _mk_ind(float_market_cap: float | None = 2.0e10) -> IndicatorSet:
    return IndicatorSet(code="600519", name="贵州茅台", float_market_cap=float_market_cap)


def test_seal_amount_wired_from_pool_fund():
    """pool_item 含 fund → ind.seal_amount = float(fund)。"""
    # Act
    card = build_diagnosis_card(
        "600519", "贵州茅台", _mk_ind(), BaseThreshold(), market_ctx=None,
        as_of=datetime.now(), pool_item={"fund": 1.5e8},
    )
    # Assert
    assert card.indicators.seal_amount == 1.5e8


def test_seal_amount_handles_str_fund():
    """fund 可能是 str 数字（东财 raw）→ 转 float。"""
    card = build_diagnosis_card(
        "600519", "贵州茅台", _mk_ind(), BaseThreshold(), market_ctx=None,
        as_of=datetime.now(), pool_item={"fund": "12345.6"},
    )
    assert card.indicators.seal_amount == 12345.6


def test_seal_amount_none_when_pool_item_none():
    """非涨停股 pool_item=None → seal_amount=None（⑥ missing，正确——⑥仅对涨停股有意义）。"""
    card = build_diagnosis_card(
        "600519", "贵州茅台", _mk_ind(), BaseThreshold(), market_ctx=None,
        as_of=datetime.now(), pool_item=None,
    )
    assert card.indicators.seal_amount is None


def test_seal_amount_none_when_fund_missing_or_dash():
    """pool_item 无 fund 键 / "-" / None / "" → seal_amount=None（不臆造）。
    注：fund=0 是合法值（封单额 0 → ratio 0 → ⑥fail，非 missing），不在此列。"""
    for fund in (None, "-", ""):
        card = build_diagnosis_card(
            "600519", "贵州茅台", _mk_ind(), BaseThreshold(), market_ctx=None,
            as_of=datetime.now(), pool_item={"fund": fund} if fund is not None else {},
        )
        assert card.indicators.seal_amount is None, f"fund={fund!r} 应 → None"
    # fund=0（合法值）→ 0.0（非 None）
    card0 = build_diagnosis_card(
        "600519", "贵州茅台", _mk_ind(), BaseThreshold(), market_ctx=None,
        as_of=datetime.now(), pool_item={"fund": 0},
    )
    assert card0.indicators.seal_amount == 0.0


def test_seal_amount_wiring_fixes_standard_6_not_missing():
    """接线后 ⑥ 不再恒 missing——有 fund + fmc → ⑥ pass/fail（非 missing）。"""
    # fund=2e8, fmc=2e10 → ratio=0.01 = 1%，阈值 >1% → fail（但不 missing）
    card = build_diagnosis_card(
        "600519", "贵州茅台", _mk_ind(float_market_cap=2.0e10), BaseThreshold(),
        market_ctx=None, as_of=datetime.now(), pool_item={"fund": 2.0e8},
    )
    six = next(it for it in card.eight_standards.items if it.key == "6")
    assert six.status in ("pass", "fail"), f"⑥ 接线后应为 pass/fail，实得 {six.status}"
    assert six.status != "missing", "⑥ 接线后不应再 missing"


def test_seal_amount_high_ratio_passes_standard_6():
    """封单 > 流通市值 1% → ⑥ pass（接线后正向判定成立，非反向 bias）。"""
    # fund=5e8, fmc=2e10 → ratio=0.025=2.5% > 1% → pass
    card = build_diagnosis_card(
        "600519", "贵州茅台", _mk_ind(float_market_cap=2.0e10), BaseThreshold(),
        market_ctx=None, as_of=datetime.now(), pool_item={"fund": 5.0e8},
    )
    six = next(it for it in card.eight_standards.items if it.key == "6")
    assert six.status == "pass", f"ratio 2.5% 应 pass，实得 {six.status} actual={six.actual}"


def test_seal_amount_not_from_fund_source_param():
    """命名碰撞守护：seal_amount 只从 pool_item.fund（封单额）来，
    不从 build_indicator_set 的 fund 参数（资金流 dict）误取。
    build_diagnosis_card 接收已构造 ind，fund source 不在它的 scope——
    构造 ind 时 fund source 含 main_net_inflow 等，但 seal_amount 必来自 pool_item。
    """
    ind = _mk_ind()
    # ind 的 fund source 字段（main_net_inflow）有值，但 seal_amount 须来自 pool_item
    ind.main_net_inflow = 999.0  # 资金流（万元），非封单额
    card = build_diagnosis_card(
        "600519", "贵州茅台", ind, BaseThreshold(), market_ctx=None,
        as_of=datetime.now(), pool_item={"fund": 1.5e8},
    )
    # seal_amount = pool_item.fund（1.5e8），不是 main_net_inflow（999）
    assert card.indicators.seal_amount == 1.5e8
    assert card.indicators.main_net_inflow == 999.0  # 资金流不受污染
