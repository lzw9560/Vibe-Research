# -*- coding: utf-8 -*-
"""S105 hithink 直连 HTTP 数据源测试（替代 S104 subprocess mock）。

契约（spec §6 验收标准）：
- A1 valuation_snapshot 返 PS_TTM/PCF_TTM 非空（直连，延迟 ≤0.3s）
- A2 code==0 成功取 data；code!=0 失败返 None 不透传 envelope
- A3 重试：429/503 连续 → 重试 3 次后失败返 None + record_failure
- A4 业务码 4001（retryable）触发重试；非 retryable 直接失败
- A5 Key：env 优先 / env 无 fallback keychain / 都无 DependencyMissing
- A6 下游零改动（full_valuation / AI 工具 / 端点 不动）
- A7 skyrocket/hot_stock 30 条；anomaly 盘后空
- A8 5min 缓存仍生效
"""
from __future__ import annotations

import json
import urllib.error
from unittest.mock import MagicMock, patch

import pytest

from data.sources import hithink_src as hs


@pytest.fixture(autouse=True)
def _clear_cache():
    hs._valuation_cache.clear()
    yield
    hs._valuation_cache.clear()


def _mock_response(code, data, status=200):
    """构造 urllib.urlopen 返回的 mock context manager（body={code,message,data}）。"""
    body = json.dumps({"code": code, "message": "ok" if code == 0 else "err",
                       "request_id": "rid-test", "data": data}).encode()
    cm = MagicMock()
    cm.__enter__ = lambda self: MagicMock(read=lambda: body, status=status)
    cm.__exit__ = lambda *a: False
    return cm


# ── A2：envelope 转译（code==0 / code!=0）─────────────────────────────────────


class TestEnvelopeTranslation:
    def test_code_zero_returns_data(self):
        """A2：code==0 → 返 data（剥 envelope）。"""
        with patch("data.sources.hithink_src.urllib.request.urlopen",
                   return_value=_mock_response(0, {"item": [{"thscode": "600519.SH"}]})), \
             patch("data.sources.hithink_src.get_breaker") as mb, \
             patch("data.sources.hithink_src._resolve_api_key", return_value="test-key"):
            mb.return_value.allow_request.return_value = True
            data = hs._http_get("/api/a-share/valuations/snapshot", {"thscodes": "600519.SH"})
            assert data == {"item": [{"thscode": "600519.SH"}]}
            mb.return_value.record_success.assert_called_once()

    def test_code_nonzero_returns_none_no_envelope_leak(self):
        """A2：code!=0（业务错误）→ 返 None，不透传 error envelope。"""
        with patch("data.sources.hithink_src.urllib.request.urlopen",
                   return_value=_mock_response(1001, None)), \
             patch("data.sources.hithink_src.get_breaker") as mb, \
             patch("data.sources.hithink_src._resolve_api_key", return_value="test-key"):
            mb.return_value.allow_request.return_value = True
            data = hs._http_get("/api/any", {})
            assert data is None
            mb.return_value.record_failure.assert_called_once()

    def test_code_nonzero_retryable_triggers_retry(self):
        """A4：业务码 4001（retryable）触发重试，耗尽后 None。"""
        with patch("data.sources.hithink_src.urllib.request.urlopen",
                   return_value=_mock_response(4001, None)), \
             patch("data.sources.hithink_src.get_breaker") as mb, \
             patch("data.sources.hithink_src._resolve_api_key", return_value="test-key"), \
             patch("data.sources.hithink_src.time.sleep"):
            mb.return_value.allow_request.return_value = True
            data = hs._http_get("/api/any", {})
            assert data is None


# ── A3：有界重试（HTTP 429/503 + 网络超时）───────────────────────────────────


