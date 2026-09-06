# -*- coding: utf-8 -*-
"""熔断器模式 —— 数据源故障时快速失败，避免雪崩。

S164 R1：SQLite 持久化（跨进程 state 恢复）。
治 :8900 重启丢 OPEN 状态（重启即忘封禁再轰）：
- ``get_breaker`` 创建时从 SQLite 加载持久化 state（state / failure_count /
  success_count / last_failure_time / half_open_calls）。
- ``allow_request`` / ``record_success`` / ``record_failure`` 状态变更后写回 SQLite。
- DB 路径 = ``resolve_data_dir() / "circuit_breaker_state.db"``（VR_DATA_DIR 隔离）。
- 持久化失败不阻断熔断器运行（except 吞 + log，breaker 仍正常工作）。

S164 R2：eastmoney breaker 拆 2 组（push2/push2his/push2ex/fflow 一组 +
datacenter 一组）。拆分在 ``data/transport.py`` 按 URL host 选择 breaker name，
本模块不感知分组——breaker name 只是 string key。
"""

from __future__ import annotations

import logging
import sqlite3
import threading
import time
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Callable, TypeVar

T = TypeVar("T")

logger = logging.getLogger("vibe-research")


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


# ── SQLite 持久化层（S164 R1）────────────────────────────────────────────

_persist_lock = threading.Lock()
_db_path_cache: str | None = None


def _get_db_path() -> str:
    """返回熔断器 state DB 路径（VR_DATA_DIR 隔离，测试 conftest 指临时目录）。"""
    global _db_path_cache
    if _db_path_cache is None:
        from vr_paths import resolve_data_dir
        _db_path_cache = str(resolve_data_dir() / "circuit_breaker_state.db")
    return _db_path_cache


def _init_db(db_path: str) -> None:
    """建表（幂等）。目录不存在则创建。"""
    Path(db_path).parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(db_path, timeout=5)
    conn.execute(
        "CREATE TABLE IF NOT EXISTS breaker_state ("
        "  name TEXT PRIMARY KEY,"
        "  state TEXT NOT NULL,"
        "  failure_count INTEGER NOT NULL,"
        "  success_count INTEGER NOT NULL,"
        "  last_failure_time REAL NOT NULL,"
        "  half_open_calls INTEGER NOT NULL,"
        "  updated_at REAL NOT NULL"
        ")"
    )
    conn.commit()
    conn.close()


def _load_persisted_state(name: str) -> dict | None:
    """从 SQLite 加载 breaker 持久化 state。无记录或出错返 None（不阻断创建）。"""
    try:
        db_path = _get_db_path()
        _init_db(db_path)
        conn = sqlite3.connect(db_path, timeout=5)
        row = conn.execute(
            "SELECT state, failure_count, success_count, last_failure_time, half_open_calls "
            "FROM breaker_state WHERE name=?",
            (name,),
        ).fetchone()
        conn.close()
        if row:
            return {
                "state": CircuitState(row[0]),
                "failure_count": row[1],
                "success_count": row[2],
                "last_failure_time": row[3],
                "half_open_calls": row[4],
            }
    except Exception as exc:  # noqa: BLE001
        logger.debug("[circuit_breaker] 加载持久化 state 失败 (%s): %s", name, exc)
    return None


def _persist_breaker(breaker: CircuitBreaker) -> None:
    """将 breaker state 写入 SQLite（INSERT OR REPLACE）。线程安全。"""
    try:
        db_path = _get_db_path()
        _init_db(db_path)
        with _persist_lock:
            conn = sqlite3.connect(db_path, timeout=5)
            conn.execute(
                "INSERT OR REPLACE INTO breaker_state "
                "(name, state, failure_count, success_count, last_failure_time, "
                " half_open_calls, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
                (
                    breaker.name,
                    breaker.state.value,
                    breaker.failure_count,
                    breaker.success_count,
                    breaker.last_failure_time,
                    breaker.half_open_calls,
                    time.time(),
                ),
            )
            conn.commit()
            conn.close()
    except Exception as exc:  # noqa: BLE001
        logger.debug("[circuit_breaker] 持久化 state 失败 (%s): %s", breaker.name, exc)


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
        # S164 R1：持久化回调，由 get_breaker 设置（独立 new 的 breaker 无持久化）
        self._persist_fn: Callable[[CircuitBreaker], None] | None = None

    def _persist(self) -> None:
        """状态变更后触发持久化（回调未设则 no-op）。"""
        if self._persist_fn is not None:
            self._persist_fn(self)

    def allow_request(self) -> bool:
        """是否允许请求通过。"""
        if self.state == CircuitState.CLOSED:
            return True
        if self.state == CircuitState.HALF_OPEN:
            allowed = self.half_open_calls < self.config.half_open_max_calls
            if allowed:
                self.half_open_calls += 1
                self._persist()
            return allowed
        # OPEN：检查是否超时
        if time.time() - self.last_failure_time >= self.config.recovery_timeout:
            self.state = CircuitState.HALF_OPEN
            self.half_open_calls = 0
            self._persist()
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
        self._persist()

    def record_failure(self) -> None:
        """记录失败。"""
        if self.state == CircuitState.HALF_OPEN:
            self.state = CircuitState.OPEN
            self.last_failure_time = time.time()
            self.half_open_calls = 0
            self.success_count = 0
            self._persist()
            return
        self.failure_count += 1
        if self.failure_count >= self.config.failure_threshold:
            self.state = CircuitState.OPEN
            self.last_failure_time = time.time()
        self._persist()

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
    """获取或创建熔断器。

    S164 R1：创建时从 SQLite 加载持久化 state（跨进程重启恢复 OPEN 状态），
    并设置持久化回调——后续状态变更自动写回 SQLite。
    """
    if name not in _breakers:
        breaker = CircuitBreaker(name, config)
        # R1：从 SQLite 加载持久化 state（重启不丢 OPEN）
        persisted = _load_persisted_state(name)
        if persisted:
            breaker.state = persisted["state"]
            breaker.failure_count = persisted["failure_count"]
            breaker.success_count = persisted["success_count"]
            breaker.last_failure_time = persisted["last_failure_time"]
            breaker.half_open_calls = persisted["half_open_calls"]
        # R1：设置持久化回调（后续状态变更自动写回）
        breaker._persist_fn = _persist_breaker
        _breakers[name] = breaker
    return _breakers[name]


def list_breakers() -> dict[str, CircuitBreaker]:
    """所有已注册熔断器（S134：供 health 等遍历，避免读私有 _breakers）。

    返回 _breakers 的浅拷贝——调用方遍历不受注册表后续变动影响，也不应
    通过返回值修改注册表本身。
    """
    return dict(_breakers)
