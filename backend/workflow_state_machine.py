"""
打板工作流状态机。

状态流转：
  候选池 → 观察池 → 监控池 → 持仓池 → 结算池
"""
from __future__ import annotations

from enum import Enum
from typing import Optional


class WorkflowStatus(str, Enum):
    """工作流状态枚举。"""
    PENDING = "pending"
    CANDIDATE = "candidate"
    WATCHING = "watching"
    MONITORING = "monitoring"
    HOLDING = "holding"
    SETTLED = "settled"
    FILTERED = "filtered"


# 允许的状态流转
_ALLOWED_TRANSITIONS = {
    WorkflowStatus.PENDING: [WorkflowStatus.CANDIDATE, WorkflowStatus.FILTERED],
    WorkflowStatus.CANDIDATE: [WorkflowStatus.WATCHING, WorkflowStatus.FILTERED],
    WorkflowStatus.WATCHING: [WorkflowStatus.MONITORING, WorkflowStatus.FILTERED, WorkflowStatus.CANDIDATE],  # S049 D7：取消观察→回候选池
    WorkflowStatus.MONITORING: [WorkflowStatus.HOLDING, WorkflowStatus.FILTERED],
    WorkflowStatus.HOLDING: [WorkflowStatus.SETTLED, WorkflowStatus.FILTERED],
    WorkflowStatus.SETTLED: [WorkflowStatus.CANDIDATE],  # 下一轮循环
    WorkflowStatus.FILTERED: [WorkflowStatus.CANDIDATE],  # 可重新进入
}


class WorkflowStateMachine:
    """工作流状态机。"""

    def __init__(self, initial_status: WorkflowStatus = WorkflowStatus.PENDING):
        self._current = initial_status
        self._history: list[tuple[WorkflowStatus, WorkflowStatus, str]] = []

    @property
    def current(self) -> WorkflowStatus:
        return self._current

    def can_transition_to(self, target: WorkflowStatus) -> bool:
        """检查是否允许转换到目标状态。"""
        return target in _ALLOWED_TRANSITIONS.get(self._current, [])

    def allowed_targets(self) -> list[WorkflowStatus]:
        """当前状态允许的目标态列表（只读副本，S032 R10 手动流转提示用）。"""
        return list(_ALLOWED_TRANSITIONS.get(self._current, []))

    def transition(self, target: WorkflowStatus, reason: str = "") -> bool:
        """执行状态转换。"""
        if not self.can_transition_to(target):
            return False
        old = self._current
        self._history.append((old, target, reason))
        self._current = target
        return True

    def reset(self) -> None:
        """重置状态机到初始状态。"""
        self._current = WorkflowStatus.PENDING
        self._history.clear()

    @property
    def history(self) -> list[tuple[WorkflowStatus, WorkflowStatus, str]]:
        return list(self._history)

    def is_terminal(self) -> bool:
        """是否为终态。"""
        return self._current in {WorkflowStatus.SETTLED, WorkflowStatus.FILTERED}

    def is_active(self) -> bool:
        """是否为活跃状态（非终态）。"""
        return not self.is_terminal()
