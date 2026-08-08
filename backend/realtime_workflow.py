"""
盘中工作流（09:30-15:00）。

职责：
1. 实时监控候选池股票
2. 炸板预警系统
3. 动态仓位管理
4. 生成交易信号
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

logger = logging.getLogger(__name__)


@dataclass
class RealtimeSignal:
    """实时信号。"""
    timestamp: str
    code: str
    name: str
    signal_type: str  # buy/sell/alert
    price: float
    volume: int
    reason: str
    urgency: str  # high/medium/low


@dataclass
class BombAlert:
    """炸板预警。"""
    timestamp: str
    code: str
    name: str
    alert_level: str  # yellow/red
    condition: str
    current_seal_amount: float
    seal_amount_change_5min: float
    recommendation: str


@dataclass
class PositionAdjustment:
    """仓位调整。"""
    timestamp: str
    code: str
    name: str
    action: str  # add/reduce/close
    reason: str
    old_position_pct: float
    new_position_pct: float


class RealtimeWorkflow:
    """盘中工作流引擎。"""

    def __init__(self):
        self._signals: list[RealtimeSignal] = []
        self._alerts: list[BombAlert] = []
        self._adjustments: list[PositionAdjustment] = []

    async def get_market_status(self) -> dict[str, Any]:
        """获取当前市场状态。"""
        now = datetime.now()
        hour = now.hour
        minute = now.minute

        if hour < 9:
            return {"status": "closed", "phase": "盘前"}
        elif hour == 9 and minute < 30:
            return {"status": "auction", "phase": "竞价中"}
        elif hour < 11 or (hour == 11 and minute <= 30):
            return {"status": "trading", "phase": "上午盘"}
        elif hour < 13:
            return {"status": "closed", "phase": "午间休市"}
        elif hour < 15:
            return {"status": "trading", "phase": "下午盘"}
        else:
            return {"status": "closed", "phase": "已收盘"}

    async def monitor_stock(self, code: str, name: str) -> RealtimeSignal | None:
        """监控单只股票，生成信号。"""
        # stub: 未实现，见 S036（端点 /workflow/realtime 已 early return，不触达本桩）
        # TODO: 接入实时行情数据
        return None

    async def check_bomb_alerts(self, code: str, name: str, seal_amount: float, prev_seal_amount: float) -> BombAlert | None:
        """检查炸板预警。"""
        if seal_amount <= 0:
            return None

        change_5min = (seal_amount - prev_seal_amount) / prev_seal_amount if prev_seal_amount > 0 else 0

        # 黄色预警：封单 5 分钟减少 > 30%
        if change_5min < -0.30:
            return BombAlert(
                timestamp=datetime.now().isoformat(),
                code=code,
                name=name,
                alert_level="yellow",
                condition=f"封单5分钟减少{abs(change_5min)*100:.0f}%",
                current_seal_amount=seal_amount,
                seal_amount_change_5min=change_5min,
                recommendation="密切关注，准备减仓",
            )

        # 红色预警：封单 < 流通市值 0.3%（需要额外数据）
        # TODO: 接入流通市值数据
        # 见 S036：alerts 端点已标灰（run_intraday 不调本方法），暂不在端点路径

        return None

    def adjust_position(self, code: str, name: str, action: str, reason: str, old_pct: float, new_pct: float) -> PositionAdjustment:
        """记录仓位调整。"""
        adj = PositionAdjustment(
            timestamp=datetime.now().isoformat(),
            code=code,
            name=name,
            action=action,
            reason=reason,
            old_position_pct=old_pct,
            new_position_pct=new_pct,
        )
        self._adjustments.append(adj)
        return adj

    @property
    def signals(self) -> list[RealtimeSignal]:
        return list(self._signals)

    @property
    def alerts(self) -> list[BombAlert]:
        return list(self._alerts)

    @property
    def adjustments(self) -> list[PositionAdjustment]:
        return list(self._adjustments)
