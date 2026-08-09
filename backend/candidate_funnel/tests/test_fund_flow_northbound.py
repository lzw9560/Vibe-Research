# -*- coding: utf-8 -*-
"""S044 阶段1 单测：北向 fetcher（经 eastmoney_datacenter）+ sources 接入。"""
import astock
from predict.features import fund_flow as ff
from candidate_funnel.sources import fund_flow as src_ff


def _row(date: str, hmc_change):
    return {"TRADE_DATE": f"{date} 00:00:00", "SECURITY_CODE": "000001",
            "HMC_CHANGE": hmc_change, "HOLD_SHARES": 1000}


class TestFetchNorthbound:
    def test_无date取最新行HMC_CHANGE换算万元(self, monkeypatch):
        rows = [_row("2024-08-16", 209164947.42), _row("2024-08-15", -50000000)]
        monkeypatch.setattr(astock, "eastmoney_datacenter", lambda *a, **k: rows)
        assert ff.fetch_northbound("000001") == round(209164947.42 / 10000, 1)

    def test_按date取对应日(self, monkeypatch):
        rows = [_row("2024-08-16", 209164947.42), _row("2024-08-15", -50000000)]
        monkeypatch.setattr(astock, "eastmoney_datacenter", lambda *a, **k: rows)
        assert ff.fetch_northbound("000001", date="2024-08-15") == round(-50000000 / 10000, 1)

    def test_date无匹配行返None_如近期post_change(self, monkeypatch):
        # 2026-08-08 在 2024-08-19 停更后 → 无匹配行
        rows = [_row("2024-08-16", 209164947.42)]
        monkeypatch.setattr(astock, "eastmoney_datacenter", lambda *a, **k: rows)
        assert ff.fetch_northbound("000001", date="2026-08-08") is None

    def test_空rows返None(self, monkeypatch):
        monkeypatch.setattr(astock, "eastmoney_datacenter", lambda *a, **k: [])
        assert ff.fetch_northbound("000001") is None

    def test_HMC_CHANGE缺失返None(self, monkeypatch):
        rows = [{"TRADE_DATE": "2024-08-16 00:00:00", "HMC_CHANGE": None}]
        monkeypatch.setattr(astock, "eastmoney_datacenter", lambda *a, **k: rows)
        assert ff.fetch_northbound("000001") is None

    def test_异常返None(self, monkeypatch):
        def boom(*a, **k):
            raise RuntimeError("net")
        monkeypatch.setattr(astock, "eastmoney_datacenter", boom)
        assert ff.fetch_northbound("000001") is None


class TestSourcesFundFlowNorthbound:
    def test_fetch_northbound接入sources填字段(self, monkeypatch):
        monkeypatch.setattr(astock, "eastmoney_datacenter", lambda *a, **k: [_row("2024-08-16", 200000000)])
        monkeypatch.setattr(astock, "stock_fund_flow_120d", lambda c: [])
        monkeypatch.setattr(astock, "dragon_tiger_board", lambda c: {})
        out = src_ff.fetch_fund_flow(["000001"], "2024-08-16")
        assert out["000001"]["northbound"] == round(200000000 / 10000, 1)
        assert "northbound" not in out["000001"]["missing"]

    def test_fetch_northbound返None_标missing(self, monkeypatch):
        monkeypatch.setattr(astock, "eastmoney_datacenter", lambda *a, **k: [])
        monkeypatch.setattr(astock, "stock_fund_flow_120d", lambda c: [])
        monkeypatch.setattr(astock, "dragon_tiger_board", lambda c: {})
        out = src_ff.fetch_fund_flow(["000001"], "2026-08-08")
        assert out["000001"]["northbound"] is None
        assert "northbound" in out["000001"]["missing"]
