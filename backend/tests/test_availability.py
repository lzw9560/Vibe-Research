# -*- coding: utf-8 -*-
"""诚实缺陷项 + chip-cyq availability 测试（S113 R4.2/R4.3 + S114 R10）。

对齐 S111 ``test_data_honesty.py`` 的 AAA + monkeypatch + 独立 fixture 风格。

R4.2 premarket 缺 cache 守卫（S113，``premarket_selection.select_premarket_candidates``）
    registry ``premarket-selection-unguarded-cache-read``：原裸读无 exists() 检查，文件缺失
    抛 FileNotFoundError 冒泡至 endpoint 全局 handler 返 500（违 S069「dev 无 baostock 降级
    不崩」契约）。S113 加 exists()+try→返 []，对齐 ``first_board_filter:359-371`` 守卫范式。

R4.3 scheduled_tasks t1_review 同型守卫（S113，``_compute_t1_returns``）
    registry 兄弟项 ``scheduled_tasks.py:1860``：t1 路径同型裸读同崩（不臆造）。S113 加
    同款 try/except→返 []，缺 cache 不崩（对齐 premarket R4.2 守卫范式）。

R4.1 chip-breaker 自愈（S113）→ **S114 supersede**：S114 把 chip_distribution 取数层
    改自建走 em_get（R10），em_get 自带 breaker('eastmoney') 已覆盖熔断自愈，chip 级
    breaker（_CHIP_BREAKER_NAME）冗余已删（对齐 hot_money_seats 复用范式）。R4.1 测试随
    S114 删除，em_get breaker-OPEN 路径由 R10 ``test_chip_distribution_em_get_breaker_open_returns_empty`` 覆盖。

R10 chip-cyq 自建走 em_get（S114）：offline fallback 4 态 + live AC1，见下文。
"""
from __future__ import annotations

from types import SimpleNamespace

import pytest

from data.sources import akshare_src


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


# ===========================================================================
# S114 R10：chip_distribution 自建走 em_get —— offline fallback 4 态 + live AC1
# 对齐 S111/S113 AAA + monkeypatch 风格。impl 并行做中，测试针对 spec 期望行为，
# 完成时可能 RED（正常）——不为过而弱化断言。
#
# 范式：S114 把 chip_distribution 取数层从 ak.stock_cyq_em 黑盒（裸 requests 无防封）
# 改为自建 _fetch_cyq_klines 走 em_get（push2his kline/get + ut=_ZTB_UT 日K token）。
# em_get 自带 breaker('eastmoney') + 0.3s 限流 + 代理探测 + UA + timeout=8（真实
# socket 超时，根因消除 S094 daemon 8s 线程硬截断）。计算层保真复用东财原 JS
# （cyq_js.CYQ_JS + py_mini_racer，策略 A）。返 {} 4 态诚实降级（R3），不臆造数值。
#
# 关键 mock 目标：_fetch_cyq_klines 内 `from data.transport import eastmoney_get as
# em_get`（late import，每次 call 重读 data.transport.eastmoney_get 属性）→ patch
# data.transport.eastmoney_get 即拦截（非模块级 em_get，后者 inert）。兜底 patch
# akshare_src.em_get（raising=False）覆盖未来改为模块级 `as em_get` 绑定形态。
# ===========================================================================


@pytest.fixture
def em_get_mock(monkeypatch):
    """拦截 ``_fetch_cyq_klines`` 的 em_get（late-import ``data.transport.eastmoney_get``
    + 兜底 ``akshare_src.em_get`` raising=False，覆盖 late-import 与模块级绑定两形态）。

    用例设 ``.fn``（callable，控 raise / return response）；``.calls`` 计数验证 fallback
    路径真触达 em_get（非被某早返路径绕过，对齐 S113 ``_FakeAk.call_count`` 验证范式）。
    """
    holder = SimpleNamespace(fn=None, calls=0)

    def _fake(url, *a, **k):
        holder.calls += 1
        if holder.fn is None:
            raise AssertionError("test 未设 em_get 行为")
        return holder.fn(url, *a, **k)

    monkeypatch.setattr("data.transport.eastmoney_get", _fake)
    # 兜底：若 impl 改为模块级 `from data.transport import eastmoney_get as em_get`，
    # patch data.transport.eastmoney_get 对已绑定名 inert → 此处 patch akshare_src.em_get
    # 接管（raising=False 容许当前 late-import 形态下该名不存在）。
    monkeypatch.setattr(akshare_src, "em_get", _fake, raising=False)
    return holder


def test_chip_distribution_em_get_breaker_open_returns_empty(em_get_mock):
    """R3-1：em_get 熔断 OPEN（raise RuntimeError，transport.py:74 breaker-OPEN 快速失败
    信号）→ chip_distribution 返 {}（不抛冒泡至 diagnosis.py:229）。

    S114 自建走 em_get，em_get 内 breaker('eastmoney') OPEN 时 raise RuntimeError
    快速失败。chip_distribution try/except（akshare_src._fetch_cyq_klines:162）接住 →
    返 None → chip_distribution:218 ``if not klines: return {}``。钉死熔断信号不冒泡。
    """
    # Arrange：em_get 熔断 OPEN raise（transport.py:74 真实信号）
    def _breaker_open(url, *a, **k):
        raise RuntimeError("[CircuitBreaker:eastmoney] 东财数据源熔断中，快速失败")
    em_get_mock.fn = _breaker_open

    # Act
    result = akshare_src.chip_distribution("600519")

    # Assert：fallback 路径真触达 em_get + 返 falsy {}（非抛、非 truthy dict）
    assert em_get_mock.calls >= 1
    assert result == {}                              # R3：empty fallback
    assert not result                                # A5：falsy → diagnosis if _result 走 missing
    assert "chip_profit_ratio" not in result         # R4：非 {chip_profit_ratio:None} truthy 绕过


