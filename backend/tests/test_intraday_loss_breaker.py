# -*- coding: utf-8 -*-
"""S203 T7: intraday_loss_breaker test（TDD）。

验证吃大面 enforce：单笔>5% 禁加仓 / 合计>8% 禁开新仓 / 四层乘积 intraday_mult / 冷却。
"""
from __future__ import annotations

import pytest

from risk.intraday_loss_breaker import (
    LossBreakerState,
    SINGLE_LOSS_BLOCK_PCT,
    TOTAL_ACCOUNT_BLOCK_PCT,
    compute_final_size,
    evaluate_loss_breaker,
    intraday_multiplier,
)


def test_single_loss_5pct_block_add():
    """单笔浮亏>5% → is_blocked_add=True（该 code 禁加仓）。"""
    s = evaluate_loss_breaker("600000", "2026-01-01", realized_loss_pct=-6.0, total_account_loss_pct=-2.0)
    assert s.is_blocked_add is True  # 6%>5%
    assert s.is_blocked_new is False  # 2%<8%


def test_single_loss_below_5pct_no_block():
    """单笔浮亏<5% → 不禁。"""
    s = evaluate_loss_breaker("600000", "2026-01-01", realized_loss_pct=-4.0, total_account_loss_pct=-2.0)
    assert s.is_blocked_add is False
    assert s.is_blocked_new is False


def test_total_account_8pct_block_new():
    """合计>8% → is_blocked_new=True（全账户禁开新仓+冷却）。"""
    s = evaluate_loss_breaker("600000", "2026-01-01", realized_loss_pct=-3.0, total_account_loss_pct=-9.0)
    assert s.is_blocked_new is True  # 9%>8%
    assert s.is_blocked_add is False  # 3%<5%


def test_both_block():
    """单笔>5% + 合计>8% → 双 block。"""
    s = evaluate_loss_breaker("600000", "2026-01-01", realized_loss_pct=-7.0, total_account_loss_pct=-10.0)
    assert s.is_blocked_add is True
    assert s.is_blocked_new is True


def test_intraday_multiplier_block_new_zero():
    """is_blocked_new → intraday_mult=0（全账户熔断优先）。"""
    s = evaluate_loss_breaker("600000", "2026-01-01", -3.0, -9.0)
    assert intraday_multiplier(s) == 0.0


def test_intraday_multiplier_block_add_zero():
    """is_blocked_add（无 block_new）→ intraday_mult=0（该 code 禁加仓）。"""
    s = evaluate_loss_breaker("600000", "2026-01-01", -6.0, -2.0)
    assert intraday_multiplier(s) == 0.0


def test_intraday_multiplier_pass():
    """无 block → intraday_mult=1.0（放行）。"""
    s = evaluate_loss_breaker("600000", "2026-01-01", -2.0, -1.0)
    assert intraday_multiplier(s) == 1.0


def test_final_size_four_layer_product():
    """四层乘积 final_size = arm × portfolio × lift × intraday。"""
    assert compute_final_size(100, 0.8, 0.5, 1.0) == 40.0  # 100*0.8*0.5*1
    assert compute_final_size(100, 0.8, 0.5, 0.0) == 0.0  # intraday 0 → 0 禁交易
    assert compute_final_size(100, 0.0, 0.5, 1.0) == 0.0  # portfolio 0 → 0


def test_loss_breaker_state_immutable():
    """LossBreakerState frozen dataclass。"""
    s = evaluate_loss_breaker("600000", "2026-01-01", -6.0, -2.0)
    with pytest.raises(Exception):
        s.is_blocked_add = False  # frozen


def test_thresholds_constants():
    """阈值常量（5% / 8%）。"""
    assert SINGLE_LOSS_BLOCK_PCT == 5.0
    assert TOTAL_ACCOUNT_BLOCK_PCT == 8.0


def test_positive_loss_no_block():
    """正收益（盈利）→ 不 block（loss_pct 正数）。"""
    s = evaluate_loss_breaker("600000", "2026-01-01", realized_loss_pct=2.0, total_account_loss_pct=1.0)
    assert s.is_blocked_add is False  # abs(2)<5
    assert s.is_blocked_new is False


# ── S203 T6 接线验收（risk_rules enforce + cooldown）──────────────────────────


def test_cooldown_enforce(tmp_path, monkeypatch):
    """冷却期内 enforce 不重置（cooldown_until 未到 → 仍 block_new）。

    即使当前浮亏已降到阈值以下（该清冷却），冷却未到期仍强制 block_new——
    防止"刚触发 block 就立即放行"的振荡。
    """
    import json
    from datetime import datetime, timedelta
    from types import SimpleNamespace
    monkeypatch.setenv("VR_DATA_DIR", str(tmp_path))

    # 写未到期 cooldown（未来日期）
    cooldown_dir = tmp_path / "risk"
    cooldown_dir.mkdir(parents=True)
    future = (datetime.now().date() + timedelta(days=2)).isoformat()
    (cooldown_dir / "loss_breaker_cooldown.json").write_text(
        json.dumps({"cooldown_until": future}))

    from risk_rules import loss_breaker_enforce

    # mock journal：当前无持仓浮亏（该清冷却但冷却未到 → 仍 block_new）
    # 用 SimpleNamespace 避免 import engine.trade_journal（deflated_sharpe transitive）
    class MockJournal:
        def query_records(self, arm=None, is_dead_arm=None):
            return []

    result = loss_breaker_enforce(journal=MockJournal(), initial_capital=100000.0)
    assert result["is_blocked_new"] is True  # 冷却未到 → 强制 block_new
    assert result["cooldown_until"] == future  # cooldown 保持不重置


def test_risk_rules_upgrade_enforce(tmp_path, monkeypatch):
    """risk_rules.loss_breaker_enforce：从诊断升级 enforce，不破坏 report API。

    - 验 loss_breaker_enforce 存在 + 返 enforce 状态（block_add/block_new/cooldown）
    - 验 per-code 浮亏 → block_add 判定
    - 验合计浮亏 → block_new + 设 cooldown
    - 验 report 函数仍可 import（不破坏现有诊断 API）
    """
    from types import SimpleNamespace
    monkeypatch.setenv("VR_DATA_DIR", str(tmp_path))

    from risk_rules import loss_breaker_enforce, report  # noqa: F401 (report 可 import=未破坏)

    # mock journal：600000 亏 -6%（-6000/100000）、600001 亏 -3%、合计 -9%
    # 用 SimpleNamespace 避免 import engine.trade_journal（deflated_sharpe transitive）
    class MockJournal:
        def query_records(self, arm=None, is_dead_arm=None):
            return [
                SimpleNamespace(stock_code="600000", is_realized=0,
                                unrealized_pnl=-6000.0),
                SimpleNamespace(stock_code="600001", is_realized=0,
                                unrealized_pnl=-3000.0),
            ]

    result = loss_breaker_enforce(journal=MockJournal(), initial_capital=100000.0)
    assert result["available"] is True
    assert result["per_code"]["600000"]["is_blocked_add"] is True   # 6%>5%
    assert result["per_code"]["600001"]["is_blocked_add"] is False  # 3%<5%
    assert result["is_blocked_new"] is True  # 合计 9%>8%
    assert result["cooldown_until"] is not None  # block_new 触发设 cooldown
    assert result["n_codes"] == 2
    assert result["n_open"] == 2
