# -*- coding: utf-8 -*-
"""baostock_src 限流 + 熔断测试（防 IP 封禁）。

不调真 baostock——mock bs.login / bs.query_history_k_data_plus。
测试：
1. 限流：连续 2 次调用间隔 >= 0.3s
2. 熔断：5 次连续失败 -> OPEN（快速失败）
3. 恢复：60s 后 HALF_OPEN 恢复
"""
import sys
import time
from unittest.mock import MagicMock

import pytest

from circuit_breaker import CircuitState, get_breaker
from data.sources import baostock_src
from data.sources._common import DependencyMissing


# ── fixtures ─────────────────────────────────────────────────────────────────

@pytest.fixture
def baostock_breaker():
    """保存/恢复 baostock 全局 breaker 状态 + 重置为干净 CLOSED（镜像 conftest.sina_breaker）。"""
    br = get_breaker("baostock")
    saved = (br.state, br.failure_count, br.last_failure_time,
             br.half_open_calls, br.success_count)
    # Reset to clean CLOSED state
    br.state = CircuitState.CLOSED
    br.failure_count = 0
    br.success_count = 0
    br.last_failure_time = 0.0
    br.half_open_calls = 0
    yield br
    (br.state, br.failure_count, br.last_failure_time,
     br.half_open_calls, br.success_count) = saved


@pytest.fixture
def reset_bs_state():
    """重置 baostock_src 模块级状态（_BS_READY / _bs_last_call），防跨测试污染。"""
    saved_ready = baostock_src._BS_READY
    saved_last_call = baostock_src._bs_last_call[0]
    baostock_src._BS_READY = False
    baostock_src._bs_last_call[0] = 0.0
    yield
    baostock_src._BS_READY = saved_ready
    baostock_src._bs_last_call[0] = saved_last_call


def _mock_baostock_ok(monkeypatch):
    """Mock baostock 模块：login 成功 + query 返空结果（error_code='0'）。"""
    mock_bs = MagicMock()
    mock_login = MagicMock()
    mock_login.error_code = "0"
    mock_login.error_msg = ""
    mock_bs.login.return_value = mock_login

    mock_rs = MagicMock()
    mock_rs.error_code = "0"
    mock_rs.next.return_value = False  # no rows
    mock_bs.query_history_k_data_plus.return_value = mock_rs

    monkeypatch.setitem(sys.modules, "baostock", mock_bs)
    return mock_bs


def _mock_baostock_login_fail(monkeypatch, error_code="10001011", error_msg="banned"):
    """Mock baostock 模块：login 失败（黑名单）。"""
    mock_bs = MagicMock()
    mock_login = MagicMock()
    mock_login.error_code = error_code
    mock_login.error_msg = error_msg
    mock_bs.login.return_value = mock_login
    monkeypatch.setitem(sys.modules, "baostock", mock_bs)
    return mock_bs


# ── 限流测试 ────────────────────────────────────────────────────────────────

def test_rate_limit_enforces_min_interval(monkeypatch, baostock_breaker, reset_bs_state):
    """限流：连续 2 次调用间隔 >= 0.3s（真实 sleep，非 mock）。"""
    mock_bs = _mock_baostock_ok(monkeypatch)
    baostock_src._BS_READY = True  # 跳过 login，测 query 限流

    t0 = time.time()
    baostock_src.fetch_bars("600000", "2026-01-01", "2026-01-02")
    baostock_src.fetch_bars("600000", "2026-01-01", "2026-01-02")
    elapsed = time.time() - t0

    # 第二次调用触发 sleep(>=0.3 + jitter 0.05-0.15)，总耗时 >= 0.3s
    assert elapsed >= 0.3, f"限流未生效：两次调用仅耗时 {elapsed:.3f}s < 0.3s"
    assert mock_bs.query_history_k_data_plus.call_count >= 2


def test_rate_limit_no_sleep_on_first_call(monkeypatch, baostock_breaker, reset_bs_state):
    """首次调用（last_call=0）不 sleep——wait = 0.3 - (now - 0) = 负数。"""
    _mock_baostock_ok(monkeypatch)
    baostock_src._BS_READY = True
    baostock_src._bs_last_call[0] = 0.0

    sleeps = []
    monkeypatch.setattr(baostock_src.time, "sleep", lambda s: sleeps.append(s))

    baostock_src.fetch_bars("600000", "2026-01-01", "2026-01-02")
    assert sleeps == [], f"首次调用不应 sleep，但 sleep 被调了: {sleeps}"


def test_rate_limit_sleeps_on_rapid_second_call(monkeypatch, baostock_breaker, reset_bs_state):
    """第二次调用紧接第一次 -> sleep 被调（wait > 0）。"""
    _mock_baostock_ok(monkeypatch)
    baostock_src._BS_READY = True
    monkeypatch.setattr(baostock_src.random, "uniform", lambda a, b: 0.0)

    sleeps = []
    monkeypatch.setattr(baostock_src.time, "sleep", lambda s: sleeps.append(s))

    # 第一次：last_call=0 -> wait<0 -> 不 sleep
    baostock_src.fetch_bars("600000", "2026-01-01", "2026-01-02")
    # 第二次：last_call 刚更新 -> wait>0 -> sleep
    baostock_src.fetch_bars("600000", "2026-01-01", "2026-01-02")

    assert len(sleeps) >= 1, "第二次调用应触发 sleep（限流间隔）"
    assert sleeps[0] >= 0.2, f"sleep 时长应接近 0.3s，实际 {sleeps[0]:.3f}s"