def test_chip_distribution_em_get_request_exception_returns_empty(em_get_mock):
    """R3-2：em_get 请求异常（连接断 / socket 超时，非 breaker-OPEN 短路）→ {}。

    区别 R3-1：此为 em_get 内 requests 抛 ConnectionError/Timeout（transport:101-103
    record_failure 后 re-raise），非 breaker 短路 raise RuntimeError。chip_distribution
    同 except（_fetch_cyq_klines:162）接住 → None → {}。钉死两类异常都不冒泡至 diagnosis。
    """
    # Arrange：em_get 请求异常（非熔断短路，是传输层 re-raise）
    def _conn_err(url, *a, **k):
        raise ConnectionError("push2his 断连/超时")
    em_get_mock.fn = _conn_err

    # Act
    result = akshare_src.chip_distribution("600519")

    # Assert
    assert em_get_mock.calls >= 1
    assert result == {}
    assert not result
    assert "chip_profit_ratio" not in result


def test_chip_distribution_no_chip_data_returns_empty(em_get_mock):
    """R3-3：em_get 200 但无筹码（body klines 空 / 该股无 CYQ 行，如新股）→ {}。

    push2his 对无筹码股返 ``{"data": {"klines": []}}``（200 body 空非服务故障）。
    _fetch_cyq_klines:168-170 ``klines = (data.get('data') or {}).get('klines')`` →
    空 → ``if not klines: return None`` → chip_distribution:218 返 {}。诚实降级不臆造。
    """
    # Arrange：200 但 klines 空（该股无筹码，非服务故障）
    em_get_mock.fn = lambda url, *a, **k: SimpleNamespace(
        json=lambda: {"data": {"klines": []}})

    # Act
    result = akshare_src.chip_distribution("600519")

    # Assert
    assert em_get_mock.calls >= 1
    assert result == {}
    assert not result
    assert "chip_profit_ratio" not in result


def test_chip_distribution_malformed_klines_returns_empty(em_get_mock):
    """R3-4：em_get 200 但 klines 坏格式（字段缺失，无法解析为 CYQ 输入）→ {}。

    _fetch_cyq_klines:179-195 逐行 split + 校验：``len(parts) < 11`` 的行 continue 跳过；
    有效行不足 90 条（R9 guard）→ 返 None → chip_distribution:218 返 {}。钉死坏格式
    不崩、诚实降级（非抛、非 truthy dict 喂 diagnosis 假信号）。
    """
    # Arrange：klines 坏格式——每行仅 2 字段（< f51..f61 共 11 字段）→ 全 skip → 有效 0 < 90
    bad_klines = ["bad,format"] * 95
    em_get_mock.fn = lambda url, *a, **k: SimpleNamespace(
        json=lambda: {"data": {"klines": bad_klines}})

    # Act
    result = akshare_src.chip_distribution("600519")

    # Assert
    assert em_get_mock.calls >= 1
    assert result == {}
    assert not result
    assert "chip_profit_ratio" not in result


@pytest.mark.live
def test_chip_distribution_live_returns_nonempty_with_numeric_ratio():
    """R10 AC1：chip_distribution('600519') 实跑，返非空 dict 含 chip_profit_ratio 数值。

    验证 ut=_ZTB_UT（日K通用公开 token）+ py_mini_racer 保真：600519（贵州茅台，长期
    流通有筹码）push2his 日K + hsl 取数成功 → CYQCalculator 算出 benefitPart（0-1 获利
    比例，CYQCalculator:205 below/totalChips）。offline ``-m 'not live'`` 跳过本用例。
    R6 5 键 shape 不变：chip_profit_ratio / avg_cost / concentration / 90_cost / 70_cost。

    注：若本机被东财 push2his kline/get 拒连（RemoteDisconnected，反爬/IP 针对性拒绝，
    akshare 原版同款拒连），换网络环境或待东财恢复再跑——非实现缺陷（em_get 防封工作，
    失败诚实返 {}）。
    """
    # Act：实跑（联网，em_get 走真实 push2his kline/get）
    result = akshare_src.chip_distribution("600519")

    # Assert：非空 dict + chip_profit_ratio 数值（AC1，ut + py_mini_racer 保真）
    assert isinstance(result, dict) and result, "live chip_distribution 应返非空 dict"
    ratio = result.get("chip_profit_ratio")
    assert ratio is not None and isinstance(ratio, (int, float)), \
        f"chip_profit_ratio 应为数值（AC1），实得 {ratio!r}"
    assert 0 <= ratio <= 1, f"benefitPart 获利比例应 0-1（below/totalChips），实得 {ratio}"
    # R6：5 键 shape 不变（值可 None 经 g() 清洗，键必在）
    for key in ("avg_cost", "concentration", "90_cost", "70_cost"):
        assert key in result, f"R6 5-key shape 缺键 {key}"
