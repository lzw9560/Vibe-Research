# -*- coding: utf-8 -*-
"""S134：新浪源熔断器单测。

mirror test_availability.py:143-163（em_get breaker-OPEN 消费侧）+
test_s085_bids_ths.py:171-219（_FakeBreaker 传输侧）+ test_circuit_breaker.py:43-51（状态机）。

覆盖：
- sina_financial/sina_kline breaker OPEN → raise → fetch_merged_periods 吞 [] / kline_resolver 回退
- exception → record_failure + re-raise；empty-200 → record_success（exception-only 契约 R7）
- OPEN→HALF_OPEN→CLOSED 恢复
- anomaly endpoint data_status 诚实缝（R3）
- health 遍历 list_breakers() 报所有 breaker（R4）
"""
from __future__ import annotations

import time

import pytest

from circuit_breaker import CircuitState, get_breaker


class _FakeBreaker:
    """镜像 test_s085_bids_ths._FakeBreaker：记 allow/success/failure 计数。"""

    def __init__(self, allow: bool = True):
        self._allow = allow
        self.allowed = 0
        self.successes = 0
        self.failures = 0

    def allow_request(self) -> bool:
        self.allowed += 1
        return self._allow

    def record_success(self) -> None:
        self.successes += 1

    def record_failure(self) -> None:
        self.failures += 1


class _FakeBreakerOpen(_FakeBreaker):
    """OPEN：allow_request 恒 False（模拟熔断中 fast-fail）。"""

    def __init__(self) -> None:
        super().__init__(allow=False)


# ── A1: sina_financial breaker OPEN → fetch_merged_periods 返 [] ──────────


def test_sina_financial_breaker_open_returns_empty(monkeypatch):
    """sina_financial breaker OPEN → fetch_raw raise → per-table catch 吞成 [] →
    fetch_merged_periods 返 []（不抛冒泡，sina_financial.py:93-104 容错契约）。"""
    from data.sources import sina_financial

    monkeypatch.setattr(sina_financial, "get_breaker", lambda name: _FakeBreakerOpen())
    assert sina_financial.fetch_merged_periods("600519") == []


# ── A2: sina_kline breaker OPEN → fetch_raw raise → kline_resolver 回退 ──


def test_sina_kline_breaker_open_raises_and_resolver_falls_through(monkeypatch):
    """sina_kline breaker OPEN → sina.fetch_raw raise RuntimeError →
    kline_resolver.catch → 回退下一源；baidu 亦失败 → ([], None)。"""
    from data.sources import sina
    from data.sources import kline_resolver

    monkeypatch.setattr(sina, "get_breaker", lambda name: _FakeBreakerOpen())

    def _baidu_boom(code):
        raise ConnectionError("baidu down")

    monkeypatch.setattr(kline_resolver, "_baidu", _baidu_boom)
    bars, src = kline_resolver.fetch_kline("600519", sources=["baidu", "sina"])
    assert bars == []
    assert src is None


# ── A3: _fetch_json raise → record_failure + re-raise ─────────────────────


def test_sina_breaker_records_failure_on_exception(monkeypatch):
    """_fetch_json raise（net error）→ record_failure + re-raise（exception-only 契约）。"""
    from data.sources import sina

    breaker = _FakeBreaker()
    monkeypatch.setattr(sina, "get_breaker", lambda name: breaker)

    def _boom(code, datalen=1023):
        raise ConnectionError("sina down")

    monkeypatch.setattr(sina, "_fetch_json", _boom)
    with pytest.raises(ConnectionError):
        sina.fetch_raw("600519")
    assert breaker.failures == 1
    assert breaker.successes == 0


# ── A4a: sina._fetch_json 返 []（empty-200，list[dict] 合法空）→ record_success ─


def test_sina_kline_breaker_records_success_on_empty_list(monkeypatch):
    """sina._fetch_json（kline，返 list[dict]）返 []（empty-200）→ record_success
    （非 failure，exception-only 契约 R7）。"""
    from data.sources import sina

    breaker = _FakeBreaker()
    monkeypatch.setattr(sina, "get_breaker", lambda name: breaker)
    monkeypatch.setattr(sina, "_fetch_json", lambda code, datalen=1023: [])
    sina.fetch_raw("600519")
    assert breaker.successes == 1
    assert breaker.failures == 0


# ── A4b: sina_financial._fetch_json 返空 dict（empty-200）→ record_success ──


