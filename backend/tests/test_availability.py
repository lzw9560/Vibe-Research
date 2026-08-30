# -*- coding: utf-8 -*-
"""S113 R4：诚实缺陷项 availability 测试（TDD）。

对齐 S111 ``test_data_honesty.py`` 的 AAA + monkeypatch + 独立 fixture 风格。覆盖
``registry.md`` 诚实缺陷项 3 条的 availability 修复（非性质撒谎，是健壮性/可恢复性）：

R4.1 chip-breaker 自愈（``akshare_src.chip_distribution``）
    registry ``chip-breaker-permanent-no-recovery``：原手搓 ``_chip_fail_streak`` 连续
    失败 3 次即永久 OPEN（复位仅走成功路径、熔断后不可达）→进程生命周期内永久返 {}
    直到后端重启。S113 对齐通用 ``circuit_breaker``（recovery_timeout + half-open +
    record_success）：OPEN 后 N 秒 half-open 放试探，成功累计复位 CLOSED，失败回 OPEN，
    不再永久 OPEN。返 {} 仍诚实（不臆造数值）。

R4.2 premarket 缺 cache 守卫（``premarket_selection.select_premarket_candidates``）
    registry ``premarket-selection-unguarded-cache-read``：原 ``json.loads(KLINE_CACHE
    .read_bytes())`` 裸读无 exists() 检查，文件缺失抛 FileNotFoundError 冒泡至 endpoint
    全局 handler 返 500（违 S069「dev 无 baostock 降级不崩」契约）。S113 加 exists()+try
    →返 []（附 data-missing note），对齐 ``first_board_filter:359-371`` 守卫范式。

R4.3 scheduled_tasks t1_review 同型守卫（``_compute_t1_returns``）
    registry 兄弟项 ``scheduled_tasks.py:1860``：t1 路径同型裸读同崩（不臆造）。S113 加
    同款 try/except→返 []，缺 cache 不崩（对齐 premarket R4.2 守卫范式）。

impl 并行做中，测试针对 spec 期望行为，完成时可能 RED（正常）——不为过而弱化断言。
"""
from __future__ import annotations

import time

import pytest

import circuit_breaker
from circuit_breaker import CircuitState
from data.sources import akshare_src


# ===========================================================================
# fixtures
# ===========================================================================


@pytest.fixture
def fresh_chip_breaker(monkeypatch):
    """每个用例用全新 chip 熔断器实例（清全局 ``_breakers`` 注册表，避免跨用例/跨模块污染）。

    清空 ``circuit_breaker._breakers`` 后，``chip_distribution`` 内 ``get_breaker``
    会创建全新实例；本 fixture 取同一引用返给用例，以便直接推进 ``last_failure_time``
    模拟 recovery_timeout 流逝（对齐 task「mock breaker 内部 clock」），无需 real sleep。
    """
    monkeypatch.setattr(circuit_breaker, "_breakers", {})
    return circuit_breaker.get_breaker(
        akshare_src._CHIP_BREAKER_NAME, akshare_src._CHIP_BREAKER_CONFIG)


class _FakeAk:
    """假 akshare：``stock_cyq_em`` 按模式抛异常/返 None，统计调用次数（验证「是否真发请求」）。

    fail=True → 抛 RuntimeError（daemon 线程捕获入 exc_holder → ``record_failure``）；
    fail=False → 返 None（线程正常结束、无异常 → ``record_success``，随后 df is None 返 {}）。
    """

    def __init__(self) -> None:
        self.call_count = 0
        self.fail = True

    def stock_cyq_em(self, symbol: str | None = None):  # noqa: D401
        self.call_count += 1
        if self.fail:
            raise RuntimeError("stock_cyq_em 服务断")
        return None  # record_success 路径（df is None → chip_distribution 返 {}）


@pytest.fixture
def fake_ak(monkeypatch):
    """patch ``akshare_src._akshare`` 返假 ak（绕开真实 akshare import + 控成功/失败）。"""
    ak = _FakeAk()
    monkeypatch.setattr(akshare_src, "_akshare", lambda: ak)
    return ak


