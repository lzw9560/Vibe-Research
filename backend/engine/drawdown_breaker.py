# -*- coding: utf-8 -*-
"""S173 Drawdown 熔断器——风控 sizing 熔断（非 IP 熔断）。

**与 circuit_breaker.py 分离**（spec §5.6）：circuit_breaker 是 IP 封断裂路器
（半开/熔断/恢复 timeout），语义不同。drawdown 是 equity 风控 sizing，
新建语义清晰。

**C4 绝对回撤**（遵循 risk_rules.equity_curve 模式）：
  equity = initial_capital + cumulative_net_pnl (realized + unrealized MTM)
  drawdown_cny = peak_cny - current_cny（绝对 CNY）
  drawdown_pct = drawdown_cny / initial_capital
  不用零基百分比 (peak-current)/peak——那会 20x 膨胀（1% 浮盈 10 元回撤 vs
  10000 元后续盈利 200 元回撤，同一绝对金额不同百分比）。

**C5 floor 豁免 per-arm DD**：ETF 历史 -13.6% > 10% 会误杀 floor。
  floor 是 buy+hold 长线，per-arm MTM 波动不是策略失效信号。
  floor 仅参与 portfolio aggregate DD，不参与 per-arm DD。

**H4 underpowered gate**：days_tracked<60 → multiplier=1.0 status='underpowered'
  （参考 §44v2 days_robust<60 逻辑）。

**H5 drawdown topology**：
  (a) per-arm DD → 仅该臂 size_multiplier 缩放（floor 豁免）
  (b) portfolio aggregate DD → portfolio-level breaker 统一缩放所有臂
  (c) final_size = arm_size_multiplier × portfolio_size_multiplier × lift_multiplier

**H6 熊市 regime**：CSI300 < 200 日线 或 市场 DD > 15% →
  floor 豁免 drawdown enforce（阈值 >25%），CB 只作用非 floor 臂。
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any

from engine.trade_journal import TradeJournal, DEFAULT_INITIAL_CAPITAL

_logger = logging.getLogger(__name__)

#: drawdown 阈值（相对 initial_capital 的百分比）。
DD_THRESHOLD_HALVE: float = 10.0   # DD_pct > 10% → size_multiplier = 0.5
DD_THRESHOLD_STOP: float = 15.0    # DD_pct > 15% → size_multiplier = 0.0（全停）

#: underpowered gate 阈值（H4）。
MIN_DAYS_FOR_ENFORCE: int = 60

#: floor 臂熊市豁免阈值（H6：熊市时 floor 不在 per-arm DD enforce）。
BEAR_MARKET_FLOOR_DD_THRESHOLD: float = 25.0

#: floor 臂 tag（C5 豁免 per-arm DD）。
ARM_FLOOR: str = "floor"


@dataclass(frozen=True)
class DrawdownResult:
    """drawdown 计算结果（immutable）。

    equity: 当前权益（initial_capital + cumulative PnL）。
    drawdown_cny: 绝对 CNY 回撤（peak - current，C4）。
    drawdown_pct: 回撤百分比（drawdown_cny / initial_capital，非 (peak-current)/peak）。
    size_multiplier: 输出的 sizing 乘数（0.5/0.0/1.0）。
    status: 'enforced' | 'underpowered' | 'disabled'。
    days_tracked: 已跟踪交易日数（<60 → underpowered）。
    is_bear_market: 熊市 regime 标志（H6）。
    """

    equity: float
    peak: float
    drawdown_cny: float
    drawdown_pct: float
    size_multiplier: float
    status: str
    days_tracked: int
    is_bear_market: bool


class DrawdownBreaker:
    """drawdown 风控 sizing 熔断器。

    读 TradeJournal 聚合 equity 曲线（realized + unrealized MTM），
    输出 size_multiplier（与 lift_multiplier 复合相乘，H5 三层乘积）。
    """

    def __init__(
        self, journal: TradeJournal | None = None,
        initial_capital: float = DEFAULT_INITIAL_CAPITAL,
    ) -> None:
        self._journal = journal or TradeJournal()
        self._initial_capital = initial_capital

    def compute_drawdown(self, arm: str | None = None) -> DrawdownResult:
        """计算回撤（C4 绝对 CNY，遵循 risk_rules.equity_curve 模式）。

        equity = initial_capital + cumulative_realized_pnl + sum(unrealized_pnl)
        drawdown_cny = peak_cny - current_cny
        drawdown_pct = drawdown_cny / initial_capital
        """
        snapshot = self._journal.get_drawdown_status(arm=arm)
        cum_pnl = snapshot.get("cum_pnl", 0.0)
        peak_pnl = snapshot.get("peak_pnl", 0.0)
        days_tracked = snapshot.get("days_tracked", 0)

        equity = self._initial_capital + cum_pnl
        peak_equity = self._initial_capital + peak_pnl
        drawdown_cny = peak_equity - equity
        drawdown_pct = (
            drawdown_cny / self._initial_capital * 100
            if self._initial_capital > 0 else 0.0
        )

        is_bear = self._detect_bear_market()

        # underpowered gate（H4）
        if days_tracked < MIN_DAYS_FOR_ENFORCE:
            status = "underpowered"
            multiplier = 1.0
        elif arm == ARM_FLOOR and is_bear:
            # H6 熊市 regime：floor 豁免（阈值 >25%）
            status = "bear_exempt"
            multiplier = 0.5 if drawdown_pct > BEAR_MARKET_FLOOR_DD_THRESHOLD else 1.0
            if drawdown_pct > BEAR_MARKET_FLOOR_DD_THRESHOLD * 1.5:
                multiplier = 0.0
        else:
            status = "enforced"
            if drawdown_pct > DD_THRESHOLD_STOP:
                multiplier = 0.0
            elif drawdown_pct > DD_THRESHOLD_HALVE:
                multiplier = 0.5
            else:
                multiplier = 1.0

        return DrawdownResult(
            equity=round(equity, 2),
            peak=round(peak_equity, 2),
            drawdown_cny=round(drawdown_cny, 2),
            drawdown_pct=round(drawdown_pct, 2),
            size_multiplier=multiplier,
            status=status,
            days_tracked=days_tracked,
            is_bear_market=is_bear,
        )

    def size_multiplier(self, arm: str | None = None) -> tuple[float, str]:
        """输出 size_multiplier + status（per-arm 或 portfolio aggregate）。

        per-arm DD（floor 豁免 C5）：DD_pct>10%→0.5, >15%→0.0
        portfolio aggregate DD：统一缩放所有臂（floor 含但阈值高/熊市豁免）
        underpowered gate（H4）：days_tracked<60→multiplier=1.0 status='underpowered'
        熊市 regime（H6）：CSI300<200日线→floor 豁免
        """
        # C5：floor 不参与 per-arm DD（只有 portfolio aggregate 才作用 floor）
        if arm == ARM_FLOOR:
            # floor per-arm DD 豁免 → 返 1.0（仍受 portfolio aggregate 约束）
            snapshot = self._journal.get_drawdown_status(arm=arm)
            days = snapshot.get("days_tracked", 0)
            if days < MIN_DAYS_FOR_ENFORCE:
                return 1.0, "underpowered"
            return 1.0, "floor_exempt_per_arm"

        result = self.compute_drawdown(arm=arm)
        return result.size_multiplier, result.status

    def portfolio_multiplier(self) -> tuple[float, str]:
        """portfolio aggregate DD → portfolio-level breaker 统一缩放所有臂。"""
        return self.size_multiplier(arm=None)

    def final_size(
        self, arm: str, arm_size: float,
        lift_multiplier: float = 1.0,
    ) -> float:
        """H5 三层乘积：final_size = arm_size × portfolio_multiplier × lift_multiplier。

        lift 管 signal 信任（§44 验证），drawdown 管组合风控，两者正交。
        """
        arm_mult, _ = self.size_multiplier(arm=arm)
        port_mult, _ = self.portfolio_multiplier()
        return arm_size * arm_mult * port_mult * lift_multiplier

    def _detect_bear_market(self) -> bool:
        """H6 熊市检测：CSI300 < 200 日均线 或 市场 DD > 15%。

        独立函数供 mock（测试不联网）。生产可接 market data。
        """
        try:
            from config import CSI300_BEAR_THRESHOLD  # noqa: PLC0415
            return bool(CSI300_BEAR_THRESHOLD)
        except ImportError:
            pass
        # 未配置熊市检测 → 返 False（不误杀，生产接线后返真值）
        return False

    def full_status(self) -> dict:
        """完整 drawdown 状态快照（供前端 /api/journal/drawdown-status）。"""
        arms = self._journal._distinct_arms()
        per_arm: dict[str, Any] = {}
        for a in arms:
            r = self.compute_drawdown(arm=a)
            per_arm[a] = {
                "equity": r.equity,
                "peak": r.peak,
                "drawdown_cny": r.drawdown_cny,
                "drawdown_pct": r.drawdown_pct,
                "size_multiplier": r.size_multiplier,
                "status": r.status,
                "days_tracked": r.days_tracked,
            }
        port = self.compute_drawdown(arm=None)
        return {
            "per_arm": per_arm,
            "portfolio": {
                "equity": port.equity,
                "peak": port.peak,
                "drawdown_cny": port.drawdown_cny,
                "drawdown_pct": port.drawdown_pct,
                "size_multiplier": port.size_multiplier,
                "status": port.status,
                "days_tracked": port.days_tracked,
                "is_bear_market": port.is_bear_market,
            },
            "initial_capital": self._initial_capital,
        }


__all__ = [
    "DrawdownBreaker",
    "DrawdownResult",
    "DD_THRESHOLD_HALVE",
    "DD_THRESHOLD_STOP",
    "MIN_DAYS_FOR_ENFORCE",
    "ARM_FLOOR",
]
