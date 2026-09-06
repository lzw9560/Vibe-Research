# -*- coding: utf-8 -*-
"""S164 R1+R2：熔断器 SQLite 持久化 + eastmoney 拆 2 组 单测。

R1 覆盖：
- OPEN 状态持久化到 SQLite，跨 _breakers 清空（模拟重启）恢复
- failure_count / last_failure_time 持久化
- CLOSED 状态也持久化（record_success 后）
- 独立 new 的 CircuitBreaker（不经 get_breaker）无持久化

R2 覆盖：
- _select_breaker_name 按 URL host 选 eastmoney / eastmoney_datacenter
- push2 breaker OPEN 不阻断 datacenter breaker（隔离）
"""
from __future__ import annotations

import time

import pytest

from circuit_breaker import (
    CircuitBreaker,
    CircuitBreakerConfig,
    CircuitState,
    get_breaker,
)


# ── R1：SQLite 持久化 ──────────────────────────────────────────────────────


@pytest.fixture
def isolated_breaker_db(tmp_path, monkeypatch):
    """隔离 DB 到 tmp_path：重置 _db_path_cache + _breakers（模拟干净进程）。"""
    import circuit_breaker as cb

    monkeypatch.setenv("VR_DATA_DIR", str(tmp_path))
    monkeypatch.setattr(cb, "_db_path_cache", None)
    monkeypatch.setattr(cb, "_breakers", {})
    yield tmp_path
    # 清理：重置回默认（monkeypatch 自动恢复）
    monkeypatch.setattr(cb, "_db_path_cache", None)


def test_open_state_persists_across_restart(isolated_breaker_db):
    """R1：OPEN 状态持久化——_breakers 清空（模拟重启）后 get_breaker 加载 OPEN。"""
    import circuit_breaker as cb

    # 创建 breaker，触发 OPEN（5 次 failure = threshold）
    breaker = get_breaker("test_r1_open")
    for _ in range(breaker.config.failure_threshold):
        breaker.record_failure()
    assert breaker.state == CircuitState.OPEN
    assert breaker.last_failure_time > 0

    # 模拟重启：清空内存注册表
    monkeypatch_local = pytest.MonkeyPatch()
    monkeypatch_local.setattr(cb, "_breakers", {})

    # 重新创建——应从 SQLite 加载 OPEN 状态
    breaker2 = get_breaker("test_r1_open")
    assert breaker2.state == CircuitState.OPEN
    assert breaker2.failure_count >= breaker.config.failure_threshold
    assert breaker2.last_failure_time > 0
    monkeypatch_local.undo()


def test_failure_count_persists(isolated_breaker_db):
    """R1：failure_count 持久化（未到 threshold 时也持久化）。"""
    import circuit_breaker as cb

    breaker = get_breaker("test_r1_count")
    # 记录 3 次失败（未到 threshold=5，state 仍 CLOSED）
    for _ in range(3):
        breaker.record_failure()
    assert breaker.state == CircuitState.CLOSED
    assert breaker.failure_count == 3

    # 模拟重启
    mp = pytest.MonkeyPatch()
    mp.setattr(cb, "_breakers", {})
    breaker2 = get_breaker("test_r1_count")
    assert breaker2.state == CircuitState.CLOSED
    assert breaker2.failure_count == 3
    mp.undo()


def test_closed_state_persists_after_recovery(isolated_breaker_db):
    """R1：CLOSED 状态持久化——record_success 后 state=CLOSED 持久化。"""
    import circuit_breaker as cb

    breaker = get_breaker("test_r1_closed")
    # 先触发 OPEN
    for _ in range(breaker.config.failure_threshold):
        breaker.record_failure()
    assert breaker.state == CircuitState.OPEN

    # 模拟 recovery_timeout 过期 → HALF_OPEN → success → CLOSED
    mp = pytest.MonkeyPatch()
    mp.setattr(breaker, "last_failure_time", time.time() - 61)
    assert breaker.peek_state() == CircuitState.HALF_OPEN
    assert breaker.allow_request() is True  # OPEN → HALF_OPEN
    breaker.record_success()
    breaker.record_success()  # success_threshold=2 → CLOSED
    assert breaker.state == CircuitState.CLOSED

    # 模拟重启
    mp.setattr(cb, "_breakers", {})
    breaker2 = get_breaker("test_r1_closed")
    assert breaker2.state == CircuitState.CLOSED
    assert breaker2.failure_count == 0
    mp.undo()


def test_standalone_breaker_no_persistence(isolated_breaker_db):
    """R1：独立 new 的 CircuitBreaker（不经 get_breaker）无持久化回调。"""
    breaker = CircuitBreaker("test_standalone")
    assert breaker._persist_fn is None
    # record_failure 不应报错（_persist 是 no-op）
    breaker.record_failure()
    assert breaker.failure_count == 1