# ===========================================================================
# R4.1 chip-breaker 自愈：失败3次→OPEN(不发请求)→timeout→half-open试探→成功复位CLOSED
# ===========================================================================


def test_chip_breaker_open_blocks_request_then_self_heals_to_closed(
    fresh_chip_breaker, fake_ak,
):
    """R4.1a：连续失败 3 次→OPEN；OPEN 时返 {} 且不发请求；推进 recovery_timeout 后
    half-open 放试探；试探成功累计达 success_threshold→复位 CLOSED，请求恢复。

    registry ``chip-breaker-permanent-no-recovery``：原手搓计数器熔断后复位仅走成功路径、
    熔断后不可达→进程生命周期内永久 OPEN 直到后端重启。S113 对齐通用 circuit_breaker
    后熔断可自愈——本用例钉死「不再永久 OPEN」：OPEN→half-open→CLOSED 全链路。
    """
    breaker = fresh_chip_breaker
    threshold = akshare_src._CHIP_BREAKER_CONFIG.failure_threshold

    # Arrange：失败模式
    fake_ak.fail = True

    # Act 1：连续失败 threshold 次→熔断 OPEN（每次真发请求，record_failure）
    for _ in range(threshold):
        assert akshare_src.chip_distribution("600519") == {}
    # Assert：熔断开启，threshold 次请求都已发出
    assert breaker.state == CircuitState.OPEN
    assert fake_ak.call_count == threshold

    # Act 2：OPEN 时再调——快速失败返 {}，不应再发请求（短路在 allow_request）
    assert akshare_src.chip_distribution("600519") == {}
    assert fake_ak.call_count == threshold  # 未增加=未发请求

    # Act 3：推进 recovery_timeout（mock breaker 内部 clock，不 real sleep）
    breaker.last_failure_time = time.time() - (breaker.config.recovery_timeout + 5)
    fake_ak.fail = False  # 试探成功模式

    # Act 4：half-open 放试探——成功累计达 success_threshold 复位 CLOSED
    for _ in range(breaker.config.success_threshold):
        assert akshare_src.chip_distribution("600519") == {}

    # Assert：复位 CLOSED（不再永久 OPEN），且 half-open 试探真发了请求
    assert breaker.state == CircuitState.CLOSED
    assert fake_ak.call_count > threshold  # half-open 试探发了请求（call_count 递增）

    # Act 5：CLOSED 后正常发请求（请求恢复，不再被熔断短路）
    calls_before = fake_ak.call_count
    assert akshare_src.chip_distribution("600519") == {}
    assert fake_ak.call_count == calls_before + 1  # CLOSED 状态正常发请求


def test_chip_breaker_half_open_trial_failure_reopens(fresh_chip_breaker, fake_ak):
    """R4.1b：OPEN→推进 timeout→half-open 试探失败→回 OPEN，再发请求被阻断。

    钉死自愈失败路径：half-open 试探若失败，熔断回 OPEN（非永久 OPEN 也非半永久
    HALF_OPEN），下次请求在 recovery_timeout 内被阻断。与 4.1a 互补覆盖自愈全分支。
    """
    breaker = fresh_chip_breaker
    threshold = akshare_src._CHIP_BREAKER_CONFIG.failure_threshold

    # Arrange：失败模式，连续失败 threshold 次→OPEN
    fake_ak.fail = True
    for _ in range(threshold):
        akshare_src.chip_distribution("600519")
    assert breaker.state == CircuitState.OPEN
    calls_after_open = fake_ak.call_count  # = threshold

    # Act 1：推进 recovery_timeout → half-open 放试探
    breaker.last_failure_time = time.time() - (breaker.config.recovery_timeout + 5)

    # Act 2：试探失败（仍 fail 模式）→回 OPEN（record_failure 在 HALF_OPEN 路径回 OPEN）
    assert akshare_src.chip_distribution("600519") == {}
    # Assert：half-open 试探真发了请求（call_count +1），失败后回 OPEN
    assert fake_ak.call_count == calls_after_open + 1
    assert breaker.state == CircuitState.OPEN

    # Act 3：回 OPEN 后 last_failure_time 刚重置为 now，recovery_timeout 内再调→被阻断
    assert akshare_src.chip_distribution("600519") == {}
    assert fake_ak.call_count == calls_after_open + 1  # 未增加=试探失败后被阻断


