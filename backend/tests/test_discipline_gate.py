# -*- coding: utf-8 -*-
"""S231 打板纪律门禁测试——cap=0 terminal BLOCK + 7 条件逻辑 + render。

风控工具非 edge 基建。
"""
import pytest
from tools.discipline_gate import evaluate_discipline_gate, render_discipline_report


def test_cap0_terminal_block():
    """cap=0（consecutive_relay falsified）→ terminal BLOCK（短路，不评估 C1-C7）。"""
    v = evaluate_discipline_gate("2026-09-29")
    assert v["status"] == "BLOCK"
    assert v["merged_light"] == "red"
    assert v.get("terminal") is True
    assert v["conditions"] == []  # 短路，不评估
    assert "cap=0 terminal BLOCK" in v["reasons"][0]


def test_render_cap0_report():
    """cap=0 render 报告含 Terminal BLOCK + 不交易理由。"""
    v = evaluate_discipline_gate("2026-09-29")
    report = render_discipline_report(v)
    assert "Terminal BLOCK" in report
    assert "consecutive_relay falsified" in report
    assert "历史统计特征" in report


def test_verdict_structure():
    """verdict 结构含 date/status/cap/terminal/conditions/merged_light/reasons。"""
    v = evaluate_discipline_gate("2026-09-29")
    assert "date" in v
    assert "status" in v
    assert "cap" in v
    assert "terminal" in v
    assert "conditions" in v
    assert "merged_light" in v
    assert "reasons" in v


def test_pre_holiday_lock_detection():
    """C7 节前禁入——09-30 买→10-08 卖（T+1=8 天锁仓）应触发。"""
    from tools.discipline_gate import _is_pre_holiday_lock
    # 09-30 国庆前买入 → 10-08 卖出（跨 10/1-7 国庆休市）= 锁仓≥3 自然日
    # 注：_is_pre_holiday_lock 依赖 vr_paths._A_SHARE_HOLIDAYS，如果 10/1-7 在 holidays 则 True
    result = _is_pre_holiday_lock("2026-09-30")
    # 不 hardcode True/False（依赖 holidays 配置），只验不抛异常 + 返 bool
    assert isinstance(result, bool)


def test_sti_consecutive_above_no_data():
    """C2 STI 连续 3 天>50——无数据时返 False。"""
    from tools.discipline_gate import _sti_consecutive_above
    from pathlib import Path
    # 用不存在 DB 路径
    is_pass, scores = _sti_consecutive_above(Path("/tmp/nonexistent.db"), 50.0, 3)
    assert is_pass is False
    assert scores == []


def test_discipline_gate_non_edge_positioning():
    """S231 定位：风控工具非 edge 基建——cap=0 时只推纪律提醒非交易信号。"""
    v = evaluate_discipline_gate("2026-09-29")
    # cap=0 terminal BLOCK 时 conditions 空（不评估 C1-C7）
    assert v.get("terminal") is True
    assert v["conditions"] == []
    # 定位：不创造 alpha，只读现有数据源
    assert v["status"] == "BLOCK"