class TestRetry:
    def test_http_429_retries_then_fails(self):
        """A3：HTTP 429 连续 → 重试 maxAttempts 次后 None。"""
        err = urllib.error.HTTPError("url", 429, "Too Many", {}, None)
        with patch("data.sources.hithink_src.urllib.request.urlopen", side_effect=err), \
             patch("data.sources.hithink_src.get_breaker") as mb, \
             patch("data.sources.hithink_src._resolve_api_key", return_value="test-key"), \
             patch("data.sources.hithink_src.time.sleep"):
            mb.return_value.allow_request.return_value = True
            data = hs._http_get("/api/any", {})
            assert data is None
            assert hs.urllib.request.urlopen.call_count == hs._MAX_ATTEMPTS

    def test_http_500_not_retryable_fails_fast(self):
        """A3 边界：HTTP 500（非 retryable）→ 不重试直接 None。"""
        err = urllib.error.HTTPError("url", 500, "Server Err", {}, None)
        with patch("data.sources.hithink_src.urllib.request.urlopen", side_effect=err), \
             patch("data.sources.hithink_src.get_breaker") as mb, \
             patch("data.sources.hithink_src._resolve_api_key", return_value="test-key"):
            mb.return_value.allow_request.return_value = True
            data = hs._http_get("/api/any", {})
            assert data is None
            assert hs.urllib.request.urlopen.call_count == 1

    def test_timeout_retries_then_fails(self):
        """A4：网络超时（URLError）→ 重试后 None。"""
        with patch("data.sources.hithink_src.urllib.request.urlopen",
                   side_effect=urllib.error.URLError("timeout")), \
             patch("data.sources.hithink_src.get_breaker") as mb, \
             patch("data.sources.hithink_src._resolve_api_key", return_value="test-key"), \
             patch("data.sources.hithink_src.time.sleep"):
            mb.return_value.allow_request.return_value = True
            data = hs._http_get("/api/any", {})
            assert data is None

    def test_breaker_open_fast_fail(self):
        """A3 边界：熔断 OPEN → 快速失败返 None，不调 urlopen。"""
        with patch("data.sources.hithink_src.get_breaker") as mb:
            mb.return_value.allow_request.return_value = False
            with patch("data.sources.hithink_src.urllib.request.urlopen") as mock_open:
                data = hs._http_get("/api/any", {})
                assert data is None
                mock_open.assert_not_called()


# ── A5：API Key 解析 ──────────────────────────────────────────────────────────


class TestApiKeyResolve:
    def test_env_priority(self, monkeypatch):
        """A5：env HITHINK_FINANCE_API_KEY 优先。"""
        monkeypatch.setenv("HITHINK_FINANCE_API_KEY", "env-key-123")
        with patch("data.sources.hithink_src.subprocess.run") as mock_run:
            assert hs._resolve_api_key() == "env-key-123"
            mock_run.assert_not_called()

    def test_keychain_fallback(self, monkeypatch):
        """A5：env 无时 fallback macOS keychain（security 命令）。"""
        monkeypatch.delenv("HITHINK_FINANCE_API_KEY", raising=False)
        mock_r = MagicMock(returncode=0, stdout="kc-key-456\n")
        with patch("data.sources.hithink_src.subprocess.run", return_value=mock_r):
            assert hs._resolve_api_key() == "kc-key-456"

    def test_both_missing_raises_dependency_missing(self, monkeypatch):
        """A5：env 无 + keychain 读失败 → DependencyMissing。"""
        monkeypatch.delenv("HITHINK_FINANCE_API_KEY", raising=False)
        mock_r = MagicMock(returncode=1, stdout="")
        with patch("data.sources.hithink_src.subprocess.run", return_value=mock_r):
            from data.sources._common import DependencyMissing
            with pytest.raises(DependencyMissing):
                hs._resolve_api_key()


# ── A1/A8：valuation_snapshot 剥 item + thscode 还原 + 缓存 ─────────────────────


class TestValuationSnapshot:
    def test_strips_and_restores_bare_code(self):
        """A1：valuation_snapshot 剥 envelope + thscode→裸 code。"""
        payload = {"item": [
            {"thscode": "600519.SH", "ps_ttm": 9.36, "pcf_ttm": 13.62, "pe_ttm": 19.92},
            {"thscode": "000001.SZ", "ps_ttm": 1.70, "pcf_ttm": 0.63, "pe_ttm": 5.20},
        ]}
        with patch("data.sources.hithink_src.urllib.request.urlopen",
                   return_value=_mock_response(0, payload)), \
             patch("data.sources.hithink_src.get_breaker") as mb, \
             patch("data.sources.hithink_src._resolve_api_key", return_value="test-key"):
            mb.return_value.allow_request.return_value = True
            out = hs.valuation_snapshot(["600519", "000001"])
            assert out["600519"]["ps_ttm"] == 9.36
            assert out["000001"]["pcf_ttm"] == 0.63

    def test_empty_codes_no_call(self):
        with patch("data.sources.hithink_src.urllib.request.urlopen") as mock_open:
            assert hs.valuation_snapshot([]) == {}
            mock_open.assert_not_called()

    def test_failure_returns_empty(self):
        """A1 降级：直连失败 → 返 {}（PS/PCF 诚实缺失）。"""
        with patch("data.sources.hithink_src._http_get", return_value=None):
            assert hs.valuation_snapshot(["600519"]) == {}

    def test_5min_cache_hit(self):
        """A8：5min TTL 内第二次命中缓存不重打。"""
        call_count = 0
        payload = {"item": [{"thscode": "600519.SH", "ps_ttm": 9.36}]}

        def fake_open(*a, **kw):
            nonlocal call_count
            call_count += 1
            return _mock_response(0, payload)

        with patch("data.sources.hithink_src.urllib.request.urlopen", side_effect=fake_open), \
             patch("data.sources.hithink_src.get_breaker") as mb, \
             patch("data.sources.hithink_src._resolve_api_key", return_value="test-key"):
            mb.return_value.allow_request.return_value = True
            r1 = hs.valuation_snapshot(["600519"])
            r2 = hs.valuation_snapshot(["600519"])
            assert r1 == r2
            assert call_count == 1


