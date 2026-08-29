# -*- coding: utf-8 -*-
"""S104 hithink 数据源封装测试——结构性缺口唯一源（PS/PCF + 异动/飙升/热股榜）。

契约（spec §6 验收标准）：
- A1 valuation_snapshot 返 PS_TTM/PCF_TTM 非空
- A2 thscode 映射：600519→SH / 000001→SZ / 830xxx→BJ
- A3 hithink ok:false（CLI_BAD_ARGUMENT）→ 返空 dict/list，不透传 error envelope
- A4 subprocess 超时 → 返空不崩
- A5 full_valuation 返 ps_ttm/pcf_ttm 非空（hithink 补上），pe/pb 仍东财腾讯口径
- A6 hithink 失败时 full_valuation 降级返 ps_ttm=None（不崩）
- A7 query_skyrocket/hot_stock/anomaly AI 工具注册可调
- A8 端点返数据（冒烟在 plan 验证，测试用 mock）
"""
from __future__ import annotations

import json
from unittest.mock import MagicMock, patch

import pytest

from data.sources import hithink_src as hs


# ──────────────────────────────────────────────────────────────────────────────
# A2：thscode 映射
# ──────────────────────────────────────────────────────────────────────────────


class TestThscodeMapping:
    @pytest.mark.parametrize("code, expected_suffix", [
        ("600519", "SH"),   # 沪市
        ("688981", "SH"),   # 科创板（6 开头）
        ("000001", "SZ"),   # 深市主板
        ("000858", "SZ"),   # 深市
        ("300750", "SZ"),   # 创业板
        ("830799", "BJ"),   # 北交所
        ("830832", "BJ"),   # 北交所
    ])
    def test_to_thscode(self, code, expected_suffix):
        """A2：6 位 code → thscode 后缀映射（复用 tencent.get_prefix）。"""
        ths = hs._to_thscode(code)
        assert ths == f"{code}.{expected_suffix}"

    @pytest.mark.parametrize("ths, expected_bare", [
        ("600519.SH", "600519"),
        ("000001.SZ", "000001"),
        ("830799.BJ", "830799"),
        ("600519", "600519"),  # 无后缀原样
    ])
    def test_strip_thscode(self, ths, expected_bare):
        """A2 反映射：thscode → 裸 6 位 code。"""
        assert hs._strip_thscode(ths) == expected_bare


# ──────────────────────────────────────────────────────────────────────────────
# A1 / A3 / A4：_run_cli envelope 解析 + 失败/超时降级
# ──────────────────────────────────────────────────────────────────────────────


class TestRunCli:
    def test_ok_true_returns_data(self):
        """A1：ok:true → 返 data 字段（剥 envelope）。"""
        payload = {"ok": True, "data": {"item": [{"thscode": "600519.SH", "ps_ttm": 9.36}]}}
        mock_proc = MagicMock(returncode=0, stdout=json.dumps(payload), stderr="")
        with patch("data.sources.hithink_src.subprocess.run", return_value=mock_proc), \
             patch("data.sources.hithink_src.get_breaker") as mb:
            mb.return_value.allow_request.return_value = True
            data = hs._run_cli(["valuation", "snapshot"], 15)
            assert data == {"item": [{"thscode": "600519.SH", "ps_ttm": 9.36}]}

    def test_ok_false_returns_none_no_envelope_leak(self):
        """A3：ok:false（CLI_BAD_ARGUMENT）→ 返 None，不透传 error envelope。"""
        payload = {"ok": False, "error": {"code": "CLI_BAD_ARGUMENT", "message": "bad arg"}}
        mock_proc = MagicMock(returncode=0, stdout=json.dumps(payload), stderr="")
        with patch("data.sources.hithink_src.subprocess.run", return_value=mock_proc), \
             patch("data.sources.hithink_src.get_breaker") as mb:
            mb.return_value.allow_request.return_value = True
            data = hs._run_cli(["valuation", "snapshot"], 15)
            assert data is None  # 关键：返 None 不透传 error envelope

    def test_timeout_returns_none(self):
        """A4：subprocess 超时 → 返 None 不崩 + record_failure。"""
        import subprocess
        with patch("data.sources.hithink_src.subprocess.run", side_effect=subprocess.TimeoutExpired(cmd=[], timeout=15)), \
             patch("data.sources.hithink_src.get_breaker") as mb:
            mb.return_value.allow_request.return_value = True
            data = hs._run_cli(["valuation", "snapshot"], 15)
            assert data is None
            mb.return_value.record_failure.assert_called_once()

    def test_nonzero_exit_returns_none(self):
        """A3 边界：CLI 非零退出 → 返 None。"""
        mock_proc = MagicMock(returncode=2, stdout="", stderr="some error")
        with patch("data.sources.hithink_src.subprocess.run", return_value=mock_proc), \
             patch("data.sources.hithink_src.get_breaker") as mb:
            mb.return_value.allow_request.return_value = True
            data = hs._run_cli(["special", "skyrocket"], 30)
            assert data is None

    def test_breaker_open_returns_none(self):
        """A4 边界：熔断 OPEN → 快速失败返 None，不调 subprocess。"""
        with patch("data.sources.hithink_src.get_breaker") as mb:
            mb.return_value.allow_request.return_value = False
            with patch("data.sources.hithink_src.subprocess.run") as mock_run:
                data = hs._run_cli(["valuation", "snapshot"], 15)
                assert data is None
                mock_run.assert_not_called()  # 熔断中不调 subprocess


