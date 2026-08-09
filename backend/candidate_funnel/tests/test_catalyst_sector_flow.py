# -*- coding: utf-8 -*-
"""S044 阶段2 单测：板块资金流 fetcher（push2 clist + ut + individual_info 行业）+ catalyst 接入。"""
from unittest import mock

import astock
from candidate_funnel.sources import catalyst
from predict.features import fund_flow as ff


class _Resp:
    """em_get 返回的 response 替身（带 .json()）。"""

    def __init__(self, d):
        self._d = d

    def json(self):
        return self._d


class TestFetchSectorFlow:
    def test_行业匹配板块f62返万元(self, monkeypatch):
        monkeypatch.setattr(astock, "individual_info", lambda c: {"行业": "电子"})
        monkeypatch.setattr(astock, "em_get", lambda *a, **k: _Resp(
            {"data": {"diff": {"0": {"f14": "电子", "f62": 26702635008.0}}}}))
        assert ff.fetch_sector_flow("000001") == round(26702635008.0 / 10000, 1)

    def test_行业未匹配返None(self, monkeypatch):
        monkeypatch.setattr(astock, "individual_info", lambda c: {"行业": "非板块"})
        monkeypatch.setattr(astock, "em_get", lambda *a, **k: _Resp(
            {"data": {"diff": {"0": {"f14": "电子", "f62": 1.0}}}}))
        assert ff.fetch_sector_flow("000001") is None

    def test_individual_info失败返None(self, monkeypatch):
        def boom(c):
            raise RuntimeError("net")
        monkeypatch.setattr(astock, "individual_info", boom)
        assert ff.fetch_sector_flow("000001") is None

    def test_无行业返None(self, monkeypatch):
        monkeypatch.setattr(astock, "individual_info", lambda c: {})
        assert ff.fetch_sector_flow("000001") is None

    def test_em_get失败返None(self, monkeypatch):
        monkeypatch.setattr(astock, "individual_info", lambda c: {"行业": "电子"})
        monkeypatch.setattr(astock, "em_get", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("net")))
        assert ff.fetch_sector_flow("000001") is None


class TestCatalystSectorFlowWired:
    def test_有值时填字段无missing(self, monkeypatch):
        monkeypatch.setattr(astock, "individual_info", lambda c: {"行业": "电子"})
        monkeypatch.setattr(astock, "em_get", lambda *a, **k: _Resp(
            {"data": {"diff": {"0": {"f14": "电子", "f62": 26702635008.0}}}}))
        with mock.patch.object(catalyst.astock, "announcements", return_value=[]), \
             mock.patch.object(catalyst.astock, "concept_blocks", return_value={"boards": []}):
            out = catalyst.fetch_catalyst(["000001"], "2026-08-08")
        assert out["000001"]["sector_flow"] == round(26702635008.0 / 10000, 1)
        assert "sector_flow" not in out["000001"]["missing"]

    def test_无值时标missing(self, monkeypatch):
        monkeypatch.setattr(astock, "individual_info", lambda c: {})  # 无行业 → None
        with mock.patch.object(catalyst.astock, "announcements", return_value=[]), \
             mock.patch.object(catalyst.astock, "concept_blocks", return_value={"boards": []}):
            out = catalyst.fetch_catalyst(["000001"], "2026-08-08")
        assert out["000001"]["sector_flow"] is None
        assert "sector_flow" in out["000001"]["missing"]
