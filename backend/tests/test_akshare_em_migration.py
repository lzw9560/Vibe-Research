# -*- coding: utf-8 -*-
"""S220 — akshare_src stock_news / individual_info 迁 em_get 防封单测。

bug（v2 审查 C2 CRITICAL）：stock_news 调 ak.stock_news_em（akshare 内部 curl_cffi 直连
search-api-web.eastmoney.com）、individual_info 调 ak.stock_individual_info_em（akshare 内部
requests 直连 push2.eastmoney.com/api/qt/stock/get 不带 ut）——均绕过 em_get 熔断器 + 0.3s
限流 + 代理探测，已致 eastmoney push2 outage（fund_flow.py:313 _industry_of docstring 实测）。

修复：两函数改走 data.transport.eastmoney_get（em_get），保原中文键 shape，熔断→诚实空。
事实更正：akshare 实际端点是 JSON/JSONP 非 HTML（核于 venv akshare 源码），故测 JSON 解析
非 pandas.read_html/BS4。

mock 方式：monkeypatch data.transport.eastmoney_get（akshare_src 函数内惰性
`from data.transport import eastmoney_get as em_get`，patch 源模块属性即生效，对齐
_fetch_cyq_klines 惰性导入先例）。
"""
from __future__ import annotations

import json

import data.transport
import data.sources.akshare_src as akshare_src


class _FakeResp:
    """最小 Response stub：带 .text / .json()，供 em_get 返回。"""

    def __init__(self, text: str = "", payload: dict | None = None):
        self._text = text
        self._payload = payload

    @property
    def text(self) -> str:
        return self._text

    def json(self) -> dict:
        return self._payload or {}


# ── stock_news ─────────────────────────────────────────────────────────────

def _jsonp_payload(items: list[dict]) -> str:
    """包成 jQuery_cb_<n>({...json...}) JSONP 文本（对齐 search-api-web 真实响应形态）。"""
    inner = json.dumps(
        {"result": {"cmsArticleWebOld": items}}, ensure_ascii=False,
    )
    return f"jQuery_cb_1764599530176({inner})"


def _news_row(code: str, title: str, date: str, source: str,
              content: str = "c", image: str = "i") -> dict:
    """akshare search-api-web 原始条目键（date/mediaName/code/title/content/image）。"""
    return {
        "code": code, "title": title, "date": date,
        "mediaName": source, "content": content, "image": image,
    }


def test_stock_news_routes_through_em_get(monkeypatch):
    """stock_news 必须经 em_get 拉 search-api-web.eastmoney.com（不裸调 akshare）。"""
    calls: list[str] = []
    items = [_news_row("603777", "T1", "2026-09-20", "东财")]

    def fake_em_get(url, params=None, headers=None, timeout=10, **kw):
        calls.append(url)
        return _FakeResp(text=_jsonp_payload(items))

    monkeypatch.setattr(data.transport, "eastmoney_get", fake_em_get)
    rows = akshare_src.stock_news("603777")
    assert calls and "search-api-web.eastmoney.com" in calls[0]
    assert len(rows) == 1


def test_stock_news_preserves_chinese_keys_and_cleans_em_tags(monkeypatch):
    """返 list[dict] 含中文键 6 列 + <em> 标签清洗（对齐 models/news.py + mappers.news_from_raw）。"""
    items = [_news_row(
        "603777", "<em>贵州茅台</em>半年报", "2026-09-20", "证券时报",
        content="<em>净利润</em>　同比增\r\n",
    )]
    monkeypatch.setattr(data.transport, "eastmoney_get",
                        lambda *a, **k: _FakeResp(text=_jsonp_payload(items)))
    rows = akshare_src.stock_news("603777")
    assert len(rows) == 1
    r = rows[0]
    # 6 列中文键（shape 锁死，防 mappers.news_from_raw 静默退化）
    assert set(r.keys()) == {"关键词", "新闻标题", "新闻内容", "发布时间", "文章来源", "新闻链接"}
    assert r["关键词"] == "603777"
    assert r["新闻标题"] == "贵州茅台半年报"  # <em> 已清
    assert r["发布时间"] == "2026-09-20"
    assert r["文章来源"] == "证券时报"
    assert r["新闻链接"] == "http://finance.eastmoney.com/a/603777.html"
    # 内容：<em> 清 + 全角空格清 + \r\n 压空格
    assert "<em>" not in r["新闻内容"] and "净利润" in r["新闻内容"]
    assert "　" not in r["新闻内容"] and "\r\n" not in r["新闻内容"]


def test_stock_news_limit_truncates(monkeypatch):
    """limit 截断（对齐原 df.head(limit)）。"""
    items = [_news_row("603777", f"T{i}", "2026-09-20", "src") for i in range(10)]
    monkeypatch.setattr(data.transport, "eastmoney_get",
                        lambda *a, **k: _FakeResp(text=_jsonp_payload(items)))
    rows = akshare_src.stock_news("603777", limit=3)
    assert len(rows) == 3


