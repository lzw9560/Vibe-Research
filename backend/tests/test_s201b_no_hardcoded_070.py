# -*- coding: utf-8 -*-
"""S201b 回归测试：14 个 lift 脚本无硬编码 0.70 cost 常量。

verdict §8 #5：14 脚本（11 需修+3 已修清残留）须无 flat 0.70 作 cost 扣减。
3 类修法：A=6 flat-deduct（换 _cost_pct）/ B=4 gross无扣（加扣）/ C=1 event-flat（传 cost=None）。
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

TOOLS_DIR = Path(__file__).resolve().parents[1] / "tools"

# 14 脚本（spec §8 verdict #5 列举）
SCRIPTS_14 = [
    "lianban_lift.py",
    "gap_window_lift.py",
    "block_trade_lift.py",
    "index_ma20_regime_lift.py",
    "first_board_layer_lift.py",
    "platform_breakout_lift.py",
    "first_plate_h2_lift.py",
    "low_absorption_c3_lift.py",
    "valuation_pe_lift.py",
    "pead_event_study.py",        # midline_pead 的 study 脚本
    "miaoban_superset_31d_lift.py",
    "zt_pool_seal_time_lift.py",
    "midline_st_removal_run.py",  # C-class
    "midline_event_harness.py",   # midline_event harness
]


def _read_script(name: str) -> str:
    p = TOOLS_DIR / name
    if not p.exists():
        return ""
    return p.read_text(encoding="utf-8")


def _has_hardcoded_0_70(text: str) -> bool:
    """检测是否残留硬编码 0.70 作 cost 常量（赋值或 round_trip_cost=0.70）。

    排除：注释行（#）、docstring 中的历史引用。
    """
    for line in text.splitlines():
        stripped = line.strip()
        if stripped.startswith("#"):
            continue
        # 检测赋值 pattern: COST = 0.70 / ROUND_TRIP_COST = 0.70 / COST_PCT = 0.70
        if re.search(r"=\s*0\.70\b", stripped):
            return True
        # 检测 round_trip_cost=0.70 传参
        if re.search(r"round_trip_cost\s*=\s*0\.70\b", stripped):
            return True
        # 检测 COST = 0.0070（分数形式 0.70%）
        if re.search(r"=\s*0\.0070\b", stripped):
            return True
    return False


def test_all_14_scripts_exist():
    """14 脚本都存在。"""
    for name in SCRIPTS_14:
        assert (TOOLS_DIR / name).exists(), f"missing script: {name}"


def test_no_hardcoded_0_70_in_scripts():
    """S201b：14 脚本无硬编码 0.70 cost 常量（含 0.0070 分数形式）。

    verdict §8 #5：降 RTC 0.70→0.15 + 3 类修法（A=6/B=4/C=1）。
    残留 0.70 = mixed-caliber（不 import accounting ROUND_TRIP_COST_PCT）。
    """
    offenders = []
    for name in SCRIPTS_14:
        text = _read_script(name)
        if _has_hardcoded_0_70(text):
            offenders.append(name)
    assert not offenders, (
        f"硬编码 0.70 残留于: {offenders}——须换 _cost_pct 或传 cost=None"
    )


def test_a_class_scripts_import_cost_pct():
    """A=6 flat-deduct 脚本须 import _cost_pct（替代 flat 0.70 扣减）。"""
    a_scripts = [
        "lianban_lift.py",
        "block_trade_lift.py",
        "index_ma20_regime_lift.py",
        "valuation_pe_lift.py",
        "miaoban_superset_31d_lift.py",
        "zt_pool_seal_time_lift.py",
    ]
    for name in a_scripts:
        text = _read_script(name)
        assert "_cost_pct" in text, (
            f"{name} 须 import _cost_pct 替代 flat 0.70（A-class flat-deduct）"
        )


def test_b_class_scripts_deduct_cost():
    """B=4 gross无扣 脚本须加 _cost_pct 扣减（非仅传 round_trip_cost 元数据）。"""
    b_scripts = [
        "platform_breakout_lift.py",
        "first_plate_h2_lift.py",
        "low_absorption_c3_lift.py",
        "first_board_layer_lift.py",
    ]
    for name in b_scripts:
        text = _read_script(name)
        assert "_cost_pct" in text, (
            f"{name} 须加 _cost_pct 扣减（B-class gross-no-deduct）"
        )


def test_c_class_script_passes_cost_none():
    """C=1 event-flat 脚本须传 cost=None（触发 harness 逐笔 _cost_pct）。"""
    text = _read_script("midline_st_removal_run.py")
    assert "COST = None" in text or "cost=None" in text or "cost = None" in text, (
        "midline_st_removal_run.py 须传 cost=None（C-class event-flat）"
    )
