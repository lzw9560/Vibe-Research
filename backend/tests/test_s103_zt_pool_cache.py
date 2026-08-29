# -*- coding: utf-8 -*-
"""S103 涨停池缓存承重切片测试——盘中陈旧快照根因治理。

契约（spec §6 验收标准）：
- A1 成功返数据 → 缓存写入 + TTL 内命中
- A2 失败/熔断 → 返 [] 且 _ztb_cache 不写入空（下次重试）
- A3 非交易日 24h / 今日盘中 60s / 今日盘后 1h / 历史日 24h
- A4 盘中 60s TTL：同窗口命中缓存（防并发放大）
- A5 vr_paths.is_intraday_time 行为（周六 False / 交易日10:00 True / 12:00 False）
- A6 seal_intraday.is_intraday_trading_time re-export 行为一致
"""
from __future__ import annotations

from datetime import datetime
from unittest.mock import MagicMock, patch

import pytest

from data.sources import eastmoney as em
from data.sources.eastmoney import _ztb_cache, _ztb_cache_ttl, em_zt_topic_pool
from vr_paths import INTRADAY_PERIODS, is_intraday_time


@pytest.fixture(autouse=True)
def _clear_cache():
    """每个用例前清涨停池缓存，防串扰。"""
    _ztb_cache.clear()
    yield
    _ztb_cache.clear()


# ──────────────────────────────────────────────────────────────────────────────
# A1 / A2：缓存写入 + 空结果不缓存
# ──────────────────────────────────────────────────────────────────────────────


class TestCacheWrite:
    def test_success_writes_cache_and_hits(self):
        """A1：成功返数据 → 缓存写入 + TTL 内命中（不重打 em_get）。"""
        fake_pool = [{"c": "000001", "n": "平安银行"}]

        def fake_em_get(*a, **kw):
            resp = MagicMock()
            resp.json.return_value = {"data": {"pool": fake_pool}}
            return resp

        with patch.object(em, "em_get", side_effect=fake_em_get) as mock_get:
            r1 = em_zt_topic_pool("getTopicZTPool", "20260801", "fbt:asc")
            r2 = em_zt_topic_pool("getTopicZTPool", "20260801", "fbt:asc")
            assert r1 == fake_pool
            assert r2 == fake_pool  # TTL 内命中，返同
            assert mock_get.call_count == 1  # 第二次命中缓存，未重打 em_get
            assert ("getTopicZTPool", "20260801", "fbt:asc") in _ztb_cache

    def test_failure_returns_empty_and_no_cache(self):
        """A2：em_get 失败/熔断 raise → 返 [] 且不写空缓存（下次重试）。"""
        def fake_em_get_fail(*a, **kw):
            raise RuntimeError("breaker OPEN 模拟熔断")

        with patch.object(em, "em_get", side_effect=fake_em_get_fail):
            r = em_zt_topic_pool("getTopicZTPool", "20260801", "fbt:asc")
            assert r == []
            # 关键：失败不写空缓存——下次请求直接重试（非等 24h）
            assert ("getTopicZTPool", "20260801", "fbt:asc") not in _ztb_cache

    def test_empty_pool_success_does_not_cache(self):
        """A2 边界：em_get 成功但 pool=[]（健康真空）→ 不缓存（下次重试）。

        grill 第 2 轮：实测 push2ex 成功 response 恒 pool 非空，此分支在当前端点
        实际不触发；但代码用 ``if result`` 保险，健康真空也不毒缓存。
        """
        def fake_em_get_empty(*a, **kw):
            resp = MagicMock()
            resp.json.return_value = {"data": {"pool": []}}
            return resp

        with patch.object(em, "em_get", side_effect=fake_em_get_empty):
            r = em_zt_topic_pool("getTopicZTPool", "20260801", "fbt:asc")
            assert r == []
            assert ("getTopicZTPool", "20260801", "fbt:asc") not in _ztb_cache


# ──────────────────────────────────────────────────────────────────────────────
# A3：TTL 分级
# ──────────────────────────────────────────────────────────────────────────────


class TestTTLGrading:
    @pytest.mark.parametrize("is_trading_day_ret, date_matches_today, is_intraday_ret, expected_ttl", [
        # 非交易日（date.today() 非交易日）→ 24h，不管查什么 date
        (False, False, False, em._ZTB_CACHE_TTL_HISTORY),
        # 交易日 + 历史日（date != 今日）→ 24h
        (True, False, True, em._ZTB_CACHE_TTL_HISTORY),
        (True, False, False, em._ZTB_CACHE_TTL_HISTORY),
        # 交易日 + 今日 + 盘中 → 60s
        (True, True, True, em._ZTB_CACHE_TTL_INTRADAY),
        # 交易日 + 今日 + 盘后 → 1h
        (True, True, False, em._ZTB_CACHE_TTL_POSTMARKET),
    ])
    def test_ttl_grading(self, monkeypatch, is_trading_day_ret, date_matches_today,
                         is_intraday_ret, expected_ttl):
        """A3：非交易日 24h / 历史日 24h / 今日盘中 60s / 今日盘后 1h。

        三个 vr_paths 函数全部 patch（is_trading_day + is_intraday_time +
        last_trading_date_str）——避免"patch 前后 last_trading_date_str 返回值不一致"
        导致 date vs 内部比对 mismatch（grill 实现期定位：测试在 patch 前算 date
        用真实回退值，patch 后内部 last_trading_date_str 走 patched is_trading_day
        返不同值，date != 今日 误判历史日）。
        """
        import vr_paths
        TODAY = "20260828"  # 固定今日紧凑日期，避免依赖真实日期
        monkeypatch.setattr(vr_paths, "is_trading_day", lambda d=None: is_trading_day_ret)
        monkeypatch.setattr(vr_paths, "is_intraday_time", lambda now=None: is_intraday_ret)
        monkeypatch.setattr(vr_paths, "last_trading_date_str", lambda d=None: "2026-08-28")
        date = TODAY if date_matches_today else "20260801"
        assert _ztb_cache_ttl(date) == expected_ttl

    def test_saturday_query_friday_is_history_not_postmarket(self, monkeypatch):
        """grill 第 4 轮：周六查周五数据应判历史日 24h，非"今日盘后 1h"。

        关键：非交易日判定用 is_trading_day(date.today()) 而非 last_trading_date_str()。
        周六 date.today() 非交易日 → 直接走 24h，不进盘中/盘后分支。
        """
        import vr_paths
        # 模拟周六：is_trading_day() 无参返 False（date.today() 是周六非交易日）
        monkeypatch.setattr(vr_paths, "is_trading_day", lambda d=None: False)
        monkeypatch.setattr(vr_paths, "is_intraday_time", lambda now=None: False)
        monkeypatch.setattr(vr_paths, "last_trading_date_str", lambda d=None: "2026-08-28")
        # 查周五数据（20260828，等于 last_trading_date_str()）
        # 但 is_trading_day()=False → 直接 24h，不进 date 比较分支
        assert _ztb_cache_ttl("20260828") == em._ZTB_CACHE_TTL_HISTORY


