# -*- coding: utf-8 -*-
"""注册 dividend_low_vol arm（S244）：is_active=1 weight_override=0.25（25% 底仓）。

仓位规则基于 explore_portfolio_allocation.py 回测验证：
- 20% 仓位 Sharpe 1.223 / 30% Sharpe 1.035（最优区间）
- 25% 是中值,regime 稳健（3 个 regime 都正 5-6%/Sharpe>1/回撤<5%）
- drawdown control 简化（-15% 减半边际效果小,放宽 -20% 减仓提醒）

详见 specs/S244-divlowvol-position-rule/spec.md + memory portfolio-allocation-backtest-2026-11-08。
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from engine.trade_journal import TradeJournal  # noqa: E402


def main() -> None:
    tj = TradeJournal()
    tj.set_arm_status("dividend_low_vol", is_active=True, weight_override=0.25)
    st = tj.query_arm_status("dividend_low_vol")
    print("✅ dividend_low_vol arm 注册:", st)


if __name__ == "__main__":
    main()
