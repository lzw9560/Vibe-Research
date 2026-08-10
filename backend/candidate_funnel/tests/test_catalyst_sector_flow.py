# -*- coding: utf-8 -*-
"""S044 R2 板块资金流 fetcher 单测（2026-08-10 live 修复版）。

行业：push2delay stock/get + ut（f127，如「白酒Ⅱ」）；板块资金流：push2 clist(fid=f62)+ut（TTL 缓存）；
归一化（去 Ⅰ/Ⅱ/Ⅲ 后缀）匹配。不再依赖 akshare individual_info（缺 ut 被断连）。
"""
from unittest import mock

import astock
import pytest
from candidate_funnel.sources import catalyst
from predict.features import fund_flow as ff


class _Resp:
    """em_get 返回的 response 替身（带 .json()）。"""

    def __init__(self, d):
        self._d = d

    def json(self):
        return self._d


def _make_em_get(industry="电子", boards=None, clist_calls=None, pages=None):
    """按 URL 分发的 em_get 替身。

    pages：板块分多页提供 {pn: {name: f62}}（模拟 496 板块分页）；缺省单页 boards。
    clist 请求 pn 超出提供页 → 空 diff（终止翻页）。clist_calls 传入 list 记录 clist 调用。
    """
    boards = boards if boards is not None else {"电子": 26702635008.0}
    pages = pages if pages is not None else {1: boards}

    def fake(url, params=None, **kw):
        if "push2delay" in url and "clist" not in url:
            assert (params or {}).get("ut"), "行业请求必须带 ut"
            return _Resp({"data": {"f127": industry} if industry else {}})
        if clist_calls is not None:
            clist_calls.append(url)
        pn = int((params or {}).get("pn", "1"))
        page = pages.get(pn, {})
        return _Resp({"data": {"diff": {
            str(i): {"f14": name, "f62": f62} for i, (name, f62) in enumerate(page.items())
        }}})

    return fake


@pytest.fixture(autouse=True)
def _clear_sector_cache(monkeypatch):
    monkeypatch.setattr(ff, "_sector_cache", {})