# ──────────────────────────────────────────────────────────────────────────────
# A4：盘中 60s TTL 防并发放大
# ──────────────────────────────────────────────────────────────────────────────


class TestIntradayCache:
    def test_intraday_60s_same_window_hits_cache(self):
        """A4：盘中 TTL=60s，同窗口（<60s）第二次调用命中缓存，防并发放大。"""
        call_count = 0

        def fake_em_get_vary(*a, **kw):
            nonlocal call_count
            call_count += 1
            resp = MagicMock()
            resp.json.return_value = {"data": {"pool": [{"v": call_count}]}}
            return resp

        with patch.object(em, "_ztb_cache_ttl", return_value=60), \
             patch.object(em, "em_get", side_effect=fake_em_get_vary):
            r_a = em_zt_topic_pool("getTopicZTPool", "20260801", "fbt:asc")
            r_b = em_zt_topic_pool("getTopicZTPool", "20260801", "fbt:asc")
            assert r_a == r_b  # 同窗口命中，返同
            assert call_count == 1  # 第二次命中缓存，未重打

    def test_intraday_expired_re_fetches(self):
        """A4：盘中 TTL 过期后重新打 em_get 拿最新（不命中陈旧）。"""
        call_count = 0

        def fake_em_get_vary(*a, **kw):
            nonlocal call_count
            call_count += 1
            resp = MagicMock()
            resp.json.return_value = {"data": {"pool": [{"v": call_count}]}}
            return resp

        with patch.object(em, "_ztb_cache_ttl", return_value=60), \
             patch.object(em, "em_get", side_effect=fake_em_get_vary):
            r_a = em_zt_topic_pool("getTopicZTPool", "20260801", "fbt:asc")
            # 手动让缓存过期（模拟 60s 后）
            from data.sources.eastmoney import _ztb_cache as cache
            ts_old = list(cache.values())[0]
            cache[("getTopicZTPool", "20260801", "fbt:asc")] = (ts_old[0] - 61, ts_old[1])
            r_b = em_zt_topic_pool("getTopicZTPool", "20260801", "fbt:asc")
            assert r_a != r_b  # 过期后重打，拿到新数据
            assert call_count == 2


# ──────────────────────────────────────────────────────────────────────────────
# A5 / A6：is_intraday_time 行为 + re-export 一致
# ──────────────────────────────────────────────────────────────────────────────


class TestIntradayTime:
    def test_periods_definition(self):
        """A5：INTRADAY_PERIODS 时段定义（09:25-11:30 / 13:01-15:05）。"""
        assert len(INTRADAY_PERIODS) == 2
        assert INTRADAY_PERIODS[0][0].hour == 9 and INTRADAY_PERIODS[0][0].minute == 25
        assert INTRADAY_PERIODS[1][1].hour == 15 and INTRADAY_PERIODS[1][1].minute == 5

    @pytest.mark.parametrize("dt, expected", [
        (datetime(2026, 8, 30, 10, 0), False),   # 周六
        (datetime(2026, 8, 28, 10, 0), True),   # 周五 10:00 盘中
        (datetime(2026, 8, 28, 12, 0), False),  # 周五 12:00 午休
        (datetime(2026, 8, 28, 15, 6), False),  # 周五 15:06 盘后
        (datetime(2026, 8, 28, 9, 25), True),   # 周五 09:25 竞价尾
        (datetime(2026, 8, 28, 13, 1), True),   # 周五 13:01 下午开盘
        (datetime(2026, 8, 28, 11, 30), True),  # 周五 11:30 上午收盘（含边界）
    ])
    def test_is_intraday_time(self, dt, expected):
        """A5：各时点盘中判定。"""
        assert is_intraday_time(dt) is expected

    def test_reexport_behavior_matches(self):
        """A6：seal_intraday.is_intraday_trading_time 与 vr_paths.is_intraday_time 行为一致。"""
        from risk.seal_intraday_collector import is_intraday_trading_time
        cases = [
            datetime(2026, 8, 30, 10, 0),   # 周六
            datetime(2026, 8, 28, 10, 0),   # 盘中
            datetime(2026, 8, 28, 12, 0),  # 午休
            datetime(2026, 8, 28, 15, 6),  # 盘后
        ]
        for dt in cases:
            assert is_intraday_trading_time(dt) == is_intraday_time(dt), \
                f"不一致 at {dt}"
