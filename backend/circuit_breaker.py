# -*- coding: utf-8 -*-
"""熔断器模式 —— 数据源故障时快速失败，避免雪崩。"""

from __future__ import annotations

import time
from dataclasses import dataclass
from enum import Enum
from typing import Callable, TypeVar

T = TypeVar("T")


class CircuitState(Enum):
    CLOSED = "closed"       # 正常：允许请求
    OPEN = "open"           # 熔断：快速失败
    HALF_OPEN = "half_open" # 半开：试探性请求


@dataclass
class CircuitBreakerConfig:
    failure_threshold: int = 5          # 连续失败次数阈值
    recovery_timeout: float = 60.0      # 熔断后多久进入半开（秒）
    half_open_max_calls: int = 3        # 半开状态最大试探次数
    success_threshold: int = 2          # 半开状态连续成功次数阈值


class CircuitBreaker:
    """通用熔断器。"""

    def __init__(self, name: str, config: CircuitBreakerConfig | None = None):
        self.name = name
        self.config = config or CircuitBreakerConfig()
        self.state = CircuitState.CLOSED
        self.failure_count = 0
        self.success_count = 0
        self.last_failure_time = 0.0
        self.half_open_calls = 0

    def allow_request(self) -> bool:
        """是否允许请求通过。"""
        if self.state == CircuitState.CLOSED:
            return True
        if self.state == CircuitState.HALF_OPEN:
            allowed = self.half_open_calls < self.config.half_open_max_calls
            if allowed:
                self.half_open_calls += 1
            return allowed
        # OPEN：检查是否超时
        if time.time() - self.last_failure_time >= self.config.recovery_timeout:
            self.state = CircuitState.HALF_OPEN
            self.half_open_calls = 0
            return True
        return False

    def peek_state(self) -> CircuitState:
        """只读探测：返回给定当前时间应处的状态（OPEN 超 recovery_timeout → HALF_OPEN）。

        与 allow_request() 不同，本方法无副作用——不改 self.state、不消耗
        half_open_calls 试探名额。供 health 检查等只读观测用；真实 OPEN→HALF_OPEN
        转换仍由 allow_request() 在真实请求时触发（S022）。
        """
        if (
            self.state == CircuitState.OPEN
            and self.last_failure_time > 0
            and time.time() - self.last_failure_time >= self.config.recovery_timeout
        ):
            return CircuitState.HALF_OPEN
        return self.state

    def record_success(self) -> None:
        """记录成功。"""
        if self.state == CircuitState.HALF_OPEN:
            self.success_count += 1
            if self.success_count >= self.config.success_threshold:
                self.state = CircuitState.CLOSED
                self.failure_count = 0
                self.success_count = 0
                self.half_open_calls = 0
        else:
            self.failure_count = 0

    def record_failure(self) -> None:
        """记录失败。"""
        if self.state == CircuitState.HALF_OPEN:
            self.state = CircuitState.OPEN
            self.last_failure_time = time.time()
            self.half_open_calls = 0
            self.success_count = 0
            return
        self.failure_count += 1
        if self.failure_count >= self.config.failure_threshold:
            self.state = CircuitState.OPEN
            self.last_failure_time = time.time()

    def __call__(self, func: Callable[..., T]) -> Callable[..., T]:
        """装饰器用法。"""
        import functools

        @functools.wraps(func)
        def wrapper(*args, **kwargs):
            if not self.allow_request():
                raise RuntimeError(f"[CircuitBreaker:{self.name}] 熔断器开启，快速失败")
            try:
                result = func(*args, **kwargs)
                self.record_success()
                return result
            except Exception as e:
                self.record_failure()
                raise

        return wrapper


# 全局熔断器注册表
_breakers: dict[str, CircuitBreaker] = {}


def get_breaker(name: str, config: CircuitBreakerConfig | None = None) -> CircuitBreaker:
    """获取或创建熔断器。"""
    if name not in _breakers:
        _breakers[name] = CircuitBreaker(name, config)
    return _breakers[name]


def list_breakers() -> dict[str, CircuitBreaker]:
    """所有已注册熔断器（S134：供 health 等遍历，避免读私有 _breakers）。

    返回 _breakers 的浅拷贝——调用方遍历不受注册表后续变动影响，也不应
    通过返回值修改注册表本身。
    """
    return dict(_breakers)