# ──────────────────────────────────────────────────────────────────────────────
# A1：valuation_snapshot 剥 item + thscode 还原
# ──────────────────────────────────────────────────────────────────────────────


class TestValuationSnapshot:
    def test_strips_envelope_and_restores_bare_code(self):
        """A1：valuation_snapshot 剥 envelope + thscode→裸 code + 缓存写入。"""
        hs._valuation_cache.clear()
        payload = {
            "ok": True,
            "data": {"item": [
                {"thscode": "600519.SH", "pe_ttm": 19.92, "ps_ttm": 9.36, "pcf_ttm": 13.62},
                {"thscode": "000001.SZ", "pe_ttm": 5.20, "ps_ttm": 1.70, "pcf_ttm": 0.63},
            ]},
        }
        mock_proc = MagicMock(returncode=0, stdout=json.dumps(payload), stderr="")
        with patch("data.sources.hithink_src.subprocess.run", return_value=mock_proc), \
             patch("data.sources.hithink_src.get_breaker") as mb:
            mb.return_value.allow_request.return_value = True
            out = hs.valuation_snapshot(["600519", "000001"])
            assert "600519" in out and "000001" in out  # 裸 code 键
            assert out["600519"]["ps_ttm"] == 9.36
            assert out["000001"]["pcf_ttm"] == 0.63

    def test_empty_codes_returns_empty(self):
        """边界：空 codes 列表 → 返 {} 不调 CLI。"""
        with patch("data.sources.hithink_src.subprocess.run") as mock_run:
            assert hs.valuation_snapshot([]) == {}
            mock_run.assert_not_called()

    def test_hithink_failure_returns_empty_dict(self):
        """A1 降级：hithink 失败 → 返 {}（PS/PCF 无数据，诚实缺失）。"""
        hs._valuation_cache.clear()
        with patch("data.sources.hithink_src._run_cli", return_value=None):
            out = hs.valuation_snapshot(["600519"])
            assert out == {}

    def test_5min_cache_hit(self):
        """缓存：5min TTL 内第二次命中缓存不重打 CLI。"""
        hs._valuation_cache.clear()
        call_count = 0
        payload = {"ok": True, "data": {"item": [{"thscode": "600519.SH", "ps_ttm": 9.36}]}}
        mock_proc = MagicMock(returncode=0, stdout=json.dumps(payload), stderr="")

        def fake_run(*a, **kw):
            nonlocal call_count
            call_count += 1
            return mock_proc

        with patch("data.sources.hithink_src.subprocess.run", side_effect=fake_run), \
             patch("data.sources.hithink_src.get_breaker") as mb:
            mb.return_value.allow_request.return_value = True
            r1 = hs.valuation_snapshot(["600519"])
            r2 = hs.valuation_snapshot(["600519"])  # 命中缓存
            assert r1 == r2
            assert call_count == 1  # 第二次命中缓存未重打


# ──────────────────────────────────────────────────────────────────────────────
# 飙升/热股/异动 归一
# ──────────────────────────────────────────────────────────────────────────────