def test_sina_financial_breaker_records_success_on_empty_dict(monkeypatch):
    """sina_financial._fetch_json（返 dict）返 {"result":{"data":{}}}（empty-200，
    _parse:56 转成 []）→ record_success。**不能**用 bare []——_fetch_json 返 dict，
    bare [] 会触发 d.get AttributeError 走 failure 路径（review confirmed G）。"""
    from data.sources import sina_financial

    breaker = _FakeBreaker()
    monkeypatch.setattr(sina_financial, "get_breaker", lambda name: breaker)
    monkeypatch.setattr(
        sina_financial,
        "_fetch_json",
        lambda code, report_type="lrb", num=8: {"result": {"data": {}}},
    )
    sina_financial.fetch_raw("600519", "lrb")
    assert breaker.successes == 1
    assert breaker.failures == 0


# ── A5: OPEN→61s→HALF_OPEN→2 success→CLOSED（mirror test_circuit_breaker:43-51）─


def test_sina_breaker_open_half_open_recovery(sina_breaker):
    """OPEN→recovery_timeout 满→peek_state HALF_OPEN→allow_request True→
    2×record_success→CLOSED（success_threshold=2）。"""
    breaker = get_breaker("sina_financial")
    breaker.state = CircuitState.OPEN
    breaker.last_failure_time = time.time() - 61  # > 60s recovery_timeout
    assert breaker.peek_state() == CircuitState.HALF_OPEN
    assert breaker.allow_request() is True
    breaker.record_success()
    breaker.record_success()
    assert breaker.state == CircuitState.CLOSED


# ── A6: anomaly endpoint breaker OPEN → data_status='sina_breaker_open' ────


def test_anomaly_endpoint_breaker_open_data_status(sina_breaker, monkeypatch):
    """breaker fresh OPEN → fetch_merged_periods 返 []（raise 被 per-table catch）→
    get_anomaly peek sina_financial breaker OPEN → data_status='sina_breaker_open'
    （R3 诚实缝：区分 breaker-OPEN vs 真无财报）。"""
    from data.sources import sina_financial
    import routers.value_funnel as vf

    breaker = get_breaker("sina_financial")
    breaker.state = CircuitState.OPEN
    breaker.last_failure_time = time.time() - 10  # fresh OPEN (<60s)

    monkeypatch.setattr(sina_financial, "get_breaker", lambda name: breaker)
    result = vf.get_anomaly("600519")
    assert result["data_status"] == "sina_breaker_open"
    assert result["period_count"] == 0


def test_anomaly_endpoint_closed_empty_marks_missing(sina_breaker, monkeypatch):
    """breaker CLOSED + fetch_merged_periods 返 []（真无财报）→ data_status='missing'。"""
    from data.sources import sina_financial
    import routers.value_funnel as vf

    monkeypatch.setattr(
        "routers.value_funnel.fetch_merged_periods",
        lambda code: [],
        raising=False,
    )
    # get_anomaly late-import fetch_merged_periods；patch 模块级 + raising=False 兜底
    monkeypatch.setattr(sina_financial, "fetch_merged_periods", lambda code: [])
    result = vf.get_anomaly("600519")
    assert result["data_status"] == "missing"
    assert result["period_count"] == 0


# ── A7: health 遍历 list_breakers() 报所有 breaker ─────────────────────────


def test_health_reports_all_breakers(sina_breaker):
    """注册 eastmoney+sina_financial+sina_kline → health 返 detail（worst-state
    string）+ breakers dict 含三项。不假设全局干净态（其他测试可能留 eastmoney/ths
    OPEN 未清理——预先存在的卫生问题，非本 spec 引入）；改用受控 OPEN 场景断言
    确切行为：设 sina_financial fresh OPEN → ok=False + detail=circuit_breaker_open。"""
    get_breaker("eastmoney")
    get_breaker("sina_financial")
    get_breaker("sina_kline")
    from routers.health import _check_circuit_breaker

    result = _check_circuit_breaker()
    # 三 breaker 均在 breakers dict 报告（per-breaker state + failure_count）
    assert "eastmoney" in result["breakers"]
    assert "sina_financial" in result["breakers"]
    assert "sina_kline" in result["breakers"]
    for d in result["breakers"].values():
        assert "state" in d and "failure_count" in d
    # detail 是 worst-state string（backward-compat test_circuit_breaker:127/139）
    assert result["detail"].startswith("circuit_breaker_")

    # 受控场景：设 sina_financial fresh OPEN（<60s）→ ok=False + detail=open
    br = get_breaker("sina_financial")
    br.state = CircuitState.OPEN
    br.last_failure_time = time.time() - 10  # fresh OPEN
    result2 = _check_circuit_breaker()
    assert result2["ok"] is False
    assert result2["detail"] == "circuit_breaker_open"
    assert result2["breakers"]["sina_financial"]["state"] == "open"
