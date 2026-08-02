# -*- coding: utf-8 -*-
"""S022：熔断器 peek_state 单测 + health 读路径自愈测。

TDD：先写（RED）→ 实现 peek_state 后转 GREEN。
覆盖：
- peek_state 三态：CLOSED / OPEN-fresh / OPEN-stale(>recovery_timeout → HALF_OPEN)
- peek 无副作用：不改 self.state、不消耗 half_open_calls
- _check_circuit_breaker 陈旧 OPEN → ok=True（体检 🔴 复现场景修复）
- _check_circuit_breaker 新鲜 OPEN → ok=False（真实信号保留）
"""
from __future__ import annotations

import time

import pytest

from circuit_breaker import CircuitBreaker, CircuitState, get_breaker


# ── peek_state 单测（R1 / A1）────────────────────────────────────


def test_peek_state_closed_returns_closed():
    # Arrange
    breaker = CircuitBreaker("t")
    # Act
    state = breaker.peek_state()
    # Assert
    assert state == CircuitState.CLOSED


def test_peek_state_open_within_recovery_timeout_returns_open():
    # Arrange
    breaker = CircuitBreaker("t")
    breaker.state = CircuitState.OPEN
    breaker.last_failure_time = time.time() - 10  # < 60s recovery_timeout
    # Act
    state = breaker.peek_state()
    # Assert
    assert state == CircuitState.OPEN


def test_peek_state_open_after_recovery_timeout_returns_half_open():
    # Arrange
    breaker = CircuitBreaker("t")
    breaker.state = CircuitState.OPEN
    breaker.last_failure_time = time.time() - 61  # > 60s recovery_timeout
    # Act
    state = breaker.peek_state()
    # Assert
    assert state == CircuitState.HALF_OPEN


def test_peek_state_does_not_mutate_breaker_state():
    # Arrange：陈旧 OPEN
    breaker = CircuitBreaker("t")
    breaker.state = CircuitState.OPEN
    breaker.last_failure_time = time.time() - 61
    # Act：连 peek 两次
    breaker.peek_state()
    breaker.peek_state()
    # Assert：peek 不改 self.state（仍 OPEN，真实转换由 allow_request 负责）、不消耗试探名额
    assert breaker.state == CircuitState.OPEN
    assert breaker.half_open_calls == 0


# ── health 读路径自愈测（R2 / A2 / A3）────────────────────────────


@pytest.fixture
def eastmoney_breaker():
    """提供全局 eastmoney breaker，用后还原（防污染其他测试）。"""
    breaker = get_breaker("eastmoney")
    saved = (
        breaker.state,
        breaker.failure_count,
        breaker.last_failure_time,
        breaker.half_open_calls,
        breaker.success_count,
    )
    yield breaker
    (
        breaker.state,
        breaker.failure_count,
        breaker.last_failure_time,
        breaker.half_open_calls,
        breaker.success_count,
    ) = saved


def test_health_check_recovers_for_stale_open_breaker(eastmoney_breaker):
    # Arrange：陈旧 OPEN（>60s 无请求）——体检 🔴 复现场景
    eastmoney_breaker.state = CircuitState.OPEN
    eastmoney_breaker.last_failure_time = time.time() - 61
    from routers.health import _check_circuit_breaker
    # Act
    result = _check_circuit_breaker()
    # Assert：peek 把陈旧 OPEN 视为 HALF_OPEN → ok=True（自愈）
    assert result["ok"] is True
    assert result["detail"] == "circuit_breaker_half_open"


def test_health_check_reports_false_for_fresh_open_breaker(eastmoney_breaker):
    # Arrange：新鲜 OPEN（<60s）——真实下游降级信号
    eastmoney_breaker.state = CircuitState.OPEN
    eastmoney_breaker.last_failure_time = time.time() - 10
    from routers.health import _check_circuit_breaker
    # Act
    result = _check_circuit_breaker()
    # Assert：真实 OPEN 仍报 ok=False（信号保留，不屏蔽）
    assert result["ok"] is False
    assert result["detail"] == "circuit_breaker_open"
