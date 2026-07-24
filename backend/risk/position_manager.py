from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from realtime_workflow import PositionAdjustment


@dataclass
class PositionLimit:
    """个股仓位限制"""
    max_single_position: float = 0.3
    max_sector_position: float = 0.6
    min_cash_reserve: float = 0.2


@dataclass
class PositionSnapshot:
    """当前仓位快照"""
    code: str
    name: str
    weight: float
    sector: str | None = None
    cost_price: float | None = None
    current_price: float | None = None


class PositionManager:
    """动态仓位管理"""

    def __init__(self, limits: PositionLimit | None = None) -> None:
        self.limits = limits or PositionLimit()
        self.positions: dict[str, PositionSnapshot] = {}
        self.adjustments: list[PositionAdjustment] = []

    def upsert(self, snapshot: PositionSnapshot) -> None:
        """更新或插入仓位"""
        self.positions[snapshot.code] = snapshot

    def evaluate(self, code: str, name: str, suggested_weight: float, sector: str | None = None) -> PositionAdjustment:
        """根据建议仓位和当前限制计算调整动作"""
        current = self.positions.get(code)
        old_pct = current.weight if current else 0.0

        new_pct = max(0.0, min(suggested_weight, self.limits.max_single_position))
        action = "hold"
        reason = "within_limit"

        if new_pct > old_pct + 1e-9:
            action = "increase"
            reason = "increase_within_limit"
        elif new_pct < old_pct - 1e-9:
            action = "decrease"
            reason = "reduce_to_limit"

        adjustment = PositionAdjustment(
            code=code,
            name=name,
            action=action,
            reason=reason,
            old_position_pct=old_pct,
            new_position_pct=new_pct,
            timestamp=datetime.now().isoformat(),
        )
        self.adjustments.append(adjustment)
        if new_pct > 0:
            self.positions[code] = PositionSnapshot(code=code, name=name, weight=new_pct, sector=sector)
        elif code in self.positions:
            del self.positions[code]
        return adjustment

    def current_weights(self) -> dict[str, float]:
        """返回当前各股仓位权重"""
        return {code: snap.weight for code, snap in self.positions.items()}

    def sector_exposure(self, sector: str) -> float:
        """返回指定板块总暴露"""
        return sum(snap.weight for snap in self.positions.values() if snap.sector == sector)