def test_persist_failure_does_not_block_breaker(isolated_breaker_db, monkeypatch):
    """R1：持久化失败不阻断熔断器运行（except 吞 + breaker 仍正常工作）。"""
    import circuit_breaker as cb

    # 让 _init_db 抛异常（模拟 DB 不可用）
    def _boom_init(db_path):
        raise OSError("disk full")
    monkeypatch.setattr(cb, "_init_db", _boom_init)

    breaker = get_breaker("test_r1_persist_fail")
    # record_failure 应正常工作（持久化失败被吞）
    for _ in range(breaker.config.failure_threshold):
        breaker.record_failure()
    assert breaker.state == CircuitState.OPEN


# ── R2：eastmoney breaker 拆 2 组 ───────────────────────────────────────────


def test_select_breaker_name_push2_group():
    """R2：push2/push2his/push2ex/push2delay/np-anotice/searchapi → eastmoney。"""
    from data.transport import _select_breaker_name

    assert _select_breaker_name("https://push2his.eastmoney.com/api/qt/stock/fflow/daykline/get") == "eastmoney"
    assert _select_breaker_name("https://push2.eastmoney.com/api/qt/clist/get") == "eastmoney"
    assert _select_breaker_name("https://push2ex.eastmoney.com/getTopicZTPool") == "eastmoney"
    assert _select_breaker_name("https://push2delay.eastmoney.com/api/qt/stock/get") == "eastmoney"
    assert _select_breaker_name("https://np-anotice-stock.eastmoney.com/api/security/ann") == "eastmoney"
    assert _select_breaker_name("https://searchapi.eastmoney.com/api/suggest/get") == "eastmoney"


def test_select_breaker_name_datacenter_group():
    """R2：datacenter-web → eastmoney_datacenter。"""
    from data.transport import _select_breaker_name

    assert _select_breaker_name("https://datacenter-web.eastmoney.com/api/data/v1/get") == "eastmoney_datacenter"


def test_push2_open_does_not_block_datacenter(isolated_breaker_db):
    """R2：push2 breaker OPEN 不阻断 datacenter breaker（隔离验收）。"""
    push2_breaker = get_breaker("eastmoney")
    dc_breaker = get_breaker("eastmoney_datacenter")

    # 保存初始状态
    saved_push2 = (push2_breaker.state, push2_breaker.failure_count,
                   push2_breaker.last_failure_time, push2_breaker.half_open_calls,
                   push2_breaker.success_count)
    saved_dc = (dc_breaker.state, dc_breaker.failure_count,
                dc_breaker.last_failure_time, dc_breaker.half_open_calls,
                dc_breaker.success_count)

    try:
        # 触发 push2 breaker OPEN
        push2_breaker.state = CircuitState.OPEN
        push2_breaker.last_failure_time = time.time() - 10  # fresh OPEN

        # push2 OPEN → allow_request False
        assert push2_breaker.peek_state() == CircuitState.OPEN
        assert push2_breaker.allow_request() is False

        # datacenter breaker 不受影响 → allow_request True
        assert dc_breaker.state == CircuitState.CLOSED
        assert dc_breaker.allow_request() is True
    finally:
        # 恢复
        (push2_breaker.state, push2_breaker.failure_count,
         push2_breaker.last_failure_time, push2_breaker.half_open_calls,
         push2_breaker.success_count) = saved_push2
        (dc_breaker.state, dc_breaker.failure_count,
         dc_breaker.last_failure_time, dc_breaker.half_open_calls,
         dc_breaker.success_count) = saved_dc


def test_datacenter_open_does_not_block_push2(isolated_breaker_db):
    """R2：datacenter breaker OPEN 不阻断 push2 breaker（反向隔离）。"""
    push2_breaker = get_breaker("eastmoney")
    dc_breaker = get_breaker("eastmoney_datacenter")

    saved_push2 = (push2_breaker.state, push2_breaker.failure_count,
                   push2_breaker.last_failure_time, push2_breaker.half_open_calls,
                   push2_breaker.success_count)
    saved_dc = (dc_breaker.state, dc_breaker.failure_count,
                dc_breaker.last_failure_time, dc_breaker.half_open_calls,
                dc_breaker.success_count)

    try:
        dc_breaker.state = CircuitState.OPEN
        dc_breaker.last_failure_time = time.time() - 10

        assert dc_breaker.allow_request() is False
        assert push2_breaker.state == CircuitState.CLOSED
        assert push2_breaker.allow_request() is True
    finally:
        (push2_breaker.state, push2_breaker.failure_count,
         push2_breaker.last_failure_time, push2_breaker.half_open_calls,
         push2_breaker.success_count) = saved_push2
        (dc_breaker.state, dc_breaker.failure_count,
         dc_breaker.last_failure_time, dc_breaker.half_open_calls,
         dc_breaker.success_count) = saved_dc