class TestFetchSectorFlow:
    def test_行业匹配板块f62返万元(self, monkeypatch):
        monkeypatch.setattr(astock, "em_get", _make_em_get())
        assert ff.fetch_sector_flow("000001") == round(26702635008.0 / 10000, 1)

    def test_级别后缀归一化匹配(self, monkeypatch):
        """f127 返「白酒Ⅱ」、板块列表为「白酒」——去后缀后匹配（live 实测口径）。"""
        monkeypatch.setattr(astock, "em_get", _make_em_get(
            industry="白酒Ⅱ", boards={"白酒": 1234567890.0}))
        assert ff.fetch_sector_flow("600519") == round(1234567890.0 / 10000, 1)

    def test_行业未匹配返None(self, monkeypatch):
        monkeypatch.setattr(astock, "em_get", _make_em_get(industry="非板块"))
        assert ff.fetch_sector_flow("000001") is None

    def test_行业请求失败返None(self, monkeypatch):
        def boom(url, params=None, **kw):
            if "push2delay" in url:
                raise RuntimeError("net")
            return _Resp({"data": {"diff": {}}})
        monkeypatch.setattr(astock, "em_get", boom)
        assert ff.fetch_sector_flow("000001") is None

    def test_无行业返None(self, monkeypatch):
        monkeypatch.setattr(astock, "em_get", _make_em_get(industry=""))
        assert ff.fetch_sector_flow("000001") is None

    def test_clist失败返None(self, monkeypatch):
        def half(url, params=None, **kw):
            if "push2delay" in url:
                return _Resp({"data": {"f127": "电子"}})
            raise RuntimeError("throttled")
        monkeypatch.setattr(astock, "em_get", half)
        assert ff.fetch_sector_flow("000001") is None

    def test_clist缓存复用_两候选无新请求(self, monkeypatch):
        """漏斗逐候选调用——首个候选填满缓存后，后续候选不再发 clist（防重复探测触发限流）。"""
        calls: list = []
        monkeypatch.setattr(astock, "em_get", _make_em_get(clist_calls=calls))
        assert ff.fetch_sector_flow("000001") is not None
        first = len(calls)
        assert first > 0
        assert ff.fetch_sector_flow("000002") is not None
        assert len(calls) == first  # 第二候选命中缓存，无新 clist 请求

    def test_分页取全板块(self, monkeypatch):
        """~496 板块分页返回——第一页没有的板块（白酒Ⅱ在第 2 页）也能匹配。"""
        monkeypatch.setattr(astock, "em_get", _make_em_get(
            industry="白酒Ⅱ",
            pages={1: {"银行": 100.0}, 2: {"白酒Ⅱ": 923719808.0}}))
        assert ff.fetch_sector_flow("600519") == round(923719808.0 / 10000, 1)

    def test_push2断连降级push2delay(self, monkeypatch):
        """push2 主host 限流断连 → 降级 push2delay（与 market_turnover_rank 同款）。"""
        def fallback(url, params=None, **kw):
            if url.startswith("https://push2.eastmoney.com"):
                raise RuntimeError("RemoteDisconnected")
            if "push2delay" in url and "clist" not in url:
                return _Resp({"data": {"f127": "银行Ⅱ"}})
            if int((params or {}).get("pn", "1")) > 1:
                return _Resp({"data": {"diff": {}}})  # 翻页终止
            return _Resp({"data": {"diff": {"0": {"f14": "银行", "f62": 50000.0}}}})
        monkeypatch.setattr(astock, "em_get", fallback)
        assert ff.fetch_sector_flow("000001") == 5.0

    def test_行业请求走push2delay且带ut(self, monkeypatch):
        seen: dict = {}

        def spy(url, params=None, **kw):
            if "push2delay" in url:
                seen["url"] = url
                seen["params"] = params
                return _Resp({"data": {"f127": "电子"}})
            return _Resp({"data": {"diff": {"0": {"f14": "电子", "f62": 1.0}}}})

        monkeypatch.setattr(astock, "em_get", spy)
        ff.fetch_sector_flow("600519")
        assert "push2delay.eastmoney.com" in seen["url"]
        assert seen["params"]["secid"] == "1.600519"  # 6 开头 → 沪市 market 1
        assert seen["params"]["ut"] == ff._EM_PUSH2_UT

    def test_历史日期防未来函数返None_零请求(self, monkeypatch):
        """date < 今日 → None：端点仅当日值，不得拿今日资金流冒充历史数据（且不发请求）。"""
        calls: list = []
        monkeypatch.setattr(astock, "em_get", lambda *a, **k: calls.append(1) or _Resp({"data": {}}))
        assert ff.fetch_sector_flow("000001", "2026-07-01") is None
        assert calls == []


class TestCatalystSectorFlowWired:
    def test_有值时填字段无missing(self, monkeypatch):
        monkeypatch.setattr(astock, "em_get", _make_em_get())
        with mock.patch.object(catalyst.astock, "announcements", return_value=[]), \
             mock.patch.object(catalyst.astock, "concept_blocks", return_value={"boards": []}):
            out = catalyst.fetch_catalyst(["000001"], "2099-01-01")  # 非历史日（>= 今日）才走 live 取数
        assert out["000001"]["sector_flow"] == round(26702635008.0 / 10000, 1)
        assert "sector_flow" not in out["000001"]["missing"]

    def test_无值时标missing(self, monkeypatch):
        monkeypatch.setattr(astock, "em_get", _make_em_get(industry=""))  # 无行业 → None
        with mock.patch.object(catalyst.astock, "announcements", return_value=[]), \
             mock.patch.object(catalyst.astock, "concept_blocks", return_value={"boards": []}):
            out = catalyst.fetch_catalyst(["000001"], "2099-01-01")  # 非历史日（>= 今日）才走 live 取数
        assert out["000001"]["sector_flow"] is None
        assert "sector_flow" in out["000001"]["missing"]