class TestSpecialData:
    def test_skyrocket_normalizes_items(self):
        """飙升榜 item 归一：thscode→code + 保留 rank/heat。"""
        payload = {"ok": True, "data": {"item": [
            {"thscode": "000560.SZ", "name": "我爱我家", "rank": 1, "heat": "215357", "rank_change": 2, "rank_trend": "up"},
        ]}}
        mock_proc = MagicMock(returncode=0, stdout=json.dumps(payload), stderr="")
        with patch("data.sources.hithink_src.subprocess.run", return_value=mock_proc), \
             patch("data.sources.hithink_src.get_breaker") as mb:
            mb.return_value.allow_request.return_value = True
            out = hs.skyrocket()
            assert len(out) == 1
            assert out[0]["code"] == "000560"  # 裸 code
            assert out[0]["rank"] == 1
            assert out[0]["heat"] == "215357"

    def test_skyrocket_failure_returns_empty(self):
        """飙升榜失败 → 返 [] 不崩。"""
        with patch("data.sources.hithink_src._run_cli", return_value=None):
            assert hs.skyrocket() == []

    def test_anomaly_stock_rejects_over_50(self):
        """A3 边界：>50 只 thscodes → 返 []（hithink 限制 50）。"""
        codes = [f"{i:06d}" for i in range(51)]
        with patch("data.sources.hithink_src._run_cli") as mock_run:
            assert hs.anomaly_stock(codes) == []
            mock_run.assert_not_called()


# ──────────────────────────────────────────────────────────────────────────────
# A5 / A6：full_valuation 补 PS/PCF + 降级
# ──────────────────────────────────────────────────────────────────────────────


class TestFullValuationIntegration:
    def test_full_valuation_fills_ps_pcf(self, monkeypatch):
        """A5：full_valuation 调 hithink 补 PS/PCF（东财结构性缺）。"""
        import astock
        # mock 腾讯行情（东财口径 pe/pb 不变）
        monkeypatch.setattr(astock, "tencent_quote", lambda codes: {
            "600519": {"name": "茅台", "price": 1500, "mcap_yi": 1.88e4, "pe_ttm": 19.92, "pb": 6.46}
        })
        # mock hithink 返 PS/PCF
        monkeypatch.setattr("data.sources.hithink_src.valuation_snapshot",
                            lambda codes: {"600519": {"ps_ttm": 9.36, "pcf_ttm": 13.62,
                                                       "pe_ttm": 19.92, "pe_mrq": 18.2, "pb_mrq": 6.46}})
        # profit_forecast 走 DependencyMissing 快速跳过
        from data.sources.akshare_src import DependencyMissing
        monkeypatch.setattr(astock, "profit_forecast", lambda code: (_ for _ in ()).throw(DependencyMissing()))
        fv = astock.full_valuation("600519")
        assert fv["pe_ttm"] == 19.92      # 东财腾讯口径不变
        assert fv["pb"] == 6.46           # 东财腾讯口径不变
        assert fv["ps_ttm"] == 9.36       # hithink 补上
        assert fv["pcf_ttm"] == 13.62     # hithink 补上

    def test_full_valuation_degrades_on_hithink_failure(self, monkeypatch):
        """A6：hithink 失败 → PS/PCF 仍 None（东财本来也 None，不崩）。"""
        import astock
        monkeypatch.setattr(astock, "tencent_quote", lambda codes: {
            "600519": {"name": "茅台", "price": 1500, "mcap_yi": 1.88e4, "pe_ttm": 19.92, "pb": 6.46}
        })
        # hithink 返空（失败/熔断）
        monkeypatch.setattr("data.sources.hithink_src.valuation_snapshot", lambda codes: {})
        from data.sources.akshare_src import DependencyMissing
        monkeypatch.setattr(astock, "profit_forecast", lambda code: (_ for _ in ()).throw(DependencyMissing()))
        fv = astock.full_valuation("600519")
        assert fv["pe_ttm"] == 19.92      # 东财口径仍正常
        assert fv["pb"] == 6.46
        assert fv["ps_ttm"] is None       # hithink 失败，诚实 None
        assert fv["pcf_ttm"] is None


# ──────────────────────────────────────────────────────────────────────────────
# A7：AI 工具注册
# ──────────────────────────────────────────────────────────────────────────────


class TestAIToolsRegistration:
    def test_three_tools_registered(self):
        """A7：query_skyrocket / query_hot_stock / query_anomaly 三工具注册。"""
        from ai.tools import registry
        tools = registry.get_openai_tools()
        names = {t["function"]["name"] for t in tools}
        assert "query_skyrocket" in names
        assert "query_hot_stock" in names
        assert "query_anomaly" in names
