from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from realtime_workflow import BombAlert


@dataclass
class BombAlertRule:
    """炸板预警规则"""
    name: str
    seal_drop_ratio: float = 0.5
    min_seal_amount: float = 1000000.0
    lookback_seconds: int = 60
    enabled: bool = True


@dataclass
class BombAlertResult:
    """单股炸板检测结果"""
    code: str
    name: str
    triggered: bool
    alert: BombAlert | None = None
    checked_at: datetime = field(default_factory=datetime.now)


class BombAlertSystem:
    """炸板预警系统"""

    def __init__(self) -> None:
        self.rules: list[BombAlertRule] = [
            BombAlertRule(name="default", seal_drop_ratio=0.5, min_seal_amount=1000000.0)
        ]
        self.history: list[BombAlertResult] = []

    def check(
        self,
        code: str,
        name: str,
        seal_amount: float,
        prev_seal_amount: float,
        now: datetime | None = None,
    ) -> BombAlertResult:
        """检查单股是否触发炸板预警"""
        now = now or datetime.now()
        triggered = False
        alert: BombAlert | None = None

        for rule in self.rules:
            if not rule.enabled:
                continue
            if prev_seal_amount <= 0:
                continue
            if seal_amount < rule.min_seal_amount:
                continue
            drop_ratio = (prev_seal_amount - seal_amount) / prev_seal_amount
            if drop_ratio >= rule.seal_drop_ratio:
                triggered = True
                alert = BombAlert(
                    timestamp=now.isoformat(),
                    code=code,
                    name=name,
                    alert_level="red" if drop_ratio >= 0.7 else "yellow",
                    condition=f"{name}({code}) 封单额下降 {drop_ratio:.1%}，疑似炸板",
                    current_seal_amount=seal_amount,
                    seal_amount_change_5min=prev_seal_amount - seal_amount,
                    recommendation="减仓或止盈",
                )
                break

        result = BombAlertResult(code=code, name=name, triggered=triggered, alert=alert, checked_at=now)
        self.history.append(result)
        return result

    def batch_check(self, items: list[dict[str, Any]]) -> list[BombAlertResult]:
        """批量检查炸板"""
        results: list[BombAlertResult] = []
        for item in items:
            results.append(
                self.check(
                    code=str(item.get("code", "")),
                    name=str(item.get("name", "")),
                    seal_amount=float(item.get("seal_amount", 0) or 0),
                    prev_seal_amount=float(item.get("prev_seal_amount", 0) or 0),
                )
            )
        return results

    def active_alerts(self) -> list[BombAlert]:
        """获取当前未处理的炸板预警"""
        alerts: list[BombAlert] = []
        for result in self.history[-200:]:
            if result.triggered and result.alert is not None:
                alerts.append(result.alert)
        return alerts