# ── 熔断器测试 ───────────────────────────────────────────────────────────────

def test_login_failure_records_failure(monkeypatch, baostock_breaker, reset_bs_state):
    """login 失败（黑名单 10001011）-> record_failure（failure_count +1）。"""
    _mock_baostock_login_fail(monkeypatch)
    monkeypatch.setattr(baostock_src.time, "sleep", lambda s: None)  # 跳过限流 sleep

    breaker = baostock_breaker
    assert breaker.failure_count == 0

    with pytest.raises(DependencyMissing):
        baostock_src.ensure_login()
    assert breaker.failure_count == 1
    assert breaker.state == CircuitState.CLOSED  # 1 次不够 OPEN


def test_circuit_breaker_opens_after_5_login_failures(monkeypatch, baostock_breaker, reset_bs_state):
    """熔断：5 次连续 login 失败（黑名单）-> OPEN。"""
    _mock_baostock_login_fail(monkeypatch)
    monkeypatch.setattr(baostock_src.time, "sleep", lambda s: None)

    breaker = baostock_breaker
    assert breaker.state == CircuitState.CLOSED

    for _ in range(5):
        with pytest.raises(DependencyMissing):
            baostock_src.ensure_login()

    assert breaker.state == CircuitState.OPEN
    assert breaker.failure_count >= 5


def test_circuit_breaker_fast_fails_when_open(monkeypatch, baostock_breaker, reset_bs_state):
    """熔断 OPEN 后：fetch_bars 快速失败返 []，不调 query。"""
    mock_bs = _mock_baostock_ok(monkeypatch)
    breaker = baostock_breaker
    # 手动设为 OPEN（模拟已熔断，刚发生 failure）
    breaker.state = CircuitState.OPEN
    breaker.failure_count = 5
    breaker.last_failure_time = time.time()  # 刚熔断，不到 60s
    baostock_src._BS_READY = True  # 跳过 login，直接到 query 的 breaker check

    result = baostock_src.fetch_bars("600000", "2026-01-01", "2026-01-02")

    assert result == []  # 快速失败返空
    assert mock_bs.query_history_k_data_plus.call_count == 0  # 未调 query


def test_circuit_breaker_recovers_after_60s(monkeypatch, baostock_breaker, reset_bs_state):
    """熔断 60s 后 HALF_OPEN 恢复：请求能通过。"""
    mock_bs = _mock_baostock_ok(monkeypatch)
    monkeypatch.setattr(baostock_src.time, "sleep", lambda s: None)

    breaker = baostock_breaker
    # 模拟 61s 前熔断 -> 超过 recovery_timeout(60s)
    breaker.state = CircuitState.OPEN
    breaker.failure_count = 5
    breaker.last_failure_time = time.time() - 61
    baostock_src._BS_READY = True  # 跳过 login

    # allow_request 应转 HALF_OPEN 并返 True
    assert breaker.allow_request() is True
    assert breaker.state == CircuitState.HALF_OPEN

    # fetch_bars 应该能正常执行（query 被调，非 fast-fail）
    result = baostock_src.fetch_bars("600000", "2026-01-01", "2026-01-02")
    assert mock_bs.query_history_k_data_plus.call_count >= 1


def test_successful_query_records_success(monkeypatch, baostock_breaker, reset_bs_state):
    """成功 query -> record_success（failure_count 归零）。"""
    _mock_baostock_ok(monkeypatch)
    baostock_src._BS_READY = True
    monkeypatch.setattr(baostock_src.time, "sleep", lambda s: None)

    breaker = baostock_breaker
    breaker.failure_count = 3  # 模拟有 3 次历史失败

    baostock_src.fetch_bars("600000", "2026-01-01", "2026-01-02")
    assert breaker.failure_count == 0  # 成功后归零
    assert breaker.state == CircuitState.CLOSED


def test_query_exception_records_failure(monkeypatch, baostock_breaker, reset_bs_state):
    """query 异常 -> record_failure + 返 []（不静默吞错）。"""
    mock_bs = _mock_baostock_ok(monkeypatch)
    # 让 query 抛异常
    mock_bs.query_history_k_data_plus.side_effect = ConnectionError("baostock down")
    baostock_src._BS_READY = True
    monkeypatch.setattr(baostock_src.time, "sleep", lambda s: None)

    breaker = baostock_breaker
    result = baostock_src.fetch_bars("600000", "2026-01-01", "2026-01-02")

    assert result == []  # 异常 -> 返空（不崩）
    assert breaker.failure_count == 1  # 记录了失败