# ===========================================================================
# R4.2 premarket 缺 cache 守卫：KLINE_CACHE 不存在→返 [] 非 500 + note
# ===========================================================================


def test_premarket_missing_cache_returns_empty_not_500(monkeypatch, tmp_path):
    """R4.2：KLINE_CACHE 不存在→select_premarket_candidates 返 []（非抛 FileNotFoundError 非 500）。

    registry ``premarket-selection-unguarded-cache-read``：原裸读无 exists() 检查，文件缺失
    抛 FileNotFoundError 冒泡至 endpoint 全局 handler 返 500（违 S069「dev 无 baostock 降级
    不崩」契约）。S113 加 exists()+try→返 []，对齐 first_board_filter:359-371 守卫范式。
    """
    from strategies import premarket_selection as pm

    # Arrange：KLINE_CACHE 指向不存在的文件（baostock 未装/首次运行场景）
    missing_cache = tmp_path / "does_not_exist_kline.json"
    assert not missing_cache.exists()
    monkeypatch.setattr(pm, "KLINE_CACHE", missing_cache)

    # Act + Assert：返 [] 非 500 崩（FileNotFoundError 不冒泡）
    assert pm.select_premarket_candidates("2026-08-15") == []


def test_premarket_missing_cache_carries_data_missing_note(monkeypatch, tmp_path):
    """R4.2 配套：缺 cache→select_premarket_with_risk 返空候选 + market_note 标 data-missing
    （下游可见「候选空系降级非无信号」，非旧裸 500）。

    对齐 spec R2「附 data-missing 备注」。calendar_factor 纯本地（holidays.json，零 API），
    无需 mock；cache 缺失时 select_premarket_candidates 早期返 []，_load_code_name_map
    （DB）不被触达，无联网/DB 副作用。
    """
    from strategies import premarket_selection as pm

    # Arrange：KLINE_CACHE 不存在
    monkeypatch.setattr(pm, "KLINE_CACHE", tmp_path / "nope.json")

    # Act
    result = pm.select_premarket_with_risk("2026-08-15")

    # Assert：空候选 + note 标降级（非 500 崩）
    assert result.candidates == []
    assert "缺失" in result.market_note  # data-missing 备注


# ===========================================================================
# R4.3 scheduled_tasks t1_review 同型守卫：缺 cache 不崩
# ===========================================================================


def test_scheduled_tasks_t1_missing_cache_returns_empty_not_crash(monkeypatch, tmp_path):
    """R4.3：scheduled_tasks t1_review 路径缺 cache→_compute_t1_returns 返 [] 不崩（同型守卫）。

    registry 兄弟项 ``scheduled_tasks.py:1860``：t1 路径同型裸读 KLINE_CACHE 同崩（不臆造）。
    S113 加同款 try/except→返 []，缺 cache 不崩（对齐 premarket R4.2 守卫范式）。
    ``_compute_t1_returns`` 内 ``from strategies.premarket_selection import KLINE_CACHE``
    运行时取被 monkeypatch 的常量值，文件不存在→FileNotFoundError 被 except 接住→返 []。
    """
    from strategies import premarket_selection as pm
    import scheduled_tasks as st

    # Arrange：KLINE_CACHE 不存在
    monkeypatch.setattr(pm, "KLINE_CACHE", tmp_path / "nope.json")
    final_cards = [{"code": "600519", "name": "贵州茅台"}]

    # Act + Assert：缺 cache 返 [] 非 FileNotFoundError 崩
    assert st._compute_t1_returns(final_cards, "2026-08-14", "2026-08-15") == []
