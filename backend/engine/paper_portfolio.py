# -*- coding: utf-8 -*-
"""S175 R10 — PaperPortfolio thin read-only wrapper（R9 消费非空转 SH1 fix）。

委托 trade_journal.equity_curve/get_drawdown_status + drawdown_breaker.full_status/final_size，
不存独立 state（S088 重算范式，DRY-acknowledged——trade_journal.equity_curve 已是重算非
结果 cache）。

**价值（SH1 fix）**：scheduler executor 末尾调 PaperPortfolio.equity() 落盘供推荐 sizing；
R9 recommendation_engine 读它作 floor 仓位 sizing（R9↔R10 接线，非空转）。v1 spec 声称
"供推荐 sizing"但 R9 零引用→空转；v2 R9 加读 equity() 接线。

**DRY-acknowledged**：trade_journal.get_drawdown_status() 已算 equity = initial + cum；
drawdown_breaker.full_status() 已算 portfolio + per-arm。PaperPortfolio 是 thin wrapper
非独立 state store——价值在 scheduler 路径提供 equity 给 R9 sizing（drawdown_breaker
当前只在 API 层不在 sizing 路径，grill C6）。
"""
from __future__ import annotations

import logging
from typing import Any

from engine.trade_journal import TradeJournal, DEFAULT_INITIAL_CAPITAL
from engine.drawdown_breaker import DrawdownBreaker

_logger = logging.getLogger(__name__)


class PaperPortfolio:
    """read-only 聚合——委托 TradeJournal + DrawdownBreaker，不存独立 state。

    每次调都从 trade_journal.db 重算（S088 重算范式，不读结果 cache）。
    """

    def __init__(
        self, journal: TradeJournal | None = None,
        breaker: DrawdownBreaker | None = None,
        initial_capital: float = DEFAULT_INITIAL_CAPITAL,
    ) -> None:
        self._journal = journal or TradeJournal()
        self._breaker = breaker or DrawdownBreaker(self._journal, initial_capital)
        self._initial_capital = initial_capital

    def equity(self, arm: str | None = None) -> float:
        """当前总权益 = initial_capital + cum_realized + unrealized（委托 get_drawdown_status）。

        arm=None → portfolio 级；arm='breakout' → per-arm 级。
        """
        status = self._journal.get_drawdown_status(arm=arm)
        return float(status.get("equity", self._initial_capital))

    def drawdown_status(self) -> dict[str, Any]:
        """委托 DrawdownBreaker.full_status()（portfolio + per-arm size_multiplier）。"""
        return self._breaker.full_status()

    def final_size(
        self, arm: str, arm_size: float, lift_multiplier: float | None = None,
    ) -> float:
        """委托 DrawdownBreaker.final_size（H5 三层乘积 arm×portfolio×lift）。

        S180 R3: lift_multiplier 默认 None → 内部调 lift_for_arm(arm) 动态算
        （用冻结 DIMENSION_LIFT_REGISTRY + lift_to_multiplier，days<60→×0.5）。
        floor/gap/mock 臂 N/A → 1.0 cap 不作用。
        """
        if lift_multiplier is None:
            from candidate_funnel.evaluation import lift_for_arm  # noqa: PLC0415
            lift_multiplier = lift_for_arm(arm)[0]
        return self._breaker.final_size(arm, arm_size, lift_multiplier)

    def bayesian_arm_size(self, arm: str, max_size: float = 1.0) -> float:
        """Beta-Bernoulli 后验驱动 arm_size（wok7j1arm P1）。

        Beta(1,1) 先验 → trade_journal realized wins/losses 更新后验 → arm_size ∝ 下 5% 可信界（保守）。
        不确定性高→小仓，数据累积→后验收窄→仓位增长。exploratory→validated 数学诚实桥梁。
        用 scipy.stats（已装），不需 PyMC/Stan。
        """
        try:
            from scipy.stats import beta as beta_dist  # noqa: PLC0415
        except ImportError:
            return 0.0
        trends = self._journal.query_winrate_trends(arm=arm)
        if not trends:
            return 0.0
        last = trends[-1]
        n_decided = last.get("n_decided", 0)
        if n_decided < 1:
            return 0.0
        n_win = round(last.get("win_rate", 0) * n_decided)
        n_loss = n_decided - n_win
        # Beta(1+n_win, 1+n_loss) 后验——下 5% 分位（保守下界）
        posterior = beta_dist(1 + n_win, 1 + n_loss)
        lower = float(posterior.ppf(0.05))
        return round(min(lower, max_size), 4)


__all__ = ["PaperPortfolio"]
