# -*- coding: utf-8 -*-
"""test_tactics_s234_bridge —— S234 filter 接线测试（S235 T18）。AAA 结构。"""
from __future__ import annotations
import pytest

from tactics.s234_bridge import apply_s234_filter, should_suppress, TACTIC_TO_S234


def _fake_filter_pass(code, s234_tactic):
    """模拟 filter_stock 通过（Pass）。"""
    return {
        "code": code, "is_passed": True, "safe_action": "Pass",
        "verdict": "✅ ok", "tactic": s234_tactic,
    }


def _fake_filter_block(code, s234_tactic):
    """模拟 filter_stock 拦截（Block）。"""
    return {
        "code": code, "is_passed": False, "safe_action": "Block",
        "verdict": "🔴 falsified", "tactic": s234_tactic,
    }


def _fake_filter_raise(code, s234_tactic):
    raise RuntimeError("filter boom")


# ---------------------------------------------------------------------------
# 映射表
# ---------------------------------------------------------------------------

def test_tactic_mapping():
    assert TACTIC_TO_S234["reversal"] == "战法1_弱转强"
    assert TACTIC_TO_S234["tail_breakout"] == "战法2_尾盘锁定"
    assert TACTIC_TO_S234["ice_rebound"] is None


# ---------------------------------------------------------------------------
# apply_s234_filter
# ---------------------------------------------------------------------------

def test_reversal_passes_filter():
    r = apply_s234_filter("603778", "reversal", _fake_filter_pass)
    assert r["safe_action"] == "Pass"
    assert r["s235_tactic"] == "reversal"
    # filter_fn 被以 S234 战法名调用
    assert r["tactic"] == "战法1_弱转强"


def test_tail_breakout_blocks():
    r = apply_s234_filter("000001", "tail_breakout", _fake_filter_block)
    assert r["safe_action"] == "Block"
    assert r["s235_tactic"] == "tail_breakout"
    assert r["tactic"] == "战法2_尾盘锁定"


def test_ice_rebound_no_s234_mapping():
    # ice_rebound 无 S234 对应 → 直接 Pass，不调 filter_fn
    called = []
    def filter_fn(c, t):
        called.append((c, t))
        return {"safe_action": "Pass"}
    r = apply_s234_filter("603778", "ice_rebound", filter_fn)
    assert r["safe_action"] == "Pass"
    assert "冰点反抽" in r["verdict"]
    assert called == []  # filter_fn 未被调用


def test_filter_exception_degrades_to_pass():
    # filter_fn 抛异常 → 降级 Pass，verdict 标异常
    r = apply_s234_filter("603778", "reversal", _fake_filter_raise)
    assert r["safe_action"] == "Pass"
    assert "filter 异常" in r["verdict"]
    assert r["s235_tactic"] == "reversal"


def test_unknown_tactic_degrades_to_pass():
    # 未知 tactic → TACTIC_TO_S234.get 返 None → ice_rebound 分支
    r = apply_s234_filter("603778", "nonexistent", _fake_filter_pass)
    assert r["safe_action"] == "Pass"
    assert "冰点反抽" in r["verdict"]


# ---------------------------------------------------------------------------
# should_suppress
# ---------------------------------------------------------------------------

def test_should_suppress_block():
    assert should_suppress({"safe_action": "Block"}) is True


def test_should_suppress_refuse():
    assert should_suppress({"safe_action": "Refuse"}) is True


def test_should_suppress_pass():
    assert should_suppress({"safe_action": "Pass"}) is False


def test_should_suppress_missing_action():
    assert should_suppress({}) is False


def test_should_suppress_case_insensitive():
    assert should_suppress({"safe_action": "block"}) is True
    assert should_suppress({"safe_action": "BLOCK"}) is True


# ---------------------------------------------------------------------------
# 集成：Block → 压制，Pass → 不压制
# ---------------------------------------------------------------------------

def test_integration_block_suppresses():
    r = apply_s234_filter("603778", "tail_breakout", _fake_filter_block)
    assert should_suppress(r) is True  # Block → 压制不推送


def test_integration_pass_does_not_suppress():
    r = apply_s234_filter("603778", "reversal", _fake_filter_pass)
    assert should_suppress(r) is False  # Pass → 推送


def test_integration_ice_rebound_not_suppressed():
    r = apply_s234_filter("603778", "ice_rebound", _fake_filter_pass)
    assert should_suppress(r) is False  # 冰点反抽 Pass