# ── A7：飙升/热股/异动 归一 ───────────────────────────────────────────────────


class TestSpecialData:
    def test_skyrocket_normalizes(self):
        """A7：飙升榜 thscode→code + 保留 rank/heat。"""
        payload = {"item": [{"thscode": "000560.SZ", "name": "我爱我家",
                              "rank": 1, "heat": "215357", "rank_change": 2, "rank_trend": "up"}]}
        with patch("data.sources.hithink_src._http_get", return_value=payload):
            out = hs.skyrocket()
            assert out[0]["code"] == "000560"
            assert out[0]["rank"] == 1

    def test_skyrocket_failure_raises(self):
        """S120：源断（_http_get None）→ raise RuntimeError（非返 [] 喂 LLM 当"无榜"）。
        源断经 registry.execute 兜成 {"error"} 喂 LLM（诚实），router→502。
        """
        with patch("data.sources.hithink_src._http_get", return_value=None):
            with pytest.raises(RuntimeError, match="飙升榜暂不可达"):
                hs.skyrocket()

    def test_skyrocket_legit_empty_returns_empty(self):
        """S120：合法空榜（code==0, item=[]）→ 返 [] 不抛（盘后空诚实保留，与源断 raise 区分）。"""
        with patch("data.sources.hithink_src._http_get", return_value={"item": []}):
            assert hs.skyrocket() == []

    def test_hot_stock_failure_raises(self):
        """S120：热股榜源断 → raise（同 skyrocket 范式）。"""
        with patch("data.sources.hithink_src._http_get", return_value=None):
            with pytest.raises(RuntimeError, match="热股榜暂不可达"):
                hs.hot_stock()

    def test_anomaly_list_failure_raises_and_legit_empty(self):
        """S120：异动榜源断 → raise；盘后合法空（item=[]）仍 [] 不抛。"""
        with patch("data.sources.hithink_src._http_get", return_value=None):
            with pytest.raises(RuntimeError, match="异动榜暂不可达"):
                hs.anomaly_list()
        with patch("data.sources.hithink_src._http_get", return_value={"item": []}):
            assert hs.anomaly_list() == []

    def test_anomaly_stock_rejects_over_50(self):
        """A7 边界：>50 thscodes → 返 []。"""
        codes = [f"{i:06d}" for i in range(51)]
        with patch("data.sources.hithink_src._http_get") as mock_get:
            assert hs.anomaly_stock(codes) == []
            mock_get.assert_not_called()


# ── A6：下游零改动（full_valuation + AI 工具）─────────────────────────────────


class TestDownstreamUnchanged:
    def test_full_valuation_fills_ps_pcf(self, monkeypatch):
        """A6：full_valuation 仍调 hithink 补 PS/PCF（下游零改动）。"""
        import astock
        monkeypatch.setattr(astock, "tencent_quote", lambda codes: {
            "600519": {"name": "茅台", "price": 1500, "mcap_yi": 1.88e4, "pe_ttm": 19.92, "pb": 6.46}
        })
        monkeypatch.setattr("data.sources.hithink_src.valuation_snapshot",
                            lambda codes: {"600519": {"ps_ttm": 9.36, "pcf_ttm": 13.62,
                                                       "pe_ttm": 19.92, "pe_mrq": 18.2, "pb_mrq": 6.46}})
        from data.sources.akshare_src import DependencyMissing
        monkeypatch.setattr(astock, "profit_forecast", lambda c: (_ for _ in ()).throw(DependencyMissing()))
        fv = astock.full_valuation("600519")
        assert fv["ps_ttm"] == 9.36 and fv["pcf_ttm"] == 13.62
        assert fv["pe_ttm"] == 19.92

    def test_three_ai_tools_registered(self):
        """A6：3 AI 工具仍注册。"""
        from ai.tools import registry
        names = {t["function"]["name"] for t in registry.get_openai_tools()}
        assert {"query_skyrocket", "query_hot_stock", "query_anomaly"} <= names


# ── thscode 映射（S104 保留）──────────────────────────────────────────────────


