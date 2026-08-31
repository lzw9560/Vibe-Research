"""S128 or-zero 契约 + 3 HIGH/头条M 修复测试。

R1.2 bidding_monitor degraded 不生成假"缩量平开"信号
R2.2 limitup_screener seal_time 全 None → 封板率 None（非 100 MAX 假封板率）
R3.3 intraday_sentiment break_rate None → break_score=50 neutral（非 100 假看涨）
C2   check_or_zero_contract.py lint 自测
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest


# ── R1.2 bidding_monitor degraded skip ──────────────────────────────────────
def test_bidding_monitor_degraded_no_false_signal():
    """quote 失败（critical 字段 None→data_status=degraded）→ 不生成"缩量平开"/"爆量高开"
    假信号，返"无信号"+reason（S128 R1）。"""
    import bidding_monitor

    snaps = [
        {
            "code": "600000", "name": "X", "open_premium": None, "auction_amount": None,
            "volume_ratio": None, "cancel_rate": 0.0, "market_cap": None,
            "data_status": "degraded",
        }
    ]
    signals = bidding_monitor.analyze_final_auction(snaps)
    assert len(signals) == 1
    assert signals[0].signal_type == "无信号"
    assert signals[0].confidence == 0.0
    assert any("取数失败" in r or "degraded" in r for r in signals[0].reasoning)


def test_bidding_monitor_ok_snapshot_still_signals():
    """quote ok（critical 字段有值）→ 原信号生成不变（无 regression）。"""
    import bidding_monitor

    snaps = [
        {
            "code": "600000", "name": "X", "open_premium": 0.05, "auction_amount": 5e8,
            "volume_ratio": 3.0, "cancel_rate": 0.0, "market_cap": 5e10,
            "data_status": "ok",
        }
    ]
    signals = bidding_monitor.analyze_final_auction(snaps)
    assert len(signals) == 1
    assert signals[0].signal_type == "爆量高开"  # open_premium>=0.02 + amount + vol_ratio 都过


# ── R2.2 limitup_screener seal_time 全 None → 封板率 None ────────────────────
def test_seal_time_all_none_no_fake_100_seal_rate():
    """seal_time 全 None → 封板率 None（非 avg_fbt=0→seal_rate=100 MAX 假封板率，S128 R2）。"""
    from limitup_screener.models import compute_factors

    # history 全 seal_time=None（_numf '-'→None）；其他字段给值防他处崩
    h = SimpleNamespace(
        code="600000", name="X", boards=1, seal_time=None, limit_pct=10.0,
        seal_amount=1e8, float_shares=1e8, broken_count=0,
    )
    factors = compute_factors([h], [], [])
    assert factors["封板率"] is None  # 非 100 假封板率


def test_seal_time_present_normal_seal_rate():
    """seal_time 有值 → 封板率正常算（无 regression）。"""
    from limitup_screener.models import compute_factors

    h = SimpleNamespace(
        code="600000", name="X", boards=1, seal_time=100000.0, limit_pct=10.0,
        seal_amount=1e8, float_shares=1e8, broken_count=0,
    )
    factors = compute_factors([h], [], [])
    assert factors["封板率"] is not None
    assert 0.0 <= factors["封板率"] <= 100.0


# ── R3.3 intraday_sentiment break_rate None → neutral 50 ────────────────────
def test_compute_score_break_none_neutral_not_fake_100():
    """break_rate=None → break_score=50 neutral（非 or 0→0<0.15→100 假看涨，S128 R3）。"""
    from routers.intraday_sentiment import _compute_score

    # break_rate=None（源断）vs break_rate=0.0（原 or 0 lie path→break_score=100）
    score_none = _compute_score(50.0, None, None, 1.0)
    score_zero_break = _compute_score(50.0, 0.5, 0.0, 1.0)  # break=0→100 假看涨
    # None neutral ≠ 0 lie path（score 应不同——None→50 < 0→100）
    assert score_none != score_zero_break
    assert score_none < score_zero_break  # 50 neutral < 100 假看涨


def test_compute_score_seal_none_neutral():
    """seal_rate=None → seal_score=50 neutral（非 0 假看跌）。"""
    from routers.intraday_sentiment import _compute_score

    score_none = _compute_score(50.0, None, 0.1, 1.0)
    score_zero_seal = _compute_score(50.0, 0.0, 0.1, 1.0)  # seal=0→_score_dimension(0)=低
    assert score_none != score_zero_seal  # None neutral ≠ 0


# ── C2 check_or_zero_contract.py lint 自测 ──────────────────────────────────
def test_or_zero_lint_passes_current_code():
    """CI lint：当前 backend 0 consumer 反吞 NEVER_ZERO 字段（S128 C2 契约门）。"""
    script = Path(__file__).resolve().parent.parent.parent / "scripts" / "check_or_zero_contract.py"
    result = subprocess.run(
        [sys.executable, str(script)], capture_output=True, text=True,
    )
    assert result.returncode == 0, f"lint 违例:\n{result.stdout}\n{result.stderr}"


def test_or_zero_lint_catches_planted_violation(tmp_path):
    """planted `model.price or 0` → lint 返非零（契约门真生效）。"""
    import importlib.util

    script = Path(__file__).resolve().parent.parent.parent / "scripts" / "check_or_zero_contract.py"
    spec = importlib.util.spec_from_file_location("check_or_zero_contract", script)
    lint = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(lint)

    # 临时 backend 目录 + 一违例文件
    fake_backend = tmp_path / "backend"
    fake_backend.mkdir()
    (fake_backend / "consumer.py").write_text("p = model.price or 0\n", encoding="utf-8")
    lint.BACKEND = fake_backend
    lint.ALLOWLIST = set()
    vs = lint.scan()
    assert len(vs) == 1
    assert "consumer.py" in vs[0][0]
    assert "price" in vs[0][2]