def test_stock_news_breaker_open_returns_empty(monkeypatch):
    """em_get 熔断 OPEN raise RuntimeError → 返 []（诚实降级，不抛、不臆造）。"""

    def boom(url, *a, **k):
        raise RuntimeError("[CircuitBreaker:eastmoney] 熔断中")

    monkeypatch.setattr(data.transport, "eastmoney_get", boom)
    assert akshare_src.stock_news("603777") == []


def test_stock_news_bad_json_returns_empty(monkeypatch):
    """JSONP 剥壳/JSON 解析失败 → []（不抛）。"""
    monkeypatch.setattr(data.transport, "eastmoney_get",
                        lambda *a, **k: _FakeResp(text="not jsonp at all"))
    assert akshare_src.stock_news("603777") == []


def test_stock_news_missing_result_returns_empty(monkeypatch):
    """result.cmsArticleWebOld 缺 → []（akshare 也会返空 DataFrame）。"""
    monkeypatch.setattr(data.transport, "eastmoney_get",
                        lambda *a, **k: _FakeResp(text="cb({})"))
    assert akshare_src.stock_news("603777") == []


# ── individual_info ───────────────────────────────────────────────────────

def _indiv_data(code: str = "603777", name: str = "ST股") -> dict:
    """push2delay stock/get 真实 data dict（f-code → value，对齐 akshare 字段）。"""
    return {
        "f57": code, "f58": name, "f84": 125627.0, "f85": 125627.0,
        "f127": "白酒", "f116": 2334.56, "f117": 2334.56,
        "f189": "2001-08-27", "f43": 1849.0,
    }


def test_individual_info_routes_through_em_get_push2delay(monkeypatch):
    """individual_info 必须经 em_get 拉 push2delay + ut（非 push2 主 host、非 akshare 裸调）。"""
    captured: dict = {}

    def fake_em_get(url, params=None, headers=None, timeout=8, **kw):
        captured["url"] = url
        captured["params"] = params or {}
        return _FakeResp(payload={"data": _indiv_data()})

    monkeypatch.setattr(data.transport, "eastmoney_get", fake_em_get)
    akshare_src.individual_info("603777")
    assert "push2delay.eastmoney.com" in captured["url"]
    assert "/api/qt/stock/get" in captured["url"]
    assert captured["params"].get("ut")  # 必须带 ut（断连根因消除）
    assert captured["params"].get("secid") == "1.603777"  # 沪市 market=1


def test_individual_info_secid_market_for_shenzhen(monkeypatch):
    """深市 code（非 6 开头）secid market=0。"""
    captured: dict = {}

    def fake_em_get(url, params=None, headers=None, timeout=8, **kw):
        captured["params"] = params or {}
        return _FakeResp(payload={"data": _indiv_data("000002", "万科")})

    monkeypatch.setattr(data.transport, "eastmoney_get", fake_em_get)
    akshare_src.individual_info("000002")
    assert captured["params"].get("secid") == "0.000002"


def test_individual_info_preserves_chinese_keys(monkeypatch):
    """返 dict 含 9 中文键（对齐 data/mappers.company_info_from_individual_info 读 行业/上市时间）。"""
    monkeypatch.setattr(data.transport, "eastmoney_get",
                        lambda *a, **k: _FakeResp(payload={"data": _indiv_data()}))
    info = akshare_src.individual_info("603777")
    expected = {"股票代码", "股票简称", "总股本", "流通股", "行业",
                "总市值", "流通市值", "上市时间", "最新"}
    assert set(info.keys()) == expected
    assert info["股票代码"] == "603777"
    assert info["行业"] == "白酒"
    assert info["上市时间"] == "2001-08-27"


def test_individual_info_breaker_open_returns_empty_dict(monkeypatch):
    """em_get 熔断 raise → 返 {}（诚实 falsy，下游走 missing 标记，同 chip_distribution 范式）。"""

    def boom(url, *a, **k):
        raise RuntimeError("[CircuitBreaker:eastmoney] 熔断中")

    monkeypatch.setattr(data.transport, "eastmoney_get", boom)
    assert akshare_src.individual_info("603777") == {}


def test_individual_info_data_none_returns_empty_dict(monkeypatch):
    """响应 data=null（股票退市/未上市）→ {}（akshare pd.notna filter 净效果：空 DataFrame→{}）。"""
    monkeypatch.setattr(data.transport, "eastmoney_get",
                        lambda *a, **k: _FakeResp(payload={"data": None}))
    assert akshare_src.individual_info("603777") == {}


def test_individual_info_partial_fields_only_mapped(monkeypatch):
    """data 只含部分 f-code → 只映射出现的（缺项不出现，与 akshare pd.notna filter 一致）。"""
    monkeypatch.setattr(data.transport, "eastmoney_get",
                        lambda *a, **k: _FakeResp(payload={"data": {"f57": "603777", "f127": "白酒"}}))
    info = akshare_src.individual_info("603777")
    assert info == {"股票代码": "603777", "行业": "白酒"}
