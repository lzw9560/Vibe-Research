# -*- coding: utf-8 -*-
"""S203 T7 QMT 模板验收 test。

验 4 模板在 specs/S203/templates/ 不进 backend/ + BLOCKER 标注 +
seal_ratio Vibe 侧可做（走 em_get 不裸调 requests）+ big_loss 复用 T6。
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

TEMPLATES_DIR = (
    Path(__file__).resolve().parents[2]
    / "specs"
    / "S203-龙头战法数字化改造"
    / "templates"
)
sys.path.insert(0, str(TEMPLATES_DIR))


def test_templates_in_specs():
    """验收 1：4 模板在 specs/S203/templates/ 不进 backend/。"""
    expected = {
        "board_hit_trigger.py",
        "vwap_stop.py",
        "seal_ratio_monitor.py",
        "big_loss_breaker.py",
    }
    actual = {f.name for f in TEMPLATES_DIR.glob("*.py")}
    assert expected == actual, f"缺: {expected - actual}, 多: {actual - expected}"
    backend_dir = Path(__file__).resolve().parents[2] / "backend"
    for name in expected:
        assert not (backend_dir / name).exists(), f"{name} 不该进 backend/"


def test_blocker_marked():
    """验收 2：board_hit_trigger/vwap_stop 标 BLOCKER（Vibe 无 xtquant/mootdx tick 实时）。"""
    board_hit = (TEMPLATES_DIR / "board_hit_trigger.py").read_text(encoding="utf-8")
    vwap_stop = (TEMPLATES_DIR / "vwap_stop.py").read_text(encoding="utf-8")
    assert "BLOCKER" in board_hit, "board_hit_trigger.py 须标 BLOCKER（需 xtquant+L2）"
    assert "BLOCKER" in vwap_stop, "vwap_stop.py 须标 BLOCKER（需 mootdx tick 实时）"
    # Vibe 侧不可实现的 trigger 函数须 NotImplementedError
    assert "NotImplementedError" in board_hit
    assert "NotImplementedError" in vwap_stop


def test_seal_ratio_vibe_side():
    """验收 3：seal_ratio_monitor 可 Vibe 侧跑（em_get 涨停池有 seal_amount+amount）。"""
    src = (TEMPLATES_DIR / "seal_ratio_monitor.py").read_text(encoding="utf-8")
    # Vibe 侧可做（不标 BLOCKER）
    assert "BLOCKER" not in src, "seal_ratio_monitor Vibe 侧可做，不标 BLOCKER"
    # 走 em_get 防封（不裸调 requests）
    assert "em_get" in src or "em_zt_topic_pool" in src, "须走 em_get/涨停池不裸调 requests"
    # 纯函数可测
    import seal_ratio_monitor

    # 薄封单 2.5% < 5% → 预警
    alert = seal_ratio_monitor.evaluate_seal_ratio(
        code="600519",
        trade_date="2026-09-17",
        seal_amount=5_000_000,
        amount=200_000_000,
    )
    assert alert.seal_ratio == pytest.approx(0.025)
    assert alert.is_thin_seal is True
    # 厚封单 10% > 5% → 不预警
    alert2 = seal_ratio_monitor.evaluate_seal_ratio(
        code="600519",
        trade_date="2026-09-17",
        seal_amount=20_000_000,
        amount=200_000_000,
    )
    assert alert2.seal_ratio == pytest.approx(0.1)
    assert alert2.is_thin_seal is False
    # amount=0 不报错（守不臆造）
    alert3 = seal_ratio_monitor.evaluate_seal_ratio(
        code="600519", trade_date="2026-09-17", seal_amount=0, amount=0
    )
    assert alert3.seal_ratio == 0.0


def test_big_loss_reuses_t6():
    """验收 4：big_loss_breaker 复用 T6 intraday_loss_breaker。"""
    src = (TEMPLATES_DIR / "big_loss_breaker.py").read_text(encoding="utf-8")
    # 复用 T6（import risk.intraday_loss_breaker）
    assert "intraday_loss_breaker" in src, "须复用 T6 intraday_loss_breaker"
    assert "evaluate_loss_breaker" in src
    assert "intraday_multiplier" in src
    assert "compute_final_size" in src
    # 实际调用（复用 T6 纯函数，可运行）
    import big_loss_breaker

    # 单笔>5% → 禁加仓 → final_size=0
    state, final = big_loss_breaker.enforce_loss_breaker(
        code="600519",
        date="2026-09-17",
        realized_loss_pct=-6.0,
        total_account_loss_pct=-3.0,
        arm_size=100,
    )
    assert state.is_blocked_add is True  # 单笔 6% > 5%
    assert state.is_blocked_new is False  # 合计 3% < 8%
    assert final == 0.0  # intraday_mult=0 → 禁加仓
    # 合计>8% → 禁全账户新仓 → final_size=0
    state2, final2 = big_loss_breaker.enforce_loss_breaker(
        code="600519",
        date="2026-09-17",
        realized_loss_pct=-3.0,
        total_account_loss_pct=-9.0,
        arm_size=100,
    )
    assert state2.is_blocked_new is True  # 合计 9% > 8%
    assert final2 == 0.0  # 全账户熔断
    # 正常 → 放行 → final_size=arm_size
    state3, final3 = big_loss_breaker.enforce_loss_breaker(
        code="600519",
        date="2026-09-17",
        realized_loss_pct=-2.0,
        total_account_loss_pct=-1.0,
        arm_size=100,
    )
    assert state3.is_blocked_add is False
    assert state3.is_blocked_new is False
    assert final3 == 100.0  # intraday_mult=1.0 → 全放行