class TestThscodeMapping:
    @pytest.mark.parametrize("code, suffix", [
        ("600519", "SH"), ("688981", "SH"), ("000001", "SZ"),
        ("000858", "SZ"), ("300750", "SZ"), ("830799", "BJ"),
    ])
    def test_to_thscode(self, code, suffix):
        assert hs._to_thscode(code) == f"{code}.{suffix}"

    @pytest.mark.parametrize("ths, bare", [
        ("600519.SH", "600519"), ("000001.SZ", "000001"), ("830799.BJ", "830799"),
    ])
    def test_strip_thscode(self, ths, bare):
        assert hs._strip_thscode(ths) == bare


# ── S167：auction_snapshot 集合竞价快照（§44 最未证否盘中 edge）────────────────


class TestAuctionSnapshot:
    """S167：集合竞价端点接线（spec §2 "竞价量比 needs new source integration" 闭合）。"""

    _PAYLOAD = {
        "timestamp": 1788714324149,
        "auction_phase": "live",
        "data_status": "ready",
        "total": 2,
        "item": [
            {"thscode": "600519.SH", "ticker": "600519", "name": "贵州茅台",
             "auction_price": 1295.88, "auction_pct": -0.231, "auction_volume": 179.43,
             "auction_amount": 23251975, "auction_unmatched": 0.57,
             "auction_turnover_pct": 0.0014, "auction_yesterday_ratio_pct": 1.011,
             "auction_volume_ratio": 1.7089, "pre_close_price": 1298.88,
             "open_price": 1295.88, "last_price": 1330.0,
             "float_market_cap": 1662608529330},
            {"thscode": "000001.SZ", "ticker": "000001", "name": "平安银行",
             "auction_price": 11.86, "auction_pct": -0.1684, "auction_volume": 5094.0,
             "auction_amount": 6041484.0, "auction_unmatched": 236.0,
             "auction_turnover_pct": 0.0026, "auction_yesterday_ratio_pct": 0.4609,
             "auction_volume_ratio": 2.269, "pre_close_price": 11.88,
             "open_price": 11.86, "last_price": 11.89,
             "float_market_cap": 230733594542.99},
        ],
    }

    def test_strips_thscode_and_maps_auction_fields(self):
        """归一：thscode→裸 code + 透传竞价字段 + 顶层 phase/status 透传每行。"""
        with patch("data.sources.hithink_src._http_get", return_value=self._PAYLOAD):
            out = hs.auction_snapshot(["600519", "000001"], stage="live")
        assert len(out) == 2
        r = next(r for r in out if r["code"] == "600519")
        assert r["name"] == "贵州茅台"
        assert r["stage"] == "live"
        assert r["auction_volume_ratio"] == 1.7089  # §44 关键信号
        assert r["auction_price"] == 1295.88
        assert r["source_timestamp"] == 1788714324149
        assert r["auction_phase"] == "live"
        assert r["data_status"] == "ready"

    def test_empty_codes_no_call(self):
        with patch("data.sources.hithink_src._http_get") as mock_get:
            assert hs.auction_snapshot([]) == []
            mock_get.assert_not_called()

    def test_invalid_stage_returns_empty(self):
        """stage 非 live/final → 返 []（endpoint enum 校验，不发请求）。"""
        with patch("data.sources.hithink_src._http_get") as mock_get:
            assert hs.auction_snapshot(["600519"], stage="invalid") == []
            mock_get.assert_not_called()

    def test_failure_returns_empty_not_raise(self):
        """降级：_http_get None（熔断/离线/Key 缺）→ 返 [] 不抛（调用方降级记 degraded）。"""
        with patch("data.sources.hithink_src._http_get", return_value=None):
            assert hs.auction_snapshot(["600519"], stage="final") == []

    def test_batches_over_100_codes(self):
        """endpoint 硬限 ≤100 thscodes/批，>100 自动分批（两批，下批失败部分降级）。"""
        codes = [f"{i:06d}" for i in range(150)]
        with patch("data.sources.hithink_src._http_get", return_value=self._PAYLOAD) as mock_get:
            out = hs.auction_snapshot(codes, stage="final")
        assert mock_get.call_count == 2  # 分两批
        assert len(out) == 4  # 每批返 2，两批合并 4（code 重复无碍，累积时 UPSERT 去重）

    def test_partial_batch_failure_degrades(self):
        """首批成功次批 None（熔断）→ 返首批部分，不整体抛。"""
        responses = iter([self._PAYLOAD, None])
        with patch("data.sources.hithink_src._http_get", side_effect=lambda *a, **k: next(responses)):
            codes = [f"{i:06d}" for i in range(150)]
            out = hs.auction_snapshot(codes, stage="final")
        assert len(out) == 2  # 仅首批 2 行（次批 None 跳过）
